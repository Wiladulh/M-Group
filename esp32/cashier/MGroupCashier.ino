#include <Arduino.h>
#include <WiFi.h>
#include <HTTPClient.h>
#include <Preferences.h>
#include <Wire.h>
#include <Adafruit_GFX.h>
#include <Adafruit_SSD1306.h>
#include "MGroupKeypad.h"
#include "MGroupCardReader.h"

const char* WIFI_SSID="CHANGE_ME";
const char* WIFI_PASSWORD="CHANGE_ME";
// Replace with the server LAN IP; default API port is 8011. Do not add a trailing slash.
const char* M_GROUP_BASE_URL="http://192.168.1.24:8011";
const char* DEVICE_ID="cashier-01";
const char* M_GROUP_DEVICE_KEY="CHANGE_DEVICE_KEY";
static constexpr int OLED_WIDTH=128, OLED_HEIGHT=64;
static constexpr uint8_t OLED_I2C_ADDRESS=0x3C;
Adafruit_SSD1306 display(OLED_WIDTH,OLED_HEIGHT,&Wire,-1);

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
  HTTPClient http; http.setConnectTimeout(3000); http.setTimeout(5000); http.begin(String(M_GROUP_BASE_URL)+path);
  http.addHeader("X-M-Group-Device-Key",M_GROUP_DEVICE_KEY); code=http.GET();
  String out=code>0?http.getString():""; http.end(); return out;
}

String jsonField(const String& body,const String& key){
  String needle="\"" + key + "\":\""; int p=body.indexOf(needle);
  if(p<0)return ""; p+=needle.length(); int e=body.indexOf("\"",p);
  return e<0?"":body.substring(p,e);
}

String postJson(const String& path,const String& body,int& code){
  HTTPClient http; http.setConnectTimeout(3000); http.setTimeout(8000); http.begin(String(M_GROUP_BASE_URL)+path);
  http.addHeader("Content-Type","application/json");
  http.addHeader("X-M-Group-Device-Key",M_GROUP_DEVICE_KEY); code=http.POST(body);
  String out=code>0?http.getString():""; http.end(); return out;
}

void heartbeat(){
  if(WiFi.status()!=WL_CONNECTED){Serial.println("HEARTBEAT skipped: WiFi offline");return;}
  int code=0;
  String body="{\"device_type\":\"esp32-cashier\",\"status\":\"active\"}";
  String reply=postJson(String("/api/v1/devices/")+DEVICE_ID+"/heartbeat",body,code);
  Serial.printf("HEARTBEAT %d %s\n",code,reply.c_str());
}

bool connectWifi(unsigned long timeoutMs=10000){
  if(WiFi.status()==WL_CONNECTED)return true;
  WiFi.mode(WIFI_STA); WiFi.setAutoReconnect(true); WiFi.begin(WIFI_SSID,WIFI_PASSWORD);
  Serial.print("WiFi reconnect");
  unsigned long started=millis();
  while(WiFi.status()!=WL_CONNECTED && millis()-started<timeoutMs){delay(250);Serial.print(".");}
  if(WiFi.status()==WL_CONNECTED){
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

// Registration API accepts a conventional colon-separated UID, while payment
// endpoints use the server credential identifier (nfc- followed by hex UID).
String uidToCardUid(const uint8_t* uid,uint8_t len){
  String out="";
  for(uint8_t i=0;i<len;i++){
    if(i)out+=":";
    if(uid[i]<16)out+="0";
    String byteText=String(uid[i],HEX); byteText.toUpperCase(); out+=byteText;
  }
  return out;
}

void cashierPayment(const String& credential,long amount,const String& seq,const String& pin){
  if(amount<=0){Serial.println("ERR nominal must be positive");lcdShow("GAGAL","Nominal invalid");delay(1200);return;}
  lcdShow("Memproses bayar","Mohon tunggu");
  Serial.printf("PAYMENT START credential=%s amount=%ld seq=%s\\n",credential.c_str(),amount,seq.c_str());
  // Persist transaction identity before network I/O. Never persist the PIN.
  savePendingPayment(credential,amount,seq);
  String body="{\"device_id\":\""+String(DEVICE_ID)+"\",\"credential_id\":\""+credential+
              "\",\"amount\":"+String(amount)+
              ",\"method\":\"NFC\",\"provider\":\"local\",\"idempotency_key\":\""+
              String(DEVICE_ID)+":"+seq+"\",\"pin\":\""+pin+"\"}";
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
                  (String(DEVICE_ID)+":"+seq).c_str());
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
              "\",\"idempotency_key\":\""+String(DEVICE_ID)+":deposit:"+seq+"\"}";
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

void registrationScan(const String& session){
  lcdShow("REGISTRASI NFC","Silahkan scan");
  uint8_t uid[M_GROUP_MAX_UID_LENGTH]={0},len=0;
  while(!card.readUID(uid,len)){ delay(20); }
  String credential=uidToCredential(uid,len);
  lcdShow("Kartu diterima","PIN 4 digit:");
  String pin=readKeyDigits("PIN 4 digit:",true,4,4);
  String body="{\"session_id\":\""+session+"\",\"card_uid\":\""+uidToCardUid(uid,len)+"\",\"pin\":\""+pin+"\"}";
  int code=0; String reply=postJson(String("/api/v1/cashier/")+DEVICE_ID+"/nfc-registration/complete",body,code);
  Serial.printf("NFC REG %d %s\n",code,reply.c_str());
  if(code==200) lcdShow("REGISTRASI","BERHASIL");
  else lcdShow("REGISTRASI","GAGAL");
  delay(1800);
}

void pollRegistration(){
  int code=0; String reply=getJson(String("/api/v1/cashier/")+DEVICE_ID+"/nfc-registration",code);
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
  lcdShow("Pembayaran","Tap kartu NFC");
  unsigned long scanStarted=millis();
  while(!card.readUID(uid,len) && millis()-scanStarted<20000UL){delay(20);}
  if(len==0){lcdShow("WAKTU HABIS","Ulangi transaksi");delay(1500);return;}
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
  // Keep the existing UI helper name so the transaction flow stays unchanged.
  // The physical display is a 128x64 I2C OLED (SSD1306, address 0x3C).
  display.clearDisplay();
  display.setTextColor(SSD1306_WHITE);
  display.setTextSize(1);
  display.setTextWrap(false);
  display.setCursor(0,0); display.print(a.substring(0,21));
  display.setCursor(0,18); display.print(b.substring(0,21));
  display.display();
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
  Wire.begin(PN532_SDA,PN532_SCL);
  if(!display.begin(SSD1306_SWITCHCAPVCC,OLED_I2C_ADDRESS)){
    Serial.println("FATAL: SSD1306 OLED init failed; check I2C wiring/address/controller");
    while(true) delay(1000);
  }
  display.clearDisplay(); display.setTextColor(SSD1306_WHITE); display.display();
  connectWifi(); heartbeat();
  readerReady=card.begin(PN532_SDA,PN532_SCL);
  if(!readerReady){
    Serial.println("ERROR: no supported NFC reader detected");
    lcdShow("NFC ERROR","Cek koneksi");
  }else{
    Serial.printf("NFC READY reader=%s\\n",card.name());
    if(pendingPayment) lcdShow("PAYMENT PENDING","Masukkan PIN");
    else lcdShow("KASIR M-Group","1 Bayar 2 Topup");
  }
}

void loop(){
  if(WiFi.status()!=WL_CONNECTED)connectWifi(3000);
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
    if(k=='1'||k=='2')mode=k;
    delay(5);
  }
  if(mode=='1'){
    lcdShow("Pembayaran","Nominal:");
    paymentAmount=readCashierAmount();
    if(paymentAmount>0)scanCard();
    paymentAmount=0;
  }else{
    lcdShow("Topup","PIN Operator:");
    String operatorPin=readKeyDigits("PIN Operator:",true,4,6);
    lcdShow("Topup","Nominal:");
    scanTopup(operatorPin);
  }
  lcdShow("KASIR M-Group","1 Bayar 2 Topup");
}
