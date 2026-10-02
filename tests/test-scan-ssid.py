"""Exercise the actual final scan-cache SSID handling (processScanResult,
rtw88SsidIsBlank, rtw88RestoreSsidIe) against the CoreWLAN hidden check.

CoreWLAN's networkHiddenOrBroadcast() reports "hidden" when the first SSID
element of AP_IE_LIST is missing, empty or starts with a zero byte. Host
substitutes replace sk_buff, IOLock and allocation only. ASan/UBSan check
malformed inputs. This is not a kernel or hardware test.
"""
from pathlib import Path
import re, subprocess, tempfile

root=Path(__file__).resolve().parents[1]/'driver/RTL88WiFi'
s=(root/'src/kext/RTW88IEEE80211.cpp').read_text()
h=(root/'src/kext/RTW88IEEE80211.hpp').read_text()
def fn(signature,src=s):
    start=src.index(signature);i=src.index('{',start)+1;depth=1
    while depth:
        depth+=(src[i]=='{')-(src[i]=='}');i+=1
    return src[start:i]
bss_struct=fn('struct RTW88BSS {',h)+';'
prefix=r'''
#include <cstdint>
#include <cstring>
#include <cstdlib>
#include <cstdio>
#include <cassert>
#include <vector>
#include <string>
static int logs=0;
#define IOLog(...) (logs++, printf(__VA_ARGS__))
#define WLAN_EID_SSID 0
#define WLAN_EID_DS_PARAMS 3
#define WLAN_EID_TIM 5
#define WLAN_EID_RSN 48
#define WLAN_EID_HT_OPERATION 61
#define WLAN_EID_VENDOR_SPECIFIC 221
#define WLAN_CIPHER_SUITE_CCMP 0x000fac04
#define WLAN_CIPHER_SUITE_TKIP 0x000fac02
#define RX_FLAG_NO_SIGNAL_VAL 4
struct ieee80211_hdr{uint16_t frame_control,duration_id;uint8_t addr1[6],addr2[6],addr3[6];uint16_t seq_ctrl;} __attribute__((packed));
struct ieee80211_hdr_3addr{uint16_t frame_control,duration_id;uint8_t addr1[6],addr2[6],addr3[6];uint16_t seq_ctrl;} __attribute__((packed));
struct ieee80211_rx_status{uint32_t flag;int8_t signal;uint16_t freq;};
struct sk_buff{uint8_t*data;uint32_t len;ieee80211_rx_status rx;};
struct IOLock{int held;};
static void IOLockLock(IOLock*l){assert(!l->held);l->held=1;}
static void IOLockUnlock(IOLock*l){assert(l->held);l->held=0;}
static long live=0;
static void*IOMallocZero(size_t n){live++;return calloc(1,n);}
static void IOFree(void*p,size_t){live--;free(p);}
static void kfree_skb(sk_buff*b){if(!b)return;free(b->data);delete b;}
static ieee80211_rx_status*IEEE80211_SKB_RXCB(sk_buff*b){return &b->rx;}
static uint16_t le16_to_cpu(uint16_t v){return v;}
'''+bss_struct+r'''
class RTW88IEEE80211{
public:
 RTW88BSS*_bssList=nullptr;uint32_t _bssCount=0;IOLock lk{0};IOLock*_bssLock=&lk;uint32_t _scanGeneration=1;
 RTW88BSS _targetBSS{};volatile bool _curBssTim=false;
 void processScanResult(sk_buff*);
 RTW88BSS*find(const uint8_t*b){for(RTW88BSS*e=_bssList;e;e=e->next)if(!memcmp(e->bssid,b,6))return e;return nullptr;}
 ~RTW88IEEE80211(){while(_bssList){RTW88BSS*n=_bssList->next;IOFree(_bssList,sizeof(RTW88BSS));_bssList=n;}}
};
'''
main=r'''
static const uint8_t B1[6]={0x08,0x8a,0xf1,0x79,0xc3,0x5a},B2[6]={0x08,0x8a,0xf1,0x79,0xc3,0x5b};
static const uint8_t RSN[]={48,20,1,0,0,0x0f,0xac,4,1,0,0,0x0f,0xac,4,1,0,0,0x0f,0xac,2,0,0};
typedef std::vector<uint8_t> V;
static V ie(uint8_t id,const V&b){V v{id,(uint8_t)b.size()};v.insert(v.end(),b.begin(),b.end());return v;}
static V ssid(const char*n){return ie(0,V(n,n+strlen(n)));}
static V body(const V&ssidIe,bool tim,uint8_t ch=36){V v=ssidIe;auto a=ie(3,{ch});v.insert(v.end(),a.begin(),a.end());
 if(tim){auto t=ie(5,{0,1,0,0});v.insert(v.end(),t.begin(),t.end());}v.insert(v.end(),RSN,RSN+sizeof(RSN));
 auto w=ie(221,{0,0x50,0xf2,2,1,1});v.insert(v.end(),w.begin(),w.end());return v;}
static sk_buff*mgmt(uint16_t stype,const uint8_t*bssid,const V&ies,uint32_t rxflag=0){
 V f(24+12,0);uint16_t fc=stype;memcpy(f.data(),&fc,2);memcpy(f.data()+16,bssid,6);
 f[32]=100;f[34]=0x11;f.insert(f.end(),ies.begin(),ies.end());
 auto*b=new sk_buff;b->len=f.size();b->data=(uint8_t*)malloc(f.size());memcpy(b->data,f.data(),f.size());
 b->rx.flag=rxflag;b->rx.signal=-40;b->rx.freq=5180;return b;}
/* CoreWLAN networkHiddenOrBroadcast verdict on an AP_IE_LIST:
   1 retry (no TIM), 2 broadcast (first SSID == name), 3 hidden. */
static int corewlan(const RTW88BSS*b,const char*name){
 bool tim=false;const uint8_t*ss=nullptr;uint8_t sl=0;
 for(uint32_t i=0;i+2<=b->ies_len;){uint32_t e=2u+b->ies[i+1];if(i+e>b->ies_len)break;
  if(b->ies[i]==5)tim=true;if(b->ies[i]==0&&!ss){ss=b->ies+i+2;sl=b->ies[i+1];}i+=e;}
 if(!tim)return 1;if(!ss)return 3;if(!sl||!ss[0])return 3;
 return (sl==strlen(name)&&!memcmp(ss,name,sl))?2:1;}
static void wellformed(const RTW88BSS*b){uint32_t i=0;while(i+2<=b->ies_len){uint32_t e=2u+b->ies[i+1];assert(i+e<=b->ies_len);i+=e;}
 assert(i==b->ies_len&&b->ies_len<sizeof(b->ies));}
static int countSsid(const RTW88BSS*b){int c=0;for(uint32_t i=0;i+2<=b->ies_len;i+=2u+b->ies[i+1])c+=b->ies[i]==0;return c;}
int main(){
 const uint16_t BEACON=0x80,PRESP=0x50;
 // 1. named beacon -> broadcast; beacon_named set
 {RTW88IEEE80211 c;c.processScanResult(mgmt(BEACON,B1,body(ssid("X1REN_5G"),true)));
  auto*e=c.find(B1);assert(e&&e->beacon_named&&e->ssid_len==8&&corewlan(e,"X1REN_5G")==2&&e->cipher==WLAN_CIPHER_SUITE_CCMP);
 // 2. later all-zero-SSID beacon from the same BSSID -> name restored, still broadcast, one SSID element first
  int l0=logs;c.processScanResult(mgmt(BEACON,B1,body(ie(0,V(8,0)),true)));e=c.find(B1);
  assert(e->ssid_len==8&&!memcmp(e->ssid,"X1REN_5G",8)&&corewlan(e,"X1REN_5G")==2&&countSsid(e)==1&&e->ies[0]==0&&e->ies[1]==8&&logs==l0+1);wellformed(e);
 // 3. empty SSID element and a frame with no SSID element at all -> restored too
  c.processScanResult(mgmt(BEACON,B1,body(V{0,0},true)));e=c.find(B1);assert(corewlan(e,"X1REN_5G")==2&&countSsid(e)==1);wellformed(e);
  {V nb=body(V(),true);c.processScanResult(mgmt(BEACON,B1,nb));e=c.find(B1);assert(corewlan(e,"X1REN_5G")==2&&countSsid(e)==1);wellformed(e);}
 // 4. blank probe response after named beacon -> restored, flag kept
  c.processScanResult(mgmt(PRESP,B1,body(ie(0,V(8,0)),false)));e=c.find(B1);assert(e->beacon_named&&e->ssid_len==8&&countSsid(e)==1&&e->ies[2]=='X');wellformed(e);
 // 5. named beacon again replaces cleanly; renamed AP takes the new name
  c.processScanResult(mgmt(BEACON,B1,body(ssid("RENAMED"),true)));e=c.find(B1);assert(e->ssid_len==7&&corewlan(e,"RENAMED")==2);
  c.processScanResult(mgmt(BEACON,B1,body(ie(0,V(7,0)),true)));e=c.find(B1);assert(corewlan(e,"RENAMED")==2);
  assert(c._bssCount==1);}
 // 6. truly hidden AP: beacons always blank; named probe response does not set beacon_named,
 //    so a later blank beacon is NOT rewritten (hidden behaviour unchanged)
 {RTW88IEEE80211 c;int l0=logs;c.processScanResult(mgmt(BEACON,B2,body(ie(0,V(10,0)),true,2)));auto*e=c.find(B2);
  assert(e&&!e->beacon_named&&e->ssid_len==0&&corewlan(e,"PEACE HOME")==3);
  c.processScanResult(mgmt(PRESP,B2,body(ssid("PEACE HOME"),false,2)));e=c.find(B2);assert(!e->beacon_named&&e->ssid_len==10);
  c.processScanResult(mgmt(BEACON,B2,body(ie(0,V(10,0)),true,2)));e=c.find(B2);
  assert(!e->beacon_named&&e->ssid_len==10&&corewlan(e,"PEACE HOME")==3&&logs==l0);}
 // 7. restore with a full 511-byte IE list: bounded, well formed, SSID first
 {RTW88IEEE80211 c;c.processScanResult(mgmt(BEACON,B1,body(ssid("ABCDEFGHIJKLMNOPQRSTUVWXYZ012345"),true)));
  V big=ie(0,V(32,0));V tim=ie(5,{0,1,0,0});big.insert(big.end(),tim.begin(),tim.end());
  while(big.size()<520){V v=ie(221,V(40,0x33));big.insert(big.end(),v.begin(),v.end());}
  c.processScanResult(mgmt(BEACON,B1,big));auto*e=c.find(B1);wellformed(e);assert(e->ssid_len==32&&e->ies[0]==0&&e->ies[1]==32&&e->ies[2]=='A');}
 // 8. malformed / truncated lists at every length, then fuzz; keep entries well formed
 {RTW88IEEE80211 c;V full=body(ie(0,V(8,0)),true);c.processScanResult(mgmt(BEACON,B1,body(ssid("X1REN_5G"),true)));
  for(size_t n=0;n<=full.size();n++){V p(full.begin(),full.begin()+n);c.processScanResult(mgmt(BEACON,B1,p));
   auto*e=c.find(B1);wellformed(e);assert(e->ssid_len==8&&countSsid(e)==1);}
  for(uint32_t n=0;n<36;n++){auto*b=new sk_buff;b->len=n;b->data=(uint8_t*)malloc(n?n:1);memset(b->data,0,n?n:1);c.processScanResult(b);}
  c.processScanResult(nullptr);
  uint32_t seed=11;for(unsigned t=0;t<20000;t++){V p(t%560);for(auto&x:p){seed=seed*1664525+1013904223;x=seed>>24;}
   if(p.size()>=2&&(seed&3)){p[0]=0;if(seed&4){p[1]=(uint8_t)std::min<size_t>(p[1]%33,p.size()-2);for(uint8_t i=0;i<p[1];i++)p[2+i]=(seed&8)?0:p[2+i];}}
   const uint8_t*bs=(seed&16)?B1:B2;c.processScanResult(mgmt((seed&32)?BEACON:PRESP,bs,p));
   for(RTW88BSS*e=c._bssList;e;e=e->next){wellformed(e);assert(e->ssid_len<=32&&countSsid(e)<=1);if(e->ssid_len){bool z=true;for(int i=0;i<e->ssid_len;i++)z&=!e->ssid[i];assert(!z);}}}
  assert(c._bssCount<=2);}
 // 9 (r10). probe response (no TIM) after a beacon keeps the beacon's TIM -> broadcast at once
 {RTW88IEEE80211 c;memcpy(c._targetBSS.bssid,B1,6);
  c.processScanResult(mgmt(PRESP,B1,body(ssid("X1REN_5G"),false)));auto*e=c.find(B1);
  assert(corewlan(e,"X1REN_5G")==1&&!c._curBssTim);            // probe-only: no TIM yet
  c.processScanResult(mgmt(BEACON,B1,body(ssid("X1REN_5G"),true)));e=c.find(B1);
  assert(corewlan(e,"X1REN_5G")==2&&c._curBssTim);
  c.processScanResult(mgmt(PRESP,B1,body(ssid("X1REN_5G"),false)));e=c.find(B1);
  assert(corewlan(e,"X1REN_5G")==2&&c._curBssTim);wellformed(e);
  int tims=0;for(uint32_t i=0;i+2<=e->ies_len;i+=2u+e->ies[i+1])tims+=e->ies[i]==5;assert(tims==1);
 // 10 (r10). trailing padding (empty vendor + empty SSID elements) is not copied
  V pad=body(ssid("X1REN_5G"),false);V tail{0xDD,0,0,0,0,0,0,0};pad.insert(pad.end(),tail.begin(),tail.end());
  c.processScanResult(mgmt(PRESP,B1,pad));e=c.find(B1);wellformed(e);assert(countSsid(e)==1&&corewlan(e,"X1REN_5G")==2);
  for(uint32_t i=0;i+2<=e->ies_len;i+=2u+e->ies[i+1])assert(!(e->ies[i]==221&&e->ies[i+1]<3));
 // 11 (r10). a non-target BSS does not touch _curBssTim
  c._curBssTim=false;c.processScanResult(mgmt(BEACON,B2,body(ssid("PEACE HOME"),true,2)));assert(!c._curBssTim);}
 // 12 (r10). truly hidden AP stays hidden even with the TIM carried into a named probe response
 {RTW88IEEE80211 c;c.processScanResult(mgmt(BEACON,B2,body(ie(0,V(10,0)),true,2)));
  c.processScanResult(mgmt(PRESP,B2,body(ssid("PEACE HOME"),false,2)));auto*e=c.find(B2);assert(corewlan(e,"PEACE HOME")!=2);
  c.processScanResult(mgmt(PRESP,B2,body(ie(0,V(10,0)),false,2)));e=c.find(B2);assert(corewlan(e,"PEACE HOME")!=2);}
 assert(live==0);
 puts("PASS: r10 TIM carried into probe responses, padding not copied, _curBssTim tracking, hidden AP still hidden; named beacon broadcast, blank/empty/missing SSID restored after a named beacon (beacon and probe response), rename, truly hidden AP unchanged, 512-byte cap, truncation at every length, 20,000 fuzz frames, no leaks");
}
'''
with tempfile.TemporaryDirectory(prefix='rtw88-scanssid-') as td:
    p=Path(td)
    src=prefix+fn('static uint32_t rtw88ReadSuite(')+'\n'+fn('static bool rtw88RsnSelectCcmpPsk(')+'\n'+fn('static bool rtw88SsidIsBlank(')+'\n'+fn('static int rtw88IeFind(')+'\n'+fn('static void rtw88RestoreSsidIe(')+'\n'+fn('void RTW88IEEE80211::processScanResult(')+main
    (p/'test.cpp').write_text(src)
    subprocess.run(['xcrun','clang++','-std=c++17','-fsanitize=address,undefined','-fno-sanitize-recover=all','-g',str(p/'test.cpp'),'-o',str(p/'test')],check=True)
    r=subprocess.run([str(p/'test')],capture_output=True,text=True)
    print('\n'.join(l for l in r.stdout.splitlines() if l.startswith('PASS')))
    if r.returncode: print(r.stdout[-2000:],r.stderr[-3000:]); raise SystemExit(r.returncode)
