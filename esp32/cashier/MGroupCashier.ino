#include <Arduino.h>
#include <WiFi.h>
#include <time.h>
#include <HTTPClient.h>
#include <WiFiClientSecure.h>
#include <Preferences.h>
#include <Wire.h>
#include <LiquidCrystal_I2C.h>
#include "MGroupConfigPortal.h"
#include "MGroupKeypad.h"
#include "MGroupCardReader.h"

String WIFI_SSID="";
String WIFI_PASSWORD="";
String M_GROUP_BASE_URL="http://192.168.1.10:8011";
String HARDWARE_ID="";
String DEVICE_LOCATION="";
bool deviceRegistered=false;
String M_GROUP_DEVICE_KEY="";
MGroupConfigPortal configPortal;
LiquidCrystal_I2C lcd(0x27,16,2);

#define PN532_SDA 21
#define PN532_SCL 22
#define PN532_IRQ 39
#define PN532_RESET 5
#define RC522_SCK 18
#define RC522_MISO 19
#define RC522_MOSI 23
#define RC522_SS 27
#define RC522_RST 4

M_GROUPCardReader card(PN532_IRQ,PN532_RESET,RC522_SCK,RC522_MISO,RC522_MOSI,RC522_SS,RC522_RST);
unsigned long lastHeartbeat=0,paymentSequence=0,depositSequence=0;
bool readerReady=false;
long paymentAmount=0;
Preferences cashierPrefs;
bool pendingPayment=false,pendingDeposit=false;
String pendingCredential="",pendingSeq="";
long pendingAmount=0;
String pendingDepositCredential="",pendingDepositSeq="";
long pendingDepositAmount=0;
void savePendingPayment(const String& credential,long amount,const String& seq){
  cashierPrefs.putBool("pay_pending",true); cashierPrefs.putString("pay_cred",credential);
  cashierPrefs.putLong("pay_amount",amount); cashierPrefs.putString("pay_seq",seq);
  pendingPayment=true; pendingCredential=credential; pendingAmount=amount; pendingSeq=seq;
}
void clearPendingPayment(){
  cashierPrefs.putBool("pay_pending",false); cashierPrefs.remove("pay_cred");
  cashierPrefs.remove("pay_amount"); cashierPrefs.remove("pay_seq");
  pendingPayment=false; pendingCredential=""; pendingAmount=0; pendingSeq="";
}
void savePendingDeposit(const String& credential,long amount,const String& seq){
  cashierPrefs.putBool("dep_pending",true); cashierPrefs.putString("dep_cred",credential);
  cashierPrefs.putLong("dep_amount",amount); cashierPrefs.putString("dep_seq",seq);
  pendingDeposit=true; pendingDepositCredential=credential; pendingDepositAmount=amount; pendingDepositSeq=seq;
}
void clearPendingDeposit(){
  cashierPrefs.putBool("dep_pending",false); cashierPrefs.remove("dep_cred");
  cashierPrefs.remove("dep_amount"); cashierPrefs.remove("dep_seq");
  pendingDeposit=false; pendingDepositCredential=""; pendingDepositAmount=0; pendingDepositSeq="";
}

void lcdShow(String a,String b="");
String readKeyDigits(const char* title,bool masked,uint8_t minDigits,uint8_t maxDigits);
long readCashierAmount();
void cashierPayment(const String& credential,long amount,const String& seq,const String& pin);
void cashierTopup(const String& credential,long amount,const String& seq,const String& operatorPin,const String& memberPin);
void scanTopup(const String& operatorPin);
void registrationScan(const String& session);
void scanCard();

String getJson(const String& path,int& code){
  HTTPClient http; WiFiClientSecure secureClient; http.setConnectTimeout(3000); http.setTimeout(5000);String url=String(M_GROUP_BASE_URL)+path;
  if(M_GROUP_BASE_URL.startsWith("https://")){String ca=configPortal.tlsCaCertificate();if(ca.isEmpty()){code=-2;Serial.println("HTTPS rejected: configure trusted server CA in local WebUI");return "";}secureClient.setCACert(ca.c_str());if(!http.begin(secureClient,url)){code=-2;return "";}}
  else if(!http.begin(url)){code=-2;return "";}
  http.addHeader("X-M-Group-Device-Key",M_GROUP_DEVICE_KEY); code=http.GET();
  String out=code>0?http.getString():""; http.end(); return out;
}

String jsonField(const String& body,const String& key){
  String needle="\"" + key + "\":\""; int p=body.indexOf(needle);
  if(p<0)return ""; p+=needle.length(); int e=body.indexOf("\"",p);
  return e<0?"":body.substring(p,e);
}

String postJson(const String& path,const String& body,int& code){
  HTTPClient http; WiFiClientSecure secureClient; http.setConnectTimeout(3000); http.setTimeout(8000);String url=String(M_GROUP_BASE_URL)+path;
  if(M_GROUP_BASE_URL.startsWith("https://")){String ca=configPortal.tlsCaCertificate();if(ca.isEmpty()){code=-2;Serial.println("HTTPS rejected: configure trusted server CA in local WebUI");return "";}secureClient.setCACert(ca.c_str());if(!http.begin(secureClient,url)){code=-2;return "";}}
  else if(!http.begin(url)){code=-2;return "";}
  http.addHeader("Content-Type","application/json");
  http.addHeader("X-M-Group-Device-Key",M_GROUP_DEVICE_KEY); code=http.POST(body);
  String out=code>0?http.getString():""; http.end(); return out;
}

bool registerDevice(){
  if(WiFi.status()!=WL_CONNECTED)return false;
  String mac=WiFi.macAddress();
  if(HARDWARE_ID.isEmpty()){Serial.println("Server-issued logical Device ID missing; configure Device ID and Device Key in WebUI");return false;}
  String body="{\"device_type\":\"esp32-cashier\",\"device_id\":\""+HARDWARE_ID+"\",\"hardware_id\":\""+mac+"\",\"mac_address\":\""+mac+"\",\"device_key\":\""+M_GROUP_DEVICE_KEY+"\"}";
  int code=0; String reply=postJson("/api/v1/devices/register",body,code);
  Serial.printf("DEVICE REGISTER %d %s\\n",code,reply.c_str());
  deviceRegistered=code>=200&&code<300;
  return deviceRegistered;
}

void heartbeat(){
  if(!deviceRegistered){Serial.println("HEARTBEAT skipped: device not registered");return;}
  if(WiFi.status()!=WL_CONNECTED){Serial.println("HEARTBEAT skipped: WiFi offline");return;}
  int code=0;
  String body="{\"device_type\":\"esp32-cashier\",\"status\":\"active\",\"display_name\":\""+configPortal.jsonEscape(DEVICE_LOCATION)+"\"}";
  String reply=postJson(String("/api/v1/devices/heartbeat"),body,code);
  Serial.printf("HEARTBEAT %d %s\n",code,reply.c_str());
  if(code<200||code>=300)deviceRegistered=false;
}

bool connectWifi(unsigned long timeoutMs=10000){
  if(WiFi.status()==WL_CONNECTED)return true;
  WiFi.mode(configPortal.active()?WIFI_AP_STA:WIFI_STA); WiFi.setAutoReconnect(true); WiFi.begin(WIFI_SSID,WIFI_PASSWORD);
  Serial.print("WiFi reconnect");
  unsigned long started=millis();
  while(WiFi.status()!=WL_CONNECTED && millis()-started<timeoutMs){delay(250);Serial.print(".");}
  if(WiFi.status()==WL_CONNECTED){
    configTime(7*3600,0,"pool.ntp.org","time.google.com","time.cloudflare.com");
    Serial.printf("\nIP %s\n",WiFi.localIP().toString().c_str());
    return true;
  }
  Serial.println("\nWiFi unavailable; will retry");
  return false;
}

String uidToCredential(const uint8_t* uid,uint8_t len){
  String out="nfc-";
  for(uint8_t i=0;i<len;i++){if(uid[i]<16)out+="0";out+=String(uid[i],HEX);}
  out.toLowerCase(); return out;
}

void cashierPayment(const String& credential,long amount,const String& seq,const String& pin){
  if(amount<=0){Serial.println("ERR nominal must be positive");lcdShow("GAGAL","Nominal invalid");delay(1200);return;}
  lcdShow("Memproses bayar","Mohon tunggu");
  Serial.printf("PAYMENT START credential=%s amount=%ld seq=%s\\n",credential.c_str(),amount,seq.c_str());
  // Persist transaction identity before network I/O. Never persist the PIN.
  savePendingPayment(credential,amount,seq);
  String body="{\"credential_id\":\""+credential+
              "\",\"amount\":"+String(amount)+
              ",\"method\":\"NFC\",\"provider\":\"local\",\"idempotency_key\":\""+
              String(HARDWARE_ID)+":"+seq+"\",\"pin\":\""+pin+"\"}";
  int code=0; String reply="";
  for(int attempt=1;attempt<=2;attempt++){
    if(WiFi.status()!=WL_CONNECTED && !connectWifi(5000)){code=-1;delay(250);continue;}
    reply=postJson("/api/v1/cashier/payments",body,code);
    Serial.printf("PAYMENT attempt=%d code=%d %s\\n",attempt,code,reply.c_str());
    // Transport errors and server 5xx are ambiguous: retry the same key/body.
    if(code>0 && code<500) break;
    delay(250);
  }
  if(code<=0 || code>=500){
    lcdShow("HASIL BELUM ADA","Ulangi PIN");
    Serial.printf("PAYMENT PENDING key=%s; same transaction must be retried\\n",
                  (String(HARDWARE_ID)+":"+seq).c_str());
    return; // NVS pending record blocks new payments until reconciled.
  }
  clearPendingPayment();
  if(code==200){
    int p=reply.indexOf("\"balance_after\":");
    long bal=p>=0?reply.substring(p+16).toInt():0;
    lcdShow("SUKSES","Terpotong Rp."+String(amount)); delay(1200);
    lcdShow("Saldo sisa","Rp."+String(bal)); delay(2200);
  }else if(code==403 && reply.indexOf("invalid_pin")>=0){
    lcdShow("GAGAL","PIN salah"); delay(1800);
  }else if(code==401 || code==403){
    lcdShow("GAGAL","Device/akses"); delay(1800);
  }else if(code==409){
    lcdShow("GAGAL",reply.indexOf("insufficient_balance")>=0?"Saldo tidak cukup":"Transaksi ditolak"); delay(1800);
  }else if(code==404){
    lcdShow("GAGAL","Device/API"); delay(1800);
  }else if(code==422){
    lcdShow("GAGAL","Data invalid"); delay(1800);
  }else if(code==429){
    lcdShow("GAGAL","Terlalu cepat"); delay(1800);
  }else{
    lcdShow("GAGAL","HTTP "+String(code)); delay(1800);
  }
}

void cashierTopup(const String& credential,long amount,const String& seq,const String& operatorPin,const String& memberPin){
  if(amount<=0){lcdShow("GAGAL","Nominal invalid");delay(1500);return;}
  savePendingDeposit(credential,amount,seq);
  String body="{\"credential_id\":\""+credential+"\",\"amount\":"+String(amount)+
              ",\"operator_pin\":\""+operatorPin+"\",\"member_pin\":\""+memberPin+
              "\",\"idempotency_key\":\""+String(HARDWARE_ID)+":deposit:"+seq+"\"}";
  int code=0; String reply="";
  for(int attempt=1;attempt<=2;attempt++){
    if(WiFi.status()!=WL_CONNECTED && !connectWifi(5000)){code=-1;continue;}
    reply=postJson("/api/v1/cashier/deposits",body,code);
    Serial.printf("TOPUP attempt=%d code=%d %s\n",attempt,code,reply.c_str());
    if(code>0 && code<500)break;
    delay(250);
  }
  if(code<=0 || code>=500){lcdShow("HASIL BELUM ADA","Ulangi Topup");return;}
  clearPendingDeposit();
  if(code>=200 && code<300){lcdShow("Topup Success","Rp."+String(amount));delay(1800);}
  else if(reply.indexOf("invalid_pin")>=0 || reply.indexOf("invalid_operator_pin")>=0){lcdShow("Topup Gagal","PIN salah");delay(1800);}
  else {lcdShow("Topup Gagal","HTTP "+String(code));delay(1800);}
}

void scanTopup(const String& operatorPin){
  long amount=readCashierAmount();
  if(amount<=0)return;
  lcdShow("Topup","Tap kartu");
  uint8_t uid[M_GROUP_MAX_UID_LENGTH]={0},len=0;
  while(!card.readUID(uid,len)){ delay(20); }
  String credential=uidToCredential(uid,len);
  lcdShow("Kartu diterima","PIN:");
  String memberPin=readKeyDigits("PIN:",true,4,6);
  ++depositSequence; cashierPrefs.putULong("dep_seq_counter",depositSequence);
  cashierTopup(credential,amount,String(depositSequence),operatorPin,memberPin);
  delay(700);
}

long jsonNumber(const String& body,const String& key){
  String needle="\"" + key + "\":";
  int p=body.indexOf(needle);
  if(p<0)return -1;
  p+=needle.length();
  while(p<(int)body.length() && body[p]==' ')p++;
  int e=p;
  if(e<(int)body.length() && body[e]=='-')e++;
  while(e<(int)body.length() && body[e]>='0' && body[e]<='9')e++;
  return e==p?-1:body.substring(p,e).toInt();
}

void checkMemberBalance(){
  if(!readerReady){lcdShow("NFC ERROR","Cek reader");delay(1500);return;}
  lcdShow("Cek saldo","Tap kartu NFC");
  uint8_t uid[M_GROUP_MAX_UID_LENGTH]={0},len=0;
  unsigned long started=millis();
  while(!card.readUID(uid,len)){
    if(millis()-started>30000UL){lcdShow("Cek saldo","Waktu habis");delay(1500);return;}
    delay(20);
  }
  String credential=uidToCredential(uid,len);
  String cardUid=credential.substring(4);
  String body="{\"card_uid\":\""+cardUid+"\"}";
  int code=0;
  String reply=postJson("/api/v1/devices/member-balance",body,code);
  Serial.printf("MEMBER BALANCE %d %s\\n",code,reply.c_str());
  if(code==200){
    long balance=jsonNumber(reply,"balance");
    String member=jsonField(reply,"member_name");
    lcdShow(member.length()?member:"Saldo Member","Rp."+String(balance<0?0:balance));
    delay(3500);
  }else if(code==401 || code==403){
    lcdShow("Cek saldo gagal","Device/akses");
    delay(1800);
  }else if(code==404){
    lcdShow("Kartu tidak","terdaftar/aktif");
    delay(1800);
  }else if(code==429){
    lcdShow("Tunggu sebentar","Coba lagi");
    delay(1500);
  }else{
    lcdShow("Cek saldo gagal","HTTP "+String(code));
    delay(1800);
  }
}

void registrationProgress(const String& session,const String& status){
  configPortal.setStatusExtra(",\"registration_status\":\""+status+"\"");
  String body="{\"session_id\":\""+session+"\",\"status\":\""+status+"\"}";
  int code=0;String reply=postJson("/api/v1/cashier/nfc-registration/progress",body,code);
  Serial.printf("NFC PROGRESS %s %d\\n",status.c_str(),code);
}
void registrationScan(const String& session){
  registrationProgress(session,"waiting_nfc");
  lcdShow("REGISTRASI NFC","Silahkan scan");
  uint8_t uid[M_GROUP_MAX_UID_LENGTH]={0},len=0;
  while(!card.readUID(uid,len)){ delay(20); }
  String credential=uidToCredential(uid,len);
  registrationProgress(session,"pin_pending");
  lcdShow("Kartu diterima","PIN 4 digit:");
  String pin=readKeyDigits("PIN 4 digit:",true,4,4);
  registrationProgress(session,"processing");
  String body="{\"session_id\":\""+session+"\",\"card_uid\":\""+credential.substring(4)+"\",\"pin\":\""+pin+"\"}";
  int code=0; String reply=postJson(String("/api/v1/cashier/nfc-registration/complete"),body,code);
  Serial.printf("NFC REG %d %s\\n",code,reply.c_str());
  if(code==200){configPortal.setStatusExtra(",\"registration_status\":\"completed\"");lcdShow("REGISTRASI","BERHASIL");}
  else {registrationProgress(session,"failed");lcdShow("REGISTRASI","GAGAL");}
  delay(1800);
}

void pollRegistration(){
  int code=0; String reply=getJson(String("/api/v1/cashier/nfc-registration"),code);
  if(code!=200)return;
  String status=jsonField(reply,"status");
  if(status=="scan_pending"){
    String session=jsonField(reply,"session_id");
    if(session.length()) registrationScan(session);
  }
}

void scanCard(){
  if(!readerReady){lcdShow("NFC ERROR","Cek reader");delay(1500);return;}
  if(paymentAmount<=0)return;
  uint8_t uid[M_GROUP_MAX_UID_LENGTH]={0},len=0;
  if(!card.readUID(uid,len))return;
  lcdShow("Kartu terbaca","Memeriksa...");
  String credential=uidToCredential(uid,len); ++paymentSequence;
  cashierPrefs.putULong("pay_seq_counter",paymentSequence);
  lcdShow("Kartu diterima","Masukkan PIN");
  Serial.printf("CARD READ reader=%s credential=%s\\n",card.name(),credential.c_str());
  String pin=readKeyDigits("PIN (#=OK):",true,4,6);
  Serial.printf("CARD %s -> %s amount=%ld\n",card.name(),credential.c_str(),paymentAmount);
  cashierPayment(credential,paymentAmount,String(paymentSequence),pin);
  delay(700);
}

void lcdShow(String a,String b){
  lcd.setCursor(0,0); lcd.print("                ");
  lcd.setCursor(0,0); lcd.print(a.substring(0,16));
  lcd.setCursor(0,1); lcd.print("                ");
  lcd.setCursor(0,1); lcd.print(b.substring(0,16));
}

String readKeyDigits(const char* title,bool masked,uint8_t minDigits,uint8_t maxDigits){
  String s="";
  auto renderInput=[&](){
    String v="";
    for(size_t i=0;i<s.length();++i) v+=masked?"*":String(s[i]);
    lcdShow(title,v);
  };
  renderInput();
  Serial.printf("INPUT START %s (digits; *=backspace; #=confirm)\\n",title);
  while(true){
    char k=M_GROUPKeypad.getKey();
    if(k>='0'&&k<='9'&&s.length()<maxDigits){
      s+=k; renderInput();
    }else if(k=='*'&&!s.isEmpty()){
      s.remove(s.length()-1); renderInput();
    }else if(k=='#'&&s.length()>=minDigits){
      Serial.printf("INPUT CONFIRMED %s length=%u\\n",title,(unsigned)s.length());
      return s;
    }
    delay(5);
  }
}

long readCashierAmount(){
  return readKeyDigits("Nominal:",false,1,6).toInt();
}

void setup(){
  Serial.begin(115200); delay(300);
  cashierPrefs.begin("M_GROUP-cashier",false);
  bool forceConfigPortal=false; const unsigned long configCheckStarted=millis();
  while(millis()-configCheckStarted<900UL){char setupKey=M_GROUPKeypad.getKey();if(setupKey==68)forceConfigPortal=true;delay(5);}
  configPortal.begin(WIFI_SSID,WIFI_PASSWORD,M_GROUP_BASE_URL,HARDWARE_ID,M_GROUP_DEVICE_KEY,"Cashier M-Group","mgroup-cashier",forceConfigPortal,&DEVICE_LOCATION);
  paymentSequence=cashierPrefs.getULong("pay_seq_counter",0);
  depositSequence=cashierPrefs.getULong("dep_seq_counter",0);
  pendingPayment=cashierPrefs.getBool("pay_pending",false);
  pendingDeposit=cashierPrefs.getBool("dep_pending",false);
  if(pendingDeposit){
    pendingDepositCredential=cashierPrefs.getString("dep_cred","");
    pendingDepositAmount=cashierPrefs.getLong("dep_amount",0);
    pendingDepositSeq=cashierPrefs.getString("dep_seq","");
    if(!pendingDepositCredential.length() || pendingDepositAmount<=0 || !pendingDepositSeq.length()){
      Serial.println("FATAL: pending deposit metadata invalid; inspect device before new deposits");
      while(true) delay(1000);
    }
  }
  if(pendingPayment){
    pendingCredential=cashierPrefs.getString("pay_cred","");
    pendingAmount=cashierPrefs.getLong("pay_amount",0);
    pendingSeq=cashierPrefs.getString("pay_seq","");
    if(!pendingCredential.length() || pendingAmount<=0 || !pendingSeq.length()){
      Serial.println("FATAL: pending payment metadata invalid; inspect device before new payments");
      while(true) delay(1000);
    }
  }
  lcd.init(); lcd.backlight();
  connectWifi();
  if(registerDevice())heartbeat();
  else lcdShow("REGISTRATION WAIT","Cek server/key");
  readerReady=card.begin(PN532_SDA,PN532_SCL);
  if(!readerReady){
    Serial.println("ERROR: no supported NFC reader detected");
    lcdShow("NFC ERROR","Cek koneksi");
  }else{
    Serial.printf("NFC READY reader=%s\\n",card.name());
    if(pendingPayment) lcdShow("PAYMENT PENDING","Masukkan PIN");
    else lcdShow("KASIR M-Group","1 Bayar 2 Topup 3 Saldo");
  }
}

void loop(){
  if(WiFi.status()!=WL_CONNECTED)connectWifi(3000);
  static unsigned long lastRegistrationAttempt=0;
  if(WiFi.status()==WL_CONNECTED && !deviceRegistered && millis()-lastRegistrationAttempt>=10000UL){
    lastRegistrationAttempt=millis();
    if(registerDevice())heartbeat();
    else {lcdShow("REGISTRATION WAIT","Cek server/key");delay(250);return;}
  }
  if(!deviceRegistered){delay(100);return;}
  // Resolve an ambiguous payment before permitting another transaction.
  // The PIN is re-entered and is never persisted in NVS.
  if(pendingPayment){
    lcdShow("PAYMENT PENDING","PIN utk ulangi");
    String pin=readKeyDigits("PIN utk ulangi",true,4,6);
    cashierPayment(pendingCredential,pendingAmount,pendingSeq,pin);
    return;
  }
  if(pendingDeposit){
    lcdShow("TOPUP PENDING","Ulangi PIN");
    String operatorPin=readKeyDigits("PIN Operator:",true,4,6);
    String memberPin=readKeyDigits("PIN Anggota:",true,4,6);
    cashierTopup(pendingDepositCredential,pendingDepositAmount,pendingDepositSeq,operatorPin,memberPin);
    return;
  }
  static unsigned long lastRegistrationPoll=0;
  if(WiFi.status()==WL_CONNECTED && millis()-lastRegistrationPoll>=1000UL){lastRegistrationPoll=millis();pollRegistration();}
  if(millis()-lastHeartbeat>=30000UL){lastHeartbeat=millis();heartbeat();}
  char mode=0;
  while(!mode){
    char k=M_GROUPKeypad.getKey();
    if(k=='1'||k=='2'||k=='3')mode=k;
    delay(5);
  }
  if(mode=='1'){
    lcdShow("Pembayaran","Nominal:");
    paymentAmount=readCashierAmount();
    if(paymentAmount>0)scanCard();
    paymentAmount=0;
  }else if(mode=='2'){
    lcdShow("Topup","PIN Operator:");
    String operatorPin=readKeyDigits("PIN Operator:",true,4,6);
    lcdShow("Topup","Nominal:");
    scanTopup(operatorPin);
  }else{
    checkMemberBalance();
  }
  lcdShow("KASIR M-Group","1 Bayar 2 Topup 3 Saldo");
}
