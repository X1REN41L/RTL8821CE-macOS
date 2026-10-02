"""Exercise the r3 Group Key Handshake (GTK rekey) in the actual candidate code.

Reuses the real crypto, key install, EAPOL builder and handleEAPOL source.
Group message 1 key data is wrapped by macOS CommonCrypto (RFC 3394), an
implementation independent of the driver's unwrap. Hardware, mbufs and timers
are host substitutes; this is not a kernel transport or hardware test.
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
#include <CommonCrypto/CommonSymmetricKeywrap.h>
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
static int installs=0,disables=0;static uint32_t lastCipher=0;
static int hardwareKey(HW*,int action,void*,void*,ieee80211_key_conf*k){if(action){installs++;lastCipher=k->cipher;}else disables++;return 0;}
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
 bool submitOK=true,lastProtect=false;int submissions=0,aggregationStarts=0;
 struct {uint8_t bssid[6]={7,8,9,10,11,12};uint32_t group_cipher=WLAN_CIPHER_SUITE_CCMP;} _targetBSS;
 bool installKey(ieee80211_key_conf**,bool,uint8_t,uint32_t,const uint8_t*,uint8_t);
 void handleEAPOL(const uint8_t*,uint32_t);
 bool sendEAPOLKey(int,const uint8_t*,bool,bool,bool);
 bool txDataFrame(mbuf_t m){captured=*m;delete m;submissions++;lastProtect=_eapolTxProtect;return submitOK;}
 void startTxAggregation(){aggregationStarts++;}
 ~RTW88IEEE80211(){free(_ptkConf);free(_gtkConf);}
};
'''
crypto=s[s.index('typedef struct {'):s.index('/* PCI device-ID')]
wire='\n'.join(fn(x) for x in ('static void rtw88WriteSuite(', 'static uint16_t rtw88BuildSelectedRsnIe(', 'static const char *rtw88CipherName(', 'bool RTW88IEEE80211::installKey(', 'bool RTW88IEEE80211::sendEAPOLKey(', 'void RTW88IEEE80211::handleEAPOL('))
main=r'''
static std::vector<uint8_t> message(RTW88IEEE80211&c,uint16_t ki,uint8_t ctr,const uint8_t*nonce,const std::vector<uint8_t>&kd,bool sign){
 std::vector<uint8_t> p(99+kd.size(),0);uint16_t body=(uint16_t)(95+kd.size());
 p[0]=2;p[1]=3;p[2]=body>>8;p[3]=body;p[4]=2;p[5]=ki>>8;p[6]=ki;p[16]=ctr;if(nonce)memcpy(p.data()+17,nonce,32);
 p[97]=kd.size()>>8;p[98]=kd.size();std::copy(kd.begin(),kd.end(),p.begin()+99);
 if(sign){uint8_t mic[20];kern_hmac_sha1(c._ptk,16,p.data(),p.size(),mic);memcpy(p.data()+81,mic,16);}return p;
}
static std::vector<uint8_t> wrap(const uint8_t*kek,std::vector<uint8_t> raw){
 if(raw.size()<16||raw.size()%8){raw.push_back(0xdd);while(raw.size()<16||raw.size()%8)raw.push_back(0);}
 std::vector<uint8_t> out(raw.size()+8);size_t n=out.size();
 assert(CCSymmetricKeyWrap(kCCWRAPAES,CCrfc3394_iv,CCrfc3394_ivLen,kek,16,raw.data(),raw.size(),out.data(),&n)==0&&n==out.size());return out;
}
static std::vector<uint8_t> gtkKde(uint8_t idx,uint8_t fill,uint8_t len){
 std::vector<uint8_t> k={0xdd,(uint8_t)(6+len),0x00,0x0f,0xac,0x01,idx,0};for(int i=0;i<len;i++)k.push_back(fill);return k;
}
static std::vector<uint8_t> g1(RTW88IEEE80211&c,uint8_t ctr,uint8_t idx,uint8_t fill,uint8_t len=16,uint16_t ki=0x1382){
 return message(c,ki,ctr,nullptr,wrap(c._ptk+16,gtkKde(idx,fill,len)),true);
}
static void checkG2(RTW88IEEE80211&c,uint8_t ctr){
 const uint8_t*e=captured.data()+14;uint8_t zero[32]={};
 assert(captured.size()==14+99);                          // no key data
 assert(e[0]==2&&e[1]==3&&e[4]==2);
 assert(((e[5]<<8)|e[6])==0x0302);                        // v2, group, Secure, MIC
 assert(e[7]==0&&e[8]==0&&e[16]==ctr);                    // key length 0, echoed counter
 assert(memcmp(e+17,zero,32)==0&&e[97]==0&&e[98]==0);     // no nonce, no key data
 assert(eapol_mic_ok(c._ptk,e,(uint32_t)captured.size()-14));
 assert(c.lastProtect&&!c._eapolTxProtect);               // protected under the PTK, flag cleared
}
int main(){
 Ops ops;HW hw{&ops};Timer timer;Parent parent;uint8_t nonce[32];memset(nonce,42,32);
 // Group M1 before any PTK exists is ignored.
 {RTW88IEEE80211 d;d._hw=&hw;d._timer=&timer;d._parent=&parent;auto early=g1(d,1,1,0x11);d.handleEAPOL(early.data(),early.size());assert(d.submissions==0&&installs==0);}
 RTW88IEEE80211 c;c._hw=&hw;c._timer=&timer;c._parent=&parent;
 auto m1=message(c,0x008a,1,nonce,{},false);c.handleEAPOL(m1.data(),m1.size());assert(!c.lastProtect);
 auto m3=message(c,0x13ca,2,nonce,wrap(c._ptk+16,gtkKde(1,0x11,16)),true);
 c.handleEAPOL(m3.data(),m3.size());assert(c._state==5&&installs==2&&c._gtkConf&&c._gtkConf->keyidx==1&&!c.lastProtect);
 c._ccmpTxPn[0]=50;
 // Good rekey to index 2.
 int n=c.submissions,i=installs;auto a=g1(c,3,2,0x22);c.handleEAPOL(a.data(),a.size());
 assert(c.submissions==n+1&&installs==i+1&&c._gtkConf->keyidx==2&&c._gtkConf->key[0]==0x22&&lastCipher==WLAN_CIPHER_SUITE_CCMP);checkG2(c,3);
 assert(c._ptkConf&&c._ccmpTxPn[0]==50&&c._state==5);    // pairwise key untouched
 // Duplicate delivery: reply again, no reinstall.
 n=c.submissions;i=installs;c.handleEAPOL(a.data(),a.size());assert(c.submissions==n+1&&installs==i);checkG2(c,3);
 // Same counter carrying different key material is rejected.
 auto forged=g1(c,3,2,0x33);n=c.submissions;c.handleEAPOL(forged.data(),forged.size());assert(c.submissions==n&&c._gtkConf->key[0]==0x22);
 // AP retransmission with newer counter and same GTK: reply, no reinstall.
 auto retry=g1(c,4,2,0x22);n=c.submissions;i=installs;c.handleEAPOL(retry.data(),retry.size());assert(c.submissions==n+1&&installs==i);checkG2(c,4);
 // Stale counter and bad MIC are dropped.
 auto stale=g1(c,3,1,0x44);n=c.submissions;c.handleEAPOL(stale.data(),stale.size());assert(c.submissions==n&&c._gtkConf->keyidx==2);
 auto bad=g1(c,5,1,0x44);bad[81]^=1;c.handleEAPOL(bad.data(),bad.size());assert(c.submissions==n&&c._gtkConf->keyidx==2);
 // Old pairwise M3 is now stale behind the group replay counter.
 c.handleEAPOL(m3.data(),m3.size());assert(c.submissions==n);
 // Missing Encrypted Key Data flag is not a valid group M1.
 auto plain=g1(c,6,1,0x55,16,0x0382);c.handleEAPOL(plain.data(),plain.size());assert(c.submissions==n);
 // Authentic MIC but key data that fails unwrap, or unwraps to no GTK KDE.
 std::vector<uint8_t> junk(24,0x5a);auto nounwrap=message(c,0x1382,7,nullptr,junk,true);c.handleEAPOL(nounwrap.data(),nounwrap.size());assert(c.submissions==n);
 std::vector<uint8_t> other={0xdd,6,0x00,0x0f,0xac,0x07,0,0};auto nokde=message(c,0x1382,8,nullptr,wrap(c._ptk+16,other),true);c.handleEAPOL(nokde.data(),nokde.size());assert(c.submissions==n);
 auto nodata=message(c,0x1382,9,nullptr,{},true);c.handleEAPOL(nodata.data(),nodata.size());assert(c.submissions==n);
 // Oversized wrapped data with authentic MIC.
 std::vector<uint8_t> huge(272,1);auto big=message(c,0x1382,10,nullptr,huge,true);c.handleEAPOL(big.data(),big.size());assert(c.submissions==n);
 // G2 submission failure is reported; key stays installed; a retry is answered without reinstall.
 auto f=g1(c,11,1,0x66);c.submitOK=false;i=installs;c.handleEAPOL(f.data(),f.size());assert(installs==i+1&&c._gtkConf->keyidx==1&&!c._eapolTxProtect);
 c.submitOK=true;auto f2=g1(c,12,1,0x66);n=c.submissions;c.handleEAPOL(f2.data(),f2.size());assert(installs==i+1&&c.submissions==n+1);checkG2(c,12);
 // WPA2 AES + TKIP mixed mode: group cipher TKIP with a 32-byte GTK.
 c._targetBSS.group_cipher=WLAN_CIPHER_SUITE_TKIP;auto t=g1(c,13,2,0x77,32);i=installs;c.handleEAPOL(t.data(),t.size());
 assert(installs==i+1&&lastCipher==WLAN_CIPHER_SUITE_TKIP&&c._gtkConf->keylen==32&&c._gtkConf->keyidx==2);checkG2(c,13);
 // Group M1 while a pairwise rekey is pending is ignored.
 memset(nonce,43,32);auto rk=message(c,0x008a,14,nonce,{},false);c.handleEAPOL(rk.data(),rk.size());assert(c._state==4&&!c.lastProtect);
 auto during=g1(c,15,1,0x88);n=c.submissions;c.handleEAPOL(during.data(),during.size());assert(c.submissions==n);
 // Truncations and fuzz of a valid group M1 under sanitizers.
 c._state=5;c._handshakePending=false;
 auto v=g1(c,20,1,0x99);for(size_t len=0;len<v.size();len++)c.handleEAPOL(v.data(),len);
 uint32_t seed=7;for(unsigned t2=0;t2<20000;t2++){auto x=v;for(int k=0;k<3;k++){seed=seed*1664525+1013904223;x[(seed>>8)%x.size()]^=(uint8_t)(seed>>24)|1;}
  if(t2&1){uint8_t mic[20];memset(x.data()+81,0,16);kern_hmac_sha1(c._ptk,16,x.data(),x.size(),mic);memcpy(x.data()+81,mic,16);}
  c.handleEAPOL(x.data(),x.size());}
 puts("PASS: group-key handshake: good rekey, duplicate/retry without reinstall, forged/stale/bad-MIC/malformed rejection, protected G2 wire format, submission failure, TKIP group cipher, pending-rekey gating, 20000 mutated inputs");
}
'''
with tempfile.TemporaryDirectory(prefix='rtw88-groupkey-') as td:
    p=Path(td);(p/'test.cpp').write_text(prefix+crypto+wire+main)
    subprocess.run(['xcrun','clang++','-std=c++17','-fsanitize=address,undefined','-fno-sanitize-recover=undefined','-g',str(p/'test.cpp'),'-o',str(p/'test')],check=True)
    subprocess.run([str(p/'test')],check=True)
