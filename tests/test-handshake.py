"""Exercise actual candidate crypto, serialization, key install and MLME code.

Host substitutes replace hardware/mbuf/timers only. ASan/UBSan check malformed
inputs. This is not a kernel transport or hardware test.
"""
from pathlib import Path
import subprocess, tempfile

root=Path(__file__).resolve().parents[1]/'driver/RTL88WiFi'
s=(root/'src/kext/RTW88IEEE80211.cpp').read_text()
def fn(signature):
    start=s.index(signature);i=s.index('{',start)+1;depth=1
    while depth:
        depth+=(s[i]=='{')-(s[i]=='}');i+=1
    return s[start:i]
prefix=r'''
#include <cstdint>
#include <cstddef>
#include <cstring>
#include <cstdlib>
#include <cstdio>
#include <cassert>
#include <vector>
#include <algorithm>
#define IOLog(...) ((void)0)
#define WLAN_CIPHER_SUITE_CCMP 0x000fac04
#define WLAN_CIPHER_SUITE_TKIP 0x000fac02
#define WLAN_EID_RSN 48
#define IEEE80211_KEY_FLAG_PAIRWISE 1
#define kMillisecondScale 1
#define kIONetworkLinkActive 1
#define kIONetworkLinkValid 2
#define SET_KEY 1
#define DISABLE_KEY 0
#define RTW88_STATE_HANDSHAKING 4
#define RTW88_STATE_CONNECTED 5
using s8=int8_t;
static void *IOMalloc(size_t n){return malloc(n);}
static void *IOMallocZero(size_t n){return calloc(1,n);}
static void IOFree(void*p,size_t){free(p);}
static int randomCalls=0;
static void read_random(void*p,size_t n){memset(p,++randomCalls,n);}
static void clock_interval_to_deadline(unsigned,unsigned,uint64_t*p){*p=1;}
using mbuf_t=std::vector<uint8_t>*;
static std::vector<uint8_t> captured;
static mbuf_t rtw88_make_packet_mbuf(const void*p,uint32_t n){auto b=(const uint8_t*)p;return new std::vector<uint8_t>(b,b+n);}
struct ieee80211_key_conf{uint32_t cipher;int8_t keyidx;uint32_t flags;uint8_t keylen,iv_len,icv_len,hw_key_idx;uint8_t key[32];};
struct HW;
static int installs=0,disables=0;
static int hardwareKey(HW*,int action,void*,void*,ieee80211_key_conf*){if(action)installs++;else disables++;return 0;}
struct Ops{decltype(&hardwareKey) set_key=hardwareKey;};
struct HW{Ops*ops;};
struct Timer{void wakeAtTime(uint64_t){} void cancelTimeout(){}};
struct Parent{void setLinkStatus(unsigned){}};
class RTW88IEEE80211{
public:
 HW*_hw;void*_vif=nullptr,*_sta=nullptr;Timer*_timer;Parent*_parent;
 uint8_t _pmk[32]={1},_ptk[64]={},_gtk[32]={},_anonce[32]={},_snonce[32]={},_replayCtr[8]={},_installedM3ReplayCtr[8]={},_ccmpTxPn[6]={},_macAddr[6]={1,2,3,4,5,6};
 ieee80211_key_conf *_ptkConf=nullptr,*_gtkConf=nullptr;
 bool _snonceValid=false,_m3KeysInstalled=false,_handshakePending=false,_associatedVisible=false,_eapolTxProtect=false;
 unsigned _state=RTW88_STATE_HANDSHAKING;
 bool submitOK=true;int submissions=0,aggregationStarts=0;
 struct {uint8_t bssid[6]={7,8,9,10,11,12};uint32_t group_cipher=WLAN_CIPHER_SUITE_CCMP;} _targetBSS;
 bool installKey(ieee80211_key_conf**,bool,uint8_t,uint32_t,const uint8_t*,uint8_t);
 void handleEAPOL(const uint8_t*,uint32_t);
 bool sendEAPOLKey(int,const uint8_t*,bool,bool,bool);
 bool txDataFrame(mbuf_t m){captured=*m;delete m;submissions++;return submitOK;}
 void startTxAggregation(){aggregationStarts++;}
 ~RTW88IEEE80211(){free(_ptkConf);free(_gtkConf);}
};
'''
# Real crypto implementation, including MIC verification and GTK parsing.
crypto=s[s.index('typedef struct {'):s.index('/* PCI device-ID')]
wire='\n'.join(fn(x) for x in ('static void rtw88WriteSuite(', 'static uint16_t rtw88BuildSelectedRsnIe(', 'static const char *rtw88CipherName(', 'bool RTW88IEEE80211::installKey(', 'bool RTW88IEEE80211::sendEAPOLKey(', 'void RTW88IEEE80211::handleEAPOL('))
main=r'''
static std::vector<uint8_t> message(RTW88IEEE80211&c,uint16_t ki,uint8_t ctr,const uint8_t*nonce,bool sign){
 std::vector<uint8_t> p(99,0);p[0]=2;p[1]=3;p[3]=95;p[4]=2;p[5]=ki>>8;p[6]=ki;p[16]=ctr;memcpy(p.data()+17,nonce,32);
 if(sign){uint8_t mic[20];kern_hmac_sha1(c._ptk,16,p.data(),p.size(),mic);memcpy(p.data()+81,mic,16);}return p;
}
static void checkWire(RTW88IEEE80211&c,int step){
 const uint8_t*e=captured.data()+14;assert(e[7]==0&&e[8]==0);
 if(step==2)assert(memcmp(e+17,c._snonce,32)==0);else{uint8_t zero[32]={};assert(memcmp(e+17,zero,32)==0);}
 assert(eapol_mic_ok(c._ptk,e,(uint32_t)captured.size()-14));
}
int main(){
 // Independent known-answer HMAC-SHA1 (RFC 2202 test case 1).
 uint8_t key[20],digest[20];memset(key,0x0b,20);
 const uint8_t expected[]={0xb6,0x17,0x31,0x86,0x55,0x05,0x72,0x64,0xe2,0x8b,0xc0,0xb6,0xfb,0x37,0x8c,0x8e,0xf1,0x46,0xbe,0x00};
 kern_hmac_sha1(key,20,(const uint8_t*)"Hi There",8,digest);assert(memcmp(digest,expected,20)==0);
 // RFC 3394 AES unwrap known-answer vector.
 const uint8_t kek[]={0,1,2,3,4,5,6,7,8,9,10,11,12,13,14,15};
 const uint8_t wrapped[]={0x1f,0xa6,0x8b,0x0a,0x81,0x12,0xb4,0x47,0xae,0xf3,0x4b,0xd8,0xfb,0x5a,0x7b,0x82,0x9d,0x3e,0x86,0x23,0x71,0xd2,0xcf,0xe5};
 const uint8_t plain[]={0,0x11,0x22,0x33,0x44,0x55,0x66,0x77,0x88,0x99,0xaa,0xbb,0xcc,0xdd,0xee,0xff};
 uint8_t out[256];uint16_t outlen=0;assert(aes_unwrap_128(kek,wrapped,24,out,&outlen));assert(outlen==16&&memcmp(out,plain,16)==0);
 Ops ops;HW hw{&ops};Timer timer;Parent parent;RTW88IEEE80211 c;c._hw=&hw;c._timer=&timer;c._parent=&parent;
 uint8_t nonce[32];memset(nonce,42,32);
 auto m1=message(c,0x008a,1,nonce,false);c.handleEAPOL(m1.data(),m1.size());checkWire(c,2);
 uint8_t snonce[32],ptk[64];memcpy(snonce,c._snonce,32);memcpy(ptk,c._ptk,64);
 c.handleEAPOL(m1.data(),m1.size());assert(randomCalls==1&&memcmp(snonce,c._snonce,32)==0&&memcmp(ptk,c._ptk,64)==0);checkWire(c,2);
 auto m3=message(c,0x03ca,2,nonce,true);c.handleEAPOL(m3.data(),m3.size());assert(installs==1&&c._state==5);checkWire(c,4);
 c._ccmpTxPn[0]=77;
 c.handleEAPOL(m3.data(),m3.size());assert(installs==1&&c._ccmpTxPn[0]==77&&c.aggregationStarts==1);checkWire(c,4);
 auto newer=message(c,0x03ca,3,nonce,true);c.handleEAPOL(newer.data(),newer.size());assert(installs==1&&c._ccmpTxPn[0]==77);checkWire(c,4);
 int n=c.submissions;c.handleEAPOL(m3.data(),m3.size());assert(c.submissions==n); // stale replay
 newer[81]^=1;c.handleEAPOL(newer.data(),newer.size());assert(c.submissions==n); // bad MIC
 c.handleEAPOL(m1.data(),m1.size());assert(c.submissions==n); // stale M1
 // M4 submission failure retains installed-key identity; retry must not reset PN.
 memset(nonce,43,32);auto fresh=message(c,0x008a,4,nonce,false);c.handleEAPOL(fresh.data(),fresh.size());assert(randomCalls==2);
 auto freshM3=message(c,0x03ca,5,nonce,true);c.submitOK=false;c.handleEAPOL(freshM3.data(),freshM3.size());assert(installs==2&&c._state==4);
 c._ccmpTxPn[0]=88;c.submitOK=true;c.handleEAPOL(freshM3.data(),freshM3.size());assert(installs==2&&c._ccmpTxPn[0]==88&&c._state==5);
 // Wrapped GTK too large for output buffer, with an authentic MIC.
 auto huge=message(c,0x13ca,6,nonce,false);huge.resize(99+272);huge[2]=1;huge[3]=111;huge[97]=1;huge[98]=16;
 uint8_t mic[20];kern_hmac_sha1(c._ptk,16,huge.data(),huge.size(),mic);memcpy(huge.data()+81,mic,16);
 n=c.submissions;c.handleEAPOL(huge.data(),huge.size());assert(c.submissions==n);
 // Malformed/truncated EAPOL and replay flags, under sanitizers.
 for(size_t len=0;len<freshM3.size();len++)c.handleEAPOL(freshM3.data(),len);
 uint32_t seed=1;uint8_t fuzz[400];for(unsigned t=0;t<10000;t++){for(auto&x:fuzz){seed=seed*1664525+1013904223;x=seed>>24;}c.handleEAPOL(fuzz,t%400);}
 c.handleEAPOL(nullptr,0);
 puts("PASS: HMAC/AES vectors; actual M1/M3 retries, replay/MIC rejection, PN preservation, submission failure, serialization and malformed inputs");
}
'''
with tempfile.TemporaryDirectory(prefix='rtw88-handshake-') as td:
    p=Path(td);(p/'test.cpp').write_text(prefix+crypto+wire+main)
    subprocess.run(['xcrun','clang++','-std=c++17','-fsanitize=address,undefined','-g',str(p/'test.cpp'),'-o',str(p/'test')],check=True)
    subprocess.run([str(p/'test')],check=True)
