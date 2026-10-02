"""Exercise the actual r9 RX data-frame filter (deliverDataFrame, deAmsdu).

Host substitutes replace sk_buff, mbuf delivery and the EAPOL handler only.
ASan/UBSan check malformed inputs. This is not a kernel or hardware test.
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
#include <cstring>
#include <cstdlib>
#include <cstdio>
#include <cassert>
#include <vector>
static int logs=0;
#define IOLog(...) (logs++, printf(__VA_ARGS__))
#define WLAN_CIPHER_SUITE_CCMP 0x000fac04
#define WLAN_CIPHER_SUITE_TKIP 0x000fac02
#define RX_FLAG_DECRYPTED 1
#define ETH_P_PAE 0x888e
#define ETH_P_IP 0x0800
#define RTW88_STATE_HANDSHAKING 4
#define RTW88_STATE_CONNECTED 5
#define RTW88_STATE_SCANNING 3
struct ieee80211_hdr{uint16_t frame_control,duration_id;uint8_t addr1[6],addr2[6],addr3[6];uint16_t seq_ctrl;} __attribute__((packed));
struct ieee80211_rx_status{uint32_t flag;};
struct sk_buff{uint8_t*data;uint32_t len;ieee80211_rx_status rx;};
static int frees=0;
static void kfree_skb(sk_buff*b){frees++;free(b->data);delete b;}
static void skb_trim(sk_buff*b,uint32_t n){if(b->len>n)b->len=n;}
static ieee80211_rx_status*IEEE80211_SKB_RXCB(sk_buff*b){return &b->rx;}
static uint16_t le16_to_cpu(uint16_t v){return v;}
static bool ieee80211_has_protected(uint16_t fc){return fc&0x4000;}
static bool ieee80211_is_data_qos(uint16_t fc){return (fc&0x00fc)==0x0088;}
static uint16_t ieee80211_get_hdrlen_from_skb(sk_buff*b){
 if(b->len<2)return 24;uint16_t fc;memcpy(&fc,b->data,2);return ieee80211_is_data_qos(fc)?26:24;}
static bool is_multicast_ether_addr(const uint8_t*a){return a[0]&1;}
struct Delivered{uint16_t type;std::vector<uint8_t> payload;};
static std::vector<Delivered> out;static std::vector<uint32_t> eapol;
class RTW88IEEE80211{
public:
 bool _m3KeysInstalled=false,_externalPTKInstalled=false,_externalSupplicant=false,_rxCcmpIvSkipLogged=false;
 uint32_t _rxUndecryptedProtected=0,_rxUnprotectedDropped=0,_rxNonSnapDropped=0,_rxAmsduSpoofDropped=0,_rxTrailerChecks=0;
 unsigned _state=RTW88_STATE_CONNECTED,_scanReturnState=0;
 struct{uint32_t cipher=WLAN_CIPHER_SUITE_CCMP,group_cipher=WLAN_CIPHER_SUITE_CCMP;}_targetBSS;
 void deliverDataFrame(sk_buff*);void deAmsdu(const uint8_t*,uint32_t);
 void deliverEthernet(const uint8_t*,const uint8_t*,uint16_t t,const uint8_t*p,uint32_t n){out.push_back({t,std::vector<uint8_t>(p,p+n)});}
 void handleEAPOL(const uint8_t*,uint32_t n){eapol.push_back(n);}
};
'''
main=r'''
static const uint8_t SNAP[6]={0xAA,0xAA,0x03,0,0,0};
static std::vector<uint8_t> ipv4(uint16_t total){std::vector<uint8_t> p(total,0x5a);p[0]=0x45;p[2]=total>>8;p[3]=total&0xff;return p;}
static sk_buff*frame(bool prot,bool dec,bool qos,bool amsdu,bool mcast,const std::vector<uint8_t>&body,uint32_t trailer){
 std::vector<uint8_t> f(qos?26:24,0);uint16_t fc=0x0208|(qos?0x80:0)|(prot?0x4000:0);memcpy(f.data(),&fc,2);
 f[4]=mcast?0x01:0x02;if(qos)f[24]=amsdu?0x80:0;
 if(prot){uint8_t iv[8]={1,0,0,0x20,0,0,0,0};f.insert(f.end(),iv,iv+8);}
 f.insert(f.end(),body.begin(),body.end());f.insert(f.end(),trailer,0xee);
 auto*b=new sk_buff;b->len=f.size();b->data=(uint8_t*)malloc(f.size()?f.size():1);memcpy(b->data,f.data(),f.size());b->rx.flag=dec?RX_FLAG_DECRYPTED:0;return b;}
static std::vector<uint8_t> msdu(uint16_t type,const std::vector<uint8_t>&p){std::vector<uint8_t> v(SNAP,SNAP+6);v.push_back(type>>8);v.push_back(type&0xff);v.insert(v.end(),p.begin(),p.end());return v;}
static std::vector<uint8_t> sub(const std::vector<uint8_t>&m,uint8_t da0,bool pad){std::vector<uint8_t> v(12,0);v[0]=da0;v.push_back(m.size()>>8);v.push_back(m.size()&0xff);v.insert(v.end(),m.begin(),m.end());while(pad&&v.size()%4)v.push_back(0);return v;}
int main(){
 RTW88IEEE80211 c;c._m3KeysInstalled=true;
 // 1. CCMP unicast: MIC trimmed, payload exact, trailer check extra=0
 out.clear();c.deliverDataFrame(frame(true,true,true,false,false,msdu(ETH_P_IP,ipv4(100)),8));
 assert(out.size()==1&&out[0].type==ETH_P_IP&&out[0].payload.size()==100&&c._rxTrailerChecks==1);
 // 2. non-QoS CCMP too
 out.clear();c.deliverDataFrame(frame(true,true,false,false,false,msdu(ETH_P_IP,ipv4(60)),8));assert(out.size()==1&&out[0].payload.size()==60);
 // 3. TKIP group cipher on multicast: 12-byte trailer
 c._targetBSS.group_cipher=WLAN_CIPHER_SUITE_TKIP;out.clear();
 c.deliverDataFrame(frame(true,true,true,false,true,msdu(ETH_P_IP,ipv4(80)),12));assert(out.size()==1&&out[0].payload.size()==80);
 // unicast still CCMP (8) with TKIP group
 out.clear();c.deliverDataFrame(frame(true,true,true,false,false,msdu(ETH_P_IP,ipv4(80)),8));assert(out.size()==1&&out[0].payload.size()==80);
 c._targetBSS.group_cipher=WLAN_CIPHER_SUITE_CCMP;
 // 4. protected but not HW-decrypted: dropped
 out.clear();c.deliverDataFrame(frame(true,false,true,false,false,msdu(ETH_P_IP,ipv4(100)),8));assert(out.empty()&&c._rxUndecryptedProtected==1);
 // 5. plaintext IPv4 on keyed link: dropped; plaintext EAPOL: handled
 c.deliverDataFrame(frame(false,false,true,false,false,msdu(ETH_P_IP,ipv4(100)),0));assert(out.empty()&&c._rxUnprotectedDropped==1);
 eapol.clear();c.deliverDataFrame(frame(false,false,true,false,false,msdu(ETH_P_PAE,std::vector<uint8_t>(99,1)),0));assert(out.empty()&&eapol.size()==1&&eapol[0]==99);
 // protected EAPOL (group rekey M1) after MIC trim keeps exact length
 eapol.clear();c.deliverDataFrame(frame(true,true,true,false,false,msdu(ETH_P_PAE,std::vector<uint8_t>(155,1)),8));assert(eapol.size()==1&&eapol[0]==155);
 // external-supplicant PTK also counts as keyed
 {RTW88IEEE80211 e;e._externalPTKInstalled=true;e._externalSupplicant=true;out.clear();e.deliverDataFrame(frame(false,false,true,false,false,msdu(ETH_P_IP,ipv4(40)),0));assert(out.empty());}
 // 6. open network (not keyed): plaintext delivered unchanged
 {RTW88IEEE80211 o;out.clear();o.deliverDataFrame(frame(false,false,true,false,false,msdu(ETH_P_IP,ipv4(100)),0));assert(out.size()==1&&out[0].payload.size()==100);
  out.clear();o.deliverDataFrame(frame(false,false,true,true,false,sub(msdu(ETH_P_IP,ipv4(40)),2,false),0));assert(out.size()==1);}
 // 7. non-SNAP payload: dropped (was EtherType 0)
 out.clear();{std::vector<uint8_t> b(64,0x11);c.deliverDataFrame(frame(true,true,true,false,false,b,8));}assert(out.empty()&&c._rxNonSnapDropped==1);
 // 8. protected A-MSDU, two subframes, MIC trimmed
 {auto a=sub(msdu(ETH_P_IP,ipv4(50)),2,true);auto b=sub(msdu(ETH_P_IP,ipv4(70)),2,false);a.insert(a.end(),b.begin(),b.end());
  out.clear();c.deliverDataFrame(frame(true,true,true,true,false,a,8));assert(out.size()==2&&out[0].payload.size()==50&&out[1].payload.size()==70);}
 // 9. A-MSDU whose first DA is an LLC/SNAP header: dropped
 {std::vector<uint8_t> a=msdu(ETH_P_IP,ipv4(60));out.clear();c.deliverDataFrame(frame(true,true,true,true,false,a,8));assert(out.empty()&&c._rxAmsduSpoofDropped==1);}
 // 10. plaintext A-MSDU on keyed link: dropped
 out.clear();c.deliverDataFrame(frame(false,false,true,true,false,sub(msdu(ETH_P_IP,ipv4(40)),2,false),0));assert(out.empty()&&c._rxUnprotectedDropped==2);
 // 11. short and truncated frames at every length, then random fuzz
 {auto full=frame(true,true,true,false,false,msdu(ETH_P_IP,ipv4(60)),8);std::vector<uint8_t> raw(full->data,full->data+full->len);kfree_skb(full);
  for(uint32_t n=0;n<raw.size();n++){auto*b=new sk_buff;b->len=n;b->data=(uint8_t*)malloc(n?n:1);memcpy(b->data,raw.data(),n);b->rx.flag=RX_FLAG_DECRYPTED;c.deliverDataFrame(b);}}
 uint32_t seed=7;for(unsigned t=0;t<20000;t++){uint32_t n=t%300;auto*b=new sk_buff;b->len=n;b->data=(uint8_t*)malloc(n?n:1);
  for(uint32_t i=0;i<n;i++){seed=seed*1664525+1013904223;b->data[i]=seed>>24;}if(n>=2){b->data[0]=(b->data[0]&0x0f)|0x08;}b->rx.flag=seed&1;c._m3KeysInstalled=(seed>>1)&1;c.deliverDataFrame(b);}
 puts("PASS: MIC/ICV trailer trim (CCMP 8, TKIP group 12), undecrypted drop, plaintext-on-keyed drop with EAPOL exception, open-network delivery, non-SNAP drop, A-MSDU trim and first-DA check, truncation and 20,000 fuzz frames");
}
'''
with tempfile.TemporaryDirectory(prefix='rtw88-rxfilter-') as td:
    p=Path(td);(p/'test.cpp').write_text(prefix+fn('void RTW88IEEE80211::deliverDataFrame(')+'\n'+fn('void RTW88IEEE80211::deAmsdu(')+main)
    subprocess.run(['xcrun','clang++','-std=c++17','-fsanitize=address,undefined','-fno-sanitize-recover=all','-g',str(p/'test.cpp'),'-o',str(p/'test')],check=True)
    r=subprocess.run([str(p/'test')],capture_output=True,text=True)
    print('\n'.join(l for l in r.stdout.splitlines() if l.startswith('PASS') or 'trailer check' in l))
    if r.returncode: print(r.stdout[-2000:],r.stderr[-3000:]); raise SystemExit(r.returncode)
