"""Focused host checks for the RTL8821CE native AirPort candidate.

Compiles the actual candidate functions (extracted from source) with host
substitutes for IOKit/kernel services, under ASan/UBSan:

  1. firmware: real rtw88_firmware.c + real embedded blob table; synthetic
     malformed metadata tables; allocation balance.
  2. peer caps: real HT/VHT IE parser and mac80211-style own/peer intersection,
     valid/truncated/malformed IEs and random fuzzing.
  3. station registry: real register/unregister/find/iterate and NAPI poll
     bracketing, including a concurrent RX-lookup stress under ASan.
  4. diagnostic ring: real append/candidate-log/non-consuming copy/consuming
     read, wrap-around and record truncation.
  5. timer/power/teardown ordering: source-structure assertions (IOKit
     workloop semantics cannot be executed on the host).

This is not a kernel, transport, or hardware test.
"""
from pathlib import Path
import json, random, re, subprocess, sys, tempfile, zlib

ROOT = Path(__file__).resolve().parents[1] / 'driver/RTL88WiFi'
SRC = ROOT / 'src'
CFLAGS = ['-g', '-O1', '-fsanitize=address,undefined', '-fno-sanitize-recover=all',
          '-fno-omit-frame-pointer', '-Wall', '-Wno-unused-function']
results = {}


def extract(text, signature):
    start = text.index(signature)
    i = text.index('{', start) + 1
    depth = 1
    while depth:
        depth += (text[i] == '{') - (text[i] == '}')
        i += 1
    return text[start:i]


def build_and_run(name, sources, tmp, cc='clang', extra=(), args=()):
    exe = tmp / name
    files = []
    for fname, body in sources:
        p = tmp / fname
        p.write_text(body)
        files.append(str(p))
    subprocess.run([cc, *CFLAGS, '-w', *extra, *files, '-o', str(exe)], check=True)
    out = subprocess.run([str(exe), *args], capture_output=True, text=True)
    if out.returncode:
        raise SystemExit(f'{name} failed rc={out.returncode}\n{out.stdout[-3000:]}\n{out.stderr[-3000:]}')
    return out.stdout


def defines(header, prefixes):
    out = []
    for line in (SRC / header).read_text().splitlines():
        m = re.match(r'#define\s+(\w+)\s+(.+?)\s*(/\*.*)?$', line)
        if m and m.group(1).startswith(prefixes):
            out.append(f'#define {m.group(1)} {m.group(2)}')
    return '\n'.join(out)


# ---------------------------------------------------------------- firmware
FW_SHIM = r'''
#include <stdint.h>
#include <stddef.h>
#include <stdlib.h>
#include <string.h>
#include <stdio.h>
#include <stdarg.h>
#include <zlib.h>
static long live_bytes = 0, live_allocs = 0;
void *IOMalloc(size_t n){ live_bytes += n; live_allocs++; return malloc(n); }
void *IOMallocZero(size_t n){ live_bytes += n; live_allocs++; return calloc(1, n); }
void IOFree(void *p, size_t n){ if(!p) return; live_bytes -= n; live_allocs--; free(p); }
void rtw88_candidate_log(const char *f, ...){ (void)f; }
'''


def firmware_checks(tmp):
    fw_src = (SRC / 'compat/rtw88_firmware.c').read_text()
    body = fw_src.replace('#include <libkern/zlib.h>', '').replace('#include "fw_blobs.h"', '')
    body = re.sub(r'#include <(IOKit|libkern|kern|mach|sys)/[^>]+>\n', '', body)
    body = re.sub(r'#include "[^"]+"\n', '', body)
    body = body.replace('#define IOLog rtw88_candidate_log', '#define IOLog(...) ((void)0)')
    blob_h = (SRC / 'compat/fw_blobs.h').read_text()
    blob_c = (SRC / 'compat/fw_blobs.c').read_text()

    # Reconstruct the embedded blobs for an independent Python reference.
    names = re.findall(r'\{\s*"([^"]+)"\s*,\s*(\w+)\s*,\s*(\w+|\d+)\s*,\s*(\w+|\d+)\s*\}', blob_c)
    main_real = FW_SHIM + blob_h + body + r'''
struct firmware; int request_firmware_nowait(struct module*,int,const char*,struct device*,unsigned,void*,void(*)(const struct firmware*,void*));
struct firmware_view { size_t size; const uint8_t *data; size_t alloc; };
static const struct firmware *got;
static void cont(const struct firmware *fw, void *ctx){ (void)ctx; got = fw; }
int main(void){
  int n = 0;
  for (int i = 0; rtw88_fw_blobs[i].name; i++) {
    got = NULL;
    char path[256]; snprintf(path, sizeof path, "rtw88/%s", rtw88_fw_blobs[i].name);
    request_firmware_nowait(NULL,0,path,NULL,0,NULL,cont);
    if (!got) { printf("FAIL %s\n", rtw88_fw_blobs[i].name); return 1; }
    const struct firmware_view *v = (const void*)got;
    uLong crc = crc32(0L, Z_NULL, 0); crc = crc32(crc, v->data, (uInt)v->size);
    printf("BLOB %s %zu %zu %zu %08lx\n", rtw88_fw_blobs[i].name, rtw88_fw_blobs[i].compressed_size, v->size, v->alloc, crc);
    release_firmware(got); n++;
  }
  got = (void*)1; request_firmware_nowait(NULL,0,"rtw88/does_not_exist.bin",NULL,0,NULL,cont);
  if (got) { printf("FAIL missing blob returned firmware\n"); return 1; }
  printf("COUNT %d LIVE %ld %ld\n", n, live_bytes, live_allocs);
  return (live_bytes || live_allocs) ? 1 : 0;
}
'''
    out = build_and_run('fw_real', [('fw_real.c', main_real), ('fw_blobs.c', '#include "fw_blobs.h"\n' + blob_c.split('#include "fw_blobs.h"', 1)[-1])],
                        tmp, extra=['-I', str(SRC / 'compat'), '-lz'])
    blobs = [l.split() for l in out.splitlines() if l.startswith('BLOB')]
    assert blobs and out.strip().endswith('LIVE 0 0'), out
    # Independent reference: parse the byte arrays and inflate with Python zlib.
    ref = {}
    for m in re.finditer(r'static const uint8_t (\w+)\[\]\s*=\s*\{([^}]*)\}', blob_c):
        ref[m.group(1)] = bytes(int(x, 0) for x in m.group(2).replace('\n', ' ').split(',') if x.strip())
    table = re.findall(r'\{\s*"([^"]+)"\s*,\s*(\w+)\s*,\s*(\w+)\s*,\s*(\w+)\s*\}', blob_c)
    checked = []
    for name, arr, csz, osz in table:
        data = ref[arr]
        raw = zlib.decompress(data)
        row = next(b for b in blobs if b[1] == name)
        assert int(row[2]) == len(data), (name, row, len(data))
        assert int(row[3]) == len(raw) == int(row[4]), (name, row, len(raw))
        assert int(row[5], 16) == zlib.crc32(raw), name
        checked.append({'name': name, 'compressed': len(data), 'original': len(raw),
                        'crc32': f'{zlib.crc32(raw):08x}'})
    assert any(c['name'] == 'rtw8821c_fw.bin' for c in checked), 'RTL8821C firmware missing'

    # Malformed metadata tables against the same loader.
    good = zlib.compress(bytes(range(256)) * 64)
    def arr(b): return ','.join(str(x) for x in b)
    raw_len = 256 * 64
    synthetic = f'''
static const uint8_t good[] = {{{arr(good)}}};
static const uint8_t bad[] = {{{arr(good[:len(good)//2])}}};
static const uint8_t junk[] = {{1,2,3,4,5,6,7,8}};
const struct rtw88_fw_blob rtw88_fw_blobs[] = {{
  {{"ok.bin", good, sizeof good, {raw_len}}},
  {{"short_orig.bin", good, sizeof good, {raw_len - 1}}},
  {{"long_orig.bin", good, sizeof good, {raw_len + 1}}},
  {{"truncated.bin", bad, sizeof bad, {raw_len}}},
  {{"junk.bin", junk, sizeof junk, 64}},
  {{"zero_orig.bin", good, sizeof good, 0}},
  {{"zero_comp.bin", good, 0, {raw_len}}},
  {{"null.bin", 0, 16, 16}},
  {{"huge.bin", good, sizeof good, (size_t)1 << 33}},
  {{0,0,0,0}}
}};
'''
    main_syn = FW_SHIM + blob_h + synthetic + body + r'''
struct firmware_view { size_t size; const uint8_t *data; size_t alloc; };
static const struct firmware *got;
static void cont(const struct firmware *fw, void *ctx){ (void)ctx; got = fw; }
int main(void){
  const char *names[] = {"ok.bin","short_orig.bin","long_orig.bin","truncated.bin","junk.bin","zero_orig.bin","zero_comp.bin","null.bin","huge.bin"};
  for (unsigned i = 0; i < sizeof names/sizeof *names; i++) {
    got = NULL; request_firmware_nowait(NULL,0,names[i],NULL,0,NULL,cont);
    printf("%s %s\n", names[i], got ? "LOADED" : "REJECTED");
    if (got) release_firmware(got);
  }
  printf("LIVE %ld %ld\n", live_bytes, live_allocs);
  return (live_bytes || live_allocs) ? 1 : 0;
}
'''
    out = build_and_run('fw_syn', [('fw_syn.c', main_syn)], tmp, extra=['-I', str(SRC / 'compat'), '-lz'])
    expect = {'ok.bin': 'LOADED'}
    for line in out.splitlines()[:-1]:
        n, st = line.split()
        assert st == expect.get(n, 'REJECTED'), line
    assert out.strip().endswith('LIVE 0 0'), out
    results['firmware'] = {'embedded_blobs_verified': checked,
                           'malformed_metadata': out.strip().splitlines(),
                           'allocation_balance': 'zero live allocations after release'}


# ---------------------------------------------------------------- peer caps
def peer_caps_checks(tmp):
    s = (SRC / 'kext/RTW88IEEE80211.cpp').read_text()
    struct = s[s.index('struct rtw88_peer_caps {'):s.index('};', s.index('struct rtw88_peer_caps {')) + 2]
    code = struct + '\n' + extract(s, 'static void rtw88_parse_peer_caps(') + '\n' + extract(s, 'static void rtw88_restrict_peer_caps(')
    macros = defines('compat/net/mac80211.h', ('IEEE80211_HT_CAP_', 'IEEE80211_VHT_CAP_', 'IEEE80211_HT_MCS_'))
    prog = r'''
#include <cstdint>
#include <cstring>
#include <cstdio>
#include <cstdlib>
#include <vector>
typedef uint8_t u8; typedef uint16_t u16; typedef uint32_t u32; typedef uint16_t __le16;
#define cpu_to_le16(x) ((uint16_t)(x))
#define le16_to_cpu(x) ((uint16_t)(x))
#define WLAN_EID_HT_CAPABILITY 45
#define WLAN_EID_VHT_CAPABILITY 191
''' + macros + r'''
struct ieee80211_mcs_info { u8 rx_mask[10]; __le16 rx_highest; u8 tx_params; u8 reserved[3]; };
struct ieee80211_sta_ht_cap { u16 cap; bool ht_supported; u8 ampdu_factor; u8 ampdu_density; struct ieee80211_mcs_info mcs; };
struct ieee80211_vht_mcs_info { __le16 rx_mcs_map, rx_highest, tx_mcs_map, tx_highest; };
struct ieee80211_sta_vht_cap { bool vht_supported; u32 cap; struct ieee80211_vht_mcs_info vht_mcs; };
struct ieee80211_supported_band { struct ieee80211_sta_ht_cap ht_cap; struct ieee80211_sta_vht_cap vht_cap; };
''' + code + r'''
#define CHECK(c) do { if(!(c)) { printf("FAIL line %d: %s\n", __LINE__, #c); exit(1);} } while(0)
/* Own capabilities as rtw_init_ht_cap/rtw_init_vht_cap build them for
 * RTL8821C: 1 stream, rx_ldpc=false, tx_stbc=false, rf_path_num=1, 40 MHz. */
static ieee80211_supported_band own8821c(){
  ieee80211_supported_band b{}; auto &h=b.ht_cap; h.ht_supported=true;
  h.cap = IEEE80211_HT_CAP_SGI_20 | IEEE80211_HT_CAP_MAX_AMSDU | (1<<8) |
          IEEE80211_HT_CAP_SUP_WIDTH_20_40 | IEEE80211_HT_CAP_DSSSCCK40 | IEEE80211_HT_CAP_SGI_40;
  h.mcs.tx_params = IEEE80211_HT_MCS_TX_DEFINED; h.mcs.rx_mask[0]=0xff; h.mcs.rx_mask[4]=1;
  auto &v=b.vht_cap; v.vht_supported=true;
  v.cap = 2 /*MAX_MPDU_11454*/ | IEEE80211_VHT_CAP_SHORT_GI_80 | 0x100 /*RXSTBC_1*/ |
          IEEE80211_VHT_CAP_HTC_VHT | IEEE80211_VHT_CAP_MAX_A_MPDU_LENGTH_EXPONENT_MASK |
          IEEE80211_VHT_CAP_MU_BEAMFORMEE_CAPABLE | IEEE80211_VHT_CAP_SU_BEAMFORMEE_CAPABLE | (3u<<13);
  v.vht_mcs.rx_mcs_map = v.vht_mcs.tx_mcs_map = 0xfffe;
  return b;
}
static void put_ht(std::vector<u8>&v,u16 cap,const u8 mask[4],u8 ampdu){
  u8 d[26]={}; d[0]=cap; d[1]=cap>>8; d[2]=ampdu; memcpy(d+3,mask,4); d[4+3-1]=mask[3]; d[7]=1 /*MCS32*/; d[13]=0x2c; d[14]=1; d[15]=1;
  v.push_back(WLAN_EID_HT_CAPABILITY); v.push_back(26); v.insert(v.end(),d,d+26);
}
static void put_vht(std::vector<u8>&v,u32 cap,u16 rx,u16 tx){
  u8 d[12]={(u8)cap,(u8)(cap>>8),(u8)(cap>>16),(u8)(cap>>24),(u8)rx,(u8)(rx>>8),0,0,(u8)tx,(u8)(tx>>8),0,0};
  v.push_back(WLAN_EID_VHT_CAPABILITY); v.push_back(12); v.insert(v.end(),d,d+12);
}
int main(){
  auto own = own8821c();
  const u8 ap2ss[4]={0xff,0xff,0,0};
  u16 apHt = IEEE80211_HT_CAP_LDPC_CODING | IEEE80211_HT_CAP_SUP_WIDTH_20_40 | IEEE80211_HT_CAP_SGI_20 |
             IEEE80211_HT_CAP_SGI_40 | IEEE80211_HT_CAP_TX_STBC | (1<<8) | IEEE80211_HT_CAP_GRN_FLD | IEEE80211_HT_CAP_MAX_AMSDU;
  u32 apVht = 1 | IEEE80211_VHT_CAP_RXLDPC | IEEE80211_VHT_CAP_SHORT_GI_80 | IEEE80211_VHT_CAP_SHORT_GI_160 |
              IEEE80211_VHT_CAP_TXSTBC | 0x100 | IEEE80211_VHT_CAP_SU_BEAMFORMER_CAPABLE |
              IEEE80211_VHT_CAP_MU_BEAMFORMER_CAPABLE | (1u<<16) | (3u<<23);
  /* 1. Realistic 2x2 AP: parse and intersect. */
  std::vector<u8> ies={0,3,'a','b','c'}; put_ht(ies,apHt,ap2ss,0x17); put_vht(ies,apVht,0xfffa,0xfffa);
  rtw88_peer_caps p{}; rtw88_parse_peer_caps(ies.data(),ies.size(),&p);
  CHECK(p.have_ht && p.have_vht && p.ht.ampdu_factor==3 && p.ht.ampdu_density==5);
  CHECK(p.ht.cap==apHt && p.ht.mcs.rx_mask[1]==0xff && p.vht.cap==apVht);
  rtw88_restrict_peer_caps(&p,&own);
  CHECK(!(p.ht.cap & IEEE80211_HT_CAP_LDPC_CODING));   /* own rx_ldpc=false */
  CHECK(!(p.ht.cap & IEEE80211_HT_CAP_RX_STBC));       /* own has no TX STBC */
  CHECK(p.ht.cap & IEEE80211_HT_CAP_TX_STBC);          /* own can RX STBC */
  CHECK(!(p.ht.cap & IEEE80211_HT_CAP_GRN_FLD));
  CHECK((p.ht.cap & IEEE80211_HT_CAP_SGI_20) && (p.ht.cap & IEEE80211_HT_CAP_SGI_40));
  CHECK(p.ht.mcs.rx_mask[0]==0xff && p.ht.mcs.rx_mask[1]==0 && p.ht.mcs.rx_mask[4]==1);
  CHECK(!(p.vht.cap & IEEE80211_VHT_CAP_RXSTBC_MASK)); /* own rf_path_num=1: no TXSTBC */
  CHECK(p.vht.cap & IEEE80211_VHT_CAP_TXSTBC);
  CHECK(p.vht.cap & IEEE80211_VHT_CAP_RXLDPC);         /* mac80211 keeps VHT RXLDPC as-is */
  CHECK((p.vht.cap & IEEE80211_VHT_CAP_SHORT_GI_80) && !(p.vht.cap & IEEE80211_VHT_CAP_SHORT_GI_160));
  CHECK((p.vht.cap & IEEE80211_VHT_CAP_SU_BEAMFORMER_CAPABLE) && (p.vht.cap & IEEE80211_VHT_CAP_MU_BEAMFORMER_CAPABLE));
  CHECK((p.vht.cap & 3)==1 && (p.vht.cap & IEEE80211_VHT_CAP_MAX_A_MPDU_LENGTH_EXPONENT_MASK)==(3u<<23));
  CHECK(p.vht.vht_mcs.rx_mcs_map==0xfffe && p.vht.vht_mcs.tx_mcs_map==0xfffe);
  /* rtw_update_sta_info() derivation: VHT peer -> stbc from RXSTBC (0), ldpc from RXLDPC. */
  /* 2. AP limited to MCS 0-7 on VHT and legacy MPDU size. */
  ies.clear(); put_ht(ies,IEEE80211_HT_CAP_SGI_20,ap2ss,0); put_vht(ies,0,0xfffc,0xfffc);
  p={}; rtw88_parse_peer_caps(ies.data(),ies.size(),&p); rtw88_restrict_peer_caps(&p,&own);
  CHECK(p.vht.vht_mcs.rx_mcs_map==0xfffc && (p.vht.cap&3)==0);
  /* 3. Own without VHT (2.4 GHz band) drops VHT; own NULL drops all. */
  auto own24 = own; own24.vht_cap = {};
  ies.clear(); put_ht(ies,apHt,ap2ss,0); put_vht(ies,apVht,0xfffa,0xfffa);
  p={}; rtw88_parse_peer_caps(ies.data(),ies.size(),&p); rtw88_restrict_peer_caps(&p,&own24);
  CHECK(p.have_ht && !p.have_vht);
  p={}; rtw88_parse_peer_caps(ies.data(),ies.size(),&p); rtw88_restrict_peer_caps(&p,nullptr);
  CHECK(!p.have_ht && !p.have_vht);
  /* VHT without HT is not usable either. */
  ies.clear(); put_vht(ies,apVht,0xfffa,0xfffa);
  p={}; rtw88_parse_peer_caps(ies.data(),ies.size(),&p); CHECK(!p.have_ht && p.have_vht);
  rtw88_restrict_peer_caps(&p,&own); CHECK(!p.have_vht);
  /* 4. Truncated and short IEs are ignored; first valid IE wins. */
  ies.clear(); put_ht(ies,apHt,ap2ss,0); ies.resize(ies.size()-1);
  p={}; rtw88_parse_peer_caps(ies.data(),ies.size(),&p); CHECK(!p.have_ht);
  u8 shortHt[]={WLAN_EID_HT_CAPABILITY,25}; std::vector<u8> sh(shortHt,shortHt+2); sh.resize(27,0xff);
  p={}; rtw88_parse_peer_caps(sh.data(),sh.size(),&p); CHECK(!p.have_ht);
  u8 shortVht[]={WLAN_EID_VHT_CAPABILITY,11}; std::vector<u8> sv(shortVht,shortVht+2); sv.resize(13,0xff);
  p={}; rtw88_parse_peer_caps(sv.data(),sv.size(),&p); CHECK(!p.have_vht);
  ies.clear(); put_ht(ies,IEEE80211_HT_CAP_SGI_20,ap2ss,0); put_ht(ies,apHt,ap2ss,3);
  p={}; rtw88_parse_peer_caps(ies.data(),ies.size(),&p); CHECK(p.ht.cap==IEEE80211_HT_CAP_SGI_20);
  /* Assoc response first, cached beacon second: response wins, cache fills gaps. */
  std::vector<u8> resp, cache; put_ht(resp,IEEE80211_HT_CAP_SGI_20,ap2ss,0); put_ht(cache,apHt,ap2ss,0); put_vht(cache,apVht,0xfffa,0xfffa);
  p={}; rtw88_parse_peer_caps(resp.data(),resp.size(),&p); rtw88_parse_peer_caps(cache.data(),cache.size(),&p);
  CHECK(p.ht.cap==IEEE80211_HT_CAP_SGI_20 && p.have_vht);
  p={}; rtw88_parse_peer_caps(nullptr,100,&p); rtw88_parse_peer_caps(ies.data(),0,&p); rtw88_parse_peer_caps(ies.data(),1,&p);
  CHECK(!p.have_ht && !p.have_vht);
  /* 5. Fuzz: exact-size heap buffers so ASan catches any over-read. */
  srand(8821);
  for (int it=0; it<50000; it++) {
    size_t n = rand()%200; u8 *b=(u8*)malloc(n?n:1);
    for (size_t i=0;i<n;i++) b[i]=rand();
    if (n>2 && (it&1)) b[0] = (it&2) ? WLAN_EID_HT_CAPABILITY : WLAN_EID_VHT_CAPABILITY;
    rtw88_peer_caps q{}; rtw88_parse_peer_caps(b,n,&q); rtw88_restrict_peer_caps(&q,&own);
    /* Consumer copies caps only when have_ht/have_vht remain set. */
    CHECK(!q.have_vht || q.have_ht);
    if (q.have_ht) {
      CHECK(!(q.ht.cap & (IEEE80211_HT_CAP_LDPC_CODING|IEEE80211_HT_CAP_RX_STBC|IEEE80211_HT_CAP_GRN_FLD)));
      for (int i=1;i<10;i++) if(i!=4) CHECK(q.ht.mcs.rx_mask[i]==0);
      CHECK((q.ht.mcs.rx_mask[4] & ~1)==0);
    }
    if (q.have_vht) {
      CHECK(!(q.vht.cap & (IEEE80211_VHT_CAP_RXSTBC_MASK|IEEE80211_VHT_CAP_SHORT_GI_160)));
      CHECK((q.vht.vht_mcs.rx_mcs_map & 0xfffc)==0xfffc && (q.vht.vht_mcs.tx_mcs_map & 0xfffc)==0xfffc);
    }
    free(b);
  }
  printf("PEER OK\n"); return 0;
}
'''
    out = build_and_run('peer', [('peer.cpp', prog)], tmp, cc='clang++', extra=['-std=c++17'])
    assert out.strip() == 'PEER OK', out
    results['peer_caps'] = ('passed: 2x2 AP intersected to RTL8821C 1x1 (HT LDPC/RX-STBC cleared, '
                            'VHT RX-STBC cleared, MCS masks limited to 1SS), band/NULL/VHT-without-HT '
                            'handling, truncated/short/duplicate IEs, response-over-cache priority, '
                            '50,000 fuzz inputs under ASan/UBSan')


# ---------------------------------------------------------------- station registry
def station_checks(tmp):
    c = (SRC / 'compat/rtw88_compat.c').read_text()
    parts = [extract(c, 'void rtw88_register_sta('), extract(c, 'bool rtw88_unregister_sta('),
             extract(c, 'void ieee80211_iterate_stations_atomic('),
             extract(c, 'struct ieee80211_sta *ieee80211_find_sta(struct ieee80211_vif *vif'),
             extract(c, 'struct ieee80211_sta *ieee80211_find_sta_by_ifaddr('),
             extract(c, 'static void rtw88_napi_work_fn(')]
    prog = r'''
#include <pthread.h>
#include <stdint.h>
#include <stdbool.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <unistd.h>
#include <stddef.h>
#define ETH_ALEN 6
typedef uint8_t u8;
typedef pthread_t thread_t;
static thread_t current_thread(void){ return pthread_self(); }
static void IOSleep(unsigned ms){ usleep(ms*1000); }
static int timeouts = 0;
static void rtw88_candidate_log(const char *f, ...){ if(strstr(f,"timed out")) timeouts++; }
#define container_of(p,t,m) ((t*)((char*)(p)-offsetof(t,m)))
struct work_struct { int dummy; };
struct workqueue_struct; static struct workqueue_struct *g_datapath_wq = NULL;
static void queue_work(struct workqueue_struct*w, struct work_struct*k){ (void)w; (void)k; }
struct napi_struct { struct work_struct work; bool enabled; int weight; int (*poll)(struct napi_struct*, int); };
struct ieee80211_hw { int x; };
struct ieee80211_vif { uint8_t addr[ETH_ALEN]; };
struct ieee80211_sta { uint8_t addr[ETH_ALEN]; long drv_priv[8]; };
static struct ieee80211_hw *g_rtw88_hw;
static uint32_t g_rtw88_rx_poll_active = 0;
static thread_t g_rtw88_rx_poll_thread = NULL;
static struct ieee80211_vif *g_rtw88_sta_vif = NULL;
static struct ieee80211_sta *g_rtw88_sta = NULL;
''' + '\n'.join(parts) + r'''
#define CHECK(c) do { if(!(c)) { printf("FAIL line %d: %s\n", __LINE__, #c); exit(1);} } while(0)
static struct ieee80211_hw hw; static struct ieee80211_vif vif = {{2,0,0,0,0,1}};
static int iter_count; static void iter(void *d, struct ieee80211_sta *s){ (void)d; (void)s; iter_count++; }
/* Mirrors rtw_rx_addr_match_iter: look up, then update per-station RSSI. */
static volatile int stop_rx, hold_ms;
static int rx_poll(struct napi_struct *n, int budget){
  (void)n; (void)budget;
  static const uint8_t ap[6]={7,8,9,10,11,12};
  for (int i=0;i<64;i++){
    struct ieee80211_sta *s = ieee80211_find_sta_by_ifaddr(&hw, ap, vif.addr);
    if (s) { if (hold_ms) usleep(hold_ms*1000); s->drv_priv[0]++; }
  }
  return 0;
}
static struct napi_struct napi = { {0}, true, 64, rx_poll };
static void *rx_thread(void *a){ (void)a; while(!stop_rx) rtw88_napi_work_fn(&napi.work); return NULL; }
/* Deauth processed inside the poll: unregister must not wait for itself. */
static struct ieee80211_sta *self_sta; static int self_ok;
static int self_poll(struct napi_struct *n, int b){ (void)n;(void)b; self_ok = rtw88_unregister_sta(self_sta); return 0; }
static int stuck_poll(struct napi_struct *n, int b){ (void)n;(void)b; while(!stop_rx) usleep(1000); return 0; }
int main(void){
  g_rtw88_hw = &hw;
  struct ieee80211_sta *s = calloc(1,sizeof *s); memcpy(s->addr,(uint8_t[]){7,8,9,10,11,12},6);
  uint8_t other[6]={1,1,1,1,1,1};
  CHECK(ieee80211_find_sta(&vif,s->addr)==NULL);
  ieee80211_iterate_stations_atomic(&hw,iter,NULL); CHECK(iter_count==0);
  rtw88_register_sta(&vif,s);
  CHECK(ieee80211_find_sta(&vif,s->addr)==s && ieee80211_find_sta(&vif,other)==NULL);
  CHECK(ieee80211_find_sta(NULL,s->addr)==NULL && ieee80211_find_sta(&vif,NULL)==NULL);
  CHECK(ieee80211_find_sta_by_ifaddr(&hw,s->addr,vif.addr)==s && ieee80211_find_sta_by_ifaddr(&hw,s->addr,NULL)==s);
  CHECK(ieee80211_find_sta_by_ifaddr(&hw,s->addr,other)==NULL && ieee80211_find_sta_by_ifaddr(NULL,s->addr,NULL)==NULL);
  ieee80211_iterate_stations_atomic(&hw,iter,NULL); ieee80211_iterate_stations_atomic(NULL,iter,NULL); CHECK(iter_count==1);
  struct ieee80211_sta decoy; CHECK(rtw88_unregister_sta(&decoy) && ieee80211_find_sta(&vif,s->addr)==s);
  CHECK(rtw88_unregister_sta(s) && ieee80211_find_sta(&vif,s->addr)==NULL);
  CHECK(rtw88_unregister_sta(NULL)); free(s);
  /* Unregister must wait for a poll that already holds the pointer. */
  s = calloc(1,sizeof *s); memcpy(s->addr,(uint8_t[]){7,8,9,10,11,12},6); rtw88_register_sta(&vif,s);
  hold_ms = 20; pthread_t t; pthread_create(&t,NULL,rx_thread,NULL); usleep(5000);
  CHECK(rtw88_unregister_sta(s)); free(s);   /* ASan reports UAF if the wait is wrong */
  /* Stress: repeated register/unregister/free against a live RX thread. */
  hold_ms = 0;
  for (int i=0;i<3000;i++){
    s = calloc(1,sizeof *s); memcpy(s->addr,(uint8_t[]){7,8,9,10,11,12},6);
    rtw88_register_sta(&vif,s); if(i&1) usleep(50);
    CHECK(rtw88_unregister_sta(s)); free(s);
  }
  stop_rx = 1; pthread_join(t,NULL); stop_rx = 0;
  /* Self-unregister from inside the poll returns immediately. */
  self_sta = calloc(1,sizeof *self_sta); rtw88_register_sta(&vif,self_sta);
  struct napi_struct sn = { {0}, true, 64, self_poll }; rtw88_napi_work_fn(&sn.work);
  CHECK(self_ok && g_rtw88_rx_poll_active==0 && g_rtw88_rx_poll_thread==NULL); free(self_sta);
  /* A poll that never finishes: bounded wait, caller told not to free. */
  s = calloc(1,sizeof *s); rtw88_register_sta(&vif,s);
  struct napi_struct st = { {0}, true, 64, stuck_poll };
  pthread_t t2; pthread_create(&t2,NULL,(void*(*)(void*))rtw88_napi_work_fn,&st.work); usleep(10000);
  CHECK(!rtw88_unregister_sta(s) && timeouts==1);
  stop_rx = 1; pthread_join(t2,NULL); free(s);
  printf("STATION OK\n"); return 0;
}
'''
    out = build_and_run('station', [('station.c', prog)], tmp, extra=['-pthread'])
    assert out.strip() == 'STATION OK', out
    results['station_registry'] = ('passed: lookup/iteration/vif/localaddr matching, foreign-station '
                                   'unregister no-op, unregister waits for an RX poll holding the pointer, '
                                   '3,000 register/unregister/free cycles against a live RX lookup thread '
                                   'under ASan, self-unregister inside poll, bounded timeout returns false')


# ---------------------------------------------------------------- diagnostic ring
def ring_checks(tmp):
    c = (SRC / 'compat/rtw88_compat.c').read_text()
    ring_decl = c[c.index('static char rtw88_log_ring['):c.index('static void rtw88_log_append')]
    parts = [extract(c, 'static void rtw88_log_append('), extract(c, 'void rtw88_candidate_log('),
             extract(c, 'uint32_t rtw88_copy_log('), extract(c, 'uint32_t rtw88_read_log(')]
    prog = r'''
#include <pthread.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <stdarg.h>
typedef pthread_mutex_t IOSimpleLock;
static IOSimpleLock lockobj = PTHREAD_MUTEX_INITIALIZER;
static void IOSimpleLockLock(IOSimpleLock *l){ pthread_mutex_lock(l); }
static void IOSimpleLockUnlock(IOSimpleLock *l){ pthread_mutex_unlock(l); }
static uint64_t ticks = 0; static uint64_t mach_absolute_time(void){ return ++ticks; }
static void IOLog(const char *f, ...){ (void)f; }
static IOSimpleLock *rtw88_log_lock = NULL;
''' + ring_decl + '\n'.join(parts) + r'''
#define CHECK(c) do { if(!(c)) { printf("FAIL line %d: %s\n", __LINE__, #c); exit(1);} } while(0)
#define CAP 32768
static char a[CAP], b[CAP];
int main(void){
  uint64_t total = 7;
  rtw88_candidate_log("dropped before init\n");
  CHECK(rtw88_copy_log(a, CAP, &total) == 0 && a[0]==0 && total==7);
  rtw88_log_lock = &lockobj;
  CHECK(rtw88_copy_log(a, CAP, &total) == 0 && total == 0);
  CHECK(rtw88_copy_log(NULL, CAP, &total) == 0 && rtw88_copy_log(a, 0, &total) == 0);
  rtw88_candidate_log("rtw88: M%d submission=%d\n", 2, 1);
  uint32_t n = rtw88_copy_log(a, CAP, &total);
  CHECK(n == strlen("[ticks=2] rtw88: M2 submission=1\n") && strcmp(a, "[ticks=2] rtw88: M2 submission=1\n")==0);
  CHECK(rtw88_copy_log(b, CAP, NULL) == n && strcmp(a,b)==0);  /* non-consuming */
  /* small capacity: NUL-terminated, oldest bytes */
  char small[8]; CHECK(rtw88_copy_log(small, sizeof small, NULL) == 7 && small[7]==0 && memcmp(small,"[ticks=",7)==0);
  /* Long messages are bounded by the 512/576-byte buffers. */
  char big[2000]; memset(big,'x',sizeof big-1); big[sizeof big-1]=0;
  rtw88_candidate_log("%s", big);
  n = rtw88_copy_log(a, CAP, &total);
  CHECK(total == n && n < 34 + 576);
  /* Wrap: stream a known pattern well past the capacity. */
  char *stream = malloc(200000); size_t slen = strlen(a); memcpy(stream, a, slen);
  for (int i = 0; slen < 150000; i++) {
    char rec[128]; snprintf(rec, sizeof rec, "rtw88: DIAG sample=%d state=5\n", i);
    char full[256]; snprintf(full, sizeof full, "[ticks=%llu] %s", (unsigned long long)ticks + 1, rec);
    rtw88_candidate_log("%s", rec); memcpy(stream + slen, full, strlen(full)); slen += strlen(full);
  }
  n = rtw88_copy_log(a, CAP, &total);
  CHECK(total == slen && n == CAP - 1 && a[n] == 0);
  CHECK(memcmp(a, stream + slen - n, n) == 0);   /* newest CAP-1 bytes, in order */
  CHECK(rtw88_copy_log(b, CAP, NULL) == n && memcmp(a,b,n)==0);
  /* Consuming reader drains; snapshots then see an empty ring but the byte counter remains. */
  char *drain = malloc(CAP); CHECK(rtw88_read_log(drain, CAP, ) == n && memcmp(drain, a, n) == 0);
  CHECK(rtw88_copy_log(a, CAP, &total) == 0 && total == slen);
  free(stream); free(drain);
  printf("RING OK\n"); return 0;
}
'''.replace('rtw88_read_log(drain, CAP, )', 'rtw88_read_log(drain, CAP)')
    out = build_and_run('ring', [('ring.c', prog)], tmp)
    assert out.strip() == 'RING OK', out
    results['diagnostic_ring'] = ('passed: pre-init drop, empty/NULL/zero-capacity, record format with '
                                  'ticks, repeated snapshots are non-consuming, small-capacity truncation, '
                                  'long message bounded, 150 KB stream keeps newest 32,767 bytes in order '
                                  'with exact byte counter, consuming reader drains without resetting counter')


# ---------------------------------------------------------------- timer/power review
def timer_checks():
    a = (SRC / 'kext/RTL88WiFi.cpp').read_text()
    td = extract(a, 'void RTL88WiFi::teardown()')
    order = ['__atomic_store_n(&_shutdown, true', '_diagnosticsTimer->disable()', '_diagnosticsTimer->cancelTimeout()',
             'removeEventSource(_diagnosticsTimer)', '_diagnosticsTimer->cancelTimeout()', '_diagnosticsTimer->release()',
             'IOFree(_diagnosticsBuffer, 32768)', 'rtw88_set_tx_resume_cb(nullptr)']
    pos = 0
    for tok in order:
        pos = td.index(tok, pos) + 1
    fired = extract(a, 'void RTL88WiFi::diagnosticsTimerFired(')
    assert fired.index('self->_shutdown') < fired.index('_diagnosticsInHardware, true')
    assert fired.index('_diagnosticsInHardware, true') < fired.index('_pmTransition') < fired.index('rtw88_debug_dump_tx_state')
    assert fired.index('rtw88_debug_dump_tx_state') < fired.index('_diagnosticsInHardware, false') < fired.index('rtw88_copy_log')
    assert 'rtw88_copy_log(self->_diagnosticsBuffer, 32768' in fired and 'setTimeoutMS(5000)' in fired
    for fn in ('IOReturn RTL88WiFi::quiesceForSystemSleep()', 'IOReturn RTL88WiFi::restoreAfterSystemWake()'):
        body = extract(a, fn)
        assert body.index('__atomic_exchange_n(&_pmTransition, true') < body.index('waitForDiagnosticsIdle()')
        assert body.index('waitForDiagnosticsIdle()') < min(body.index(x) for x in ('setProperty(', '_pciDev') if x in body)
    start = extract(a, 'bool RTL88WiFi::start(')
    assert 'IOMalloc(32768)' in start and 'addEventSource(_diagnosticsTimer)' in start
    assert start.index('addEventSource(_diagnosticsTimer)') < start.index('setTimeoutMS(1000)')
    results['timer_power_teardown'] = ('source-structure review passed: teardown sets shutdown, disables, cancels, '
        'removes (gate wait), cancels any re-arm, releases, then frees buffer; callback checks shutdown and '
        'publishes hardware access before re-checking PM/DMA flags; sleep and wake set the PM flag then wait '
        'for in-flight diagnostic reads before touching hardware; LPS is compiled off for RTW88_MACOS. '
        'Not executed against IOKit.')


if __name__ == '__main__':
    with tempfile.TemporaryDirectory() as d:
        tmp = Path(d)
        firmware_checks(tmp)
        peer_caps_checks(tmp)
        station_checks(tmp)
        ring_checks(tmp)
    timer_checks()
    out = Path(__file__).with_name('focused-validation-results.json')
    out.write_text(json.dumps(results, indent=2) + '\n')
    print(json.dumps(results, indent=2))
