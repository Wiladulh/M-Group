#include <Arduino.h>
#include <Wire.h>
#include <SPI.h>
#include <Keypad.h>
#include <MFRC522.h>
#include <Adafruit_GFX.h>
#include <Adafruit_SSD1306.h>
#include <ArduinoJson.h>
#include "MGroupV2Runtime.h"

namespace {
constexpr uint8_t RFID_SS=27, RFID_RST=4;
constexpr uint8_t OLED_SDA=21, OLED_SCL=22, OLED_ADDRESS=0x3C;
constexpr int8_t OLED_RESET=-1;
constexpr byte ROWS=4,COLS=4;
char keyMap[ROWS][COLS]={{'1','2','3','A'},{'4','5','6','B'},{'7','8','9','C'},{'*','0','#','D'}};
byte rowPins[ROWS]={32,33,25,26};
byte colPins[COLS]={13,14,16,17};
Keypad keypad=Keypad(makeKeymap(keyMap),rowPins,colPins,ROWS,COLS);
Adafruit_SSD1306 display(128,64,&Wire,OLED_RESET);
MFRC522 rfid(RFID_SS,RFID_RST);
bool oledReady=false,rc522Ready=false;
enum Mode { HOME, AMOUNT_PAYMENT, AMOUNT_TOPUP, WAIT_CARD_PAYMENT, ENTER_PIN_PAYMENT,
            ENTER_OPERATOR_PIN, WAIT_CARD_TOPUP, ENTER_PIN_TOPUP, NFC_WAIT_CARD, NFC_ENTER_PIN };
Mode mode=HOME;
String inputDigits,pinDigits,operatorPin,pendingCardUid,pendingOp,pendingRequestId,nfcSessionId;
long pendingAmount=0;
unsigned long lastNfcPoll=0;
String lastCardUid;
bool cardReadThisLoop=false;

void lines(const String& a,const String& b="") {
  if(!oledReady){Serial.printf("[DISPLAY] %s | %s\\n",a.c_str(),b.c_str());return;}
  display.clearDisplay();display.setTextColor(SSD1306_WHITE);display.setTextSize(1);
  display.setCursor(0,0);display.println(a.substring(0,21));
  display.setCursor(0,16);display.println(b.substring(0,21));display.display();
}
void inputLine(const String& value) {
  if(!oledReady)return;
  display.fillRect(0,16,128,10,SSD1306_BLACK);display.setCursor(0,16);
  display.print(value.substring(0,21));display.display();
}
String masked(const String& s){String out;for(size_t i=0;i<s.length();i++)out+='*';return out;}
void clearPending() {
  Preferences& p=mgroup.prefs();
  p.remove("pending_op");p.remove("pending_req");p.remove("pending_amount");
  pendingOp="";pendingRequestId="";pendingAmount=0;
}
void persistPending(const String& op,long amount) {
  pendingOp=op;pendingAmount=amount;pendingRequestId=mgroup.nextRequestId(op=="topup"?"cashier-topup":"cashier-payment");
  Preferences& p=mgroup.prefs();p.putString("pending_op",pendingOp);p.putString("pending_req",pendingRequestId);p.putLong("pending_amount",pendingAmount);
}
String responseCode(const String& body) {
  JsonDocument doc;if(deserializeJson(doc,body)==DeserializationError::Ok) {
    if(doc["detail"]["code"].is<const char*>())return doc["detail"]["code"].as<String>();
    if(doc["code"].is<const char*>())return doc["code"].as<String>();
  }
  return "";
}
bool refreshMemberBalance(const String& cardUid,long& balance) {
  if(cardUid.isEmpty()||!mgroup.wifiConnected())return false;
  JsonDocument lookup;lookup["card_uid"]=cardUid;
  String body;serializeJson(lookup,body);
  String response;int status=-1;
  if(!mgroup.apiPost("/api/v2/devices/member-balance",body,response,status))return false;
  JsonDocument result;
  if(deserializeJson(result,response)!=DeserializationError::Ok||!result["balance_minor"].is<long>())return false;
  balance=result["balance_minor"].as<long>();
  return true;
}

void finishRequest(const String& path,const String& body) {
  String response;int status=-1;bool ok=mgroup.apiPost(path,body,response,status);
  pinDigits="";operatorPin="";
  if(ok) {
    JsonDocument doc;deserializeJson(doc,response);
    String tx=doc["transaction_id"]|String("");
    String state=doc["status"]|String("succeeded");
    // Always attempt a fresh server read after a committed payment/top-up.
    // A failed read never changes the already-confirmed transaction result.
    long latestBalance=-1;
    bool balanceFresh=refreshMemberBalance(pendingCardUid,latestBalance);
    clearPending();mode=HOME;pendingCardUid="";
    lines(state=="succeeded"?"TRANSAKSI OK":"TRANSAKSI",tx.length()?tx.substring(0,16):state);
    delay(1000);
    if(balanceFresh)lines("SALDO TERBARU","Rp "+String(latestBalance));
    else lines("TRANSAKSI OK","Saldo sync pending");
    delay(1400);lines("A=Bayar B=Topup","Tempel kartu saat diminta");
    return;
  }
  String code=responseCode(response);
  if(status>=400&&status<500&&code!="IDEMPOTENCY_CONFLICT") {
    clearPending();mode=HOME;pendingCardUid="";
    lines("DITOLAK",code.length()?code.substring(0,16):"Periksa input");
    delay(1600);lines("A=Bayar B=Topup","Tempel kartu saat diminta");
  } else {
    // Keep the exact request ID and amount. Raw card UID/PIN are deliberately
    // not persisted; retry requires the member to tap again and re-enter PIN.
    mode=pendingOp=="topup"?ENTER_OPERATOR_PIN:WAIT_CARD_PAYMENT;
    pendingCardUid="";
    lines(pendingOp=="topup"?"TOPUP TERTUNDA":"HASIL BELUM ADA",pendingOp=="topup"?"Masukkan PIN op":"Tap ulang; PIN ulang");
  }
}
String cardUid() {
  if(!rc522Ready)return "";
  if(!rfid.PICC_IsNewCardPresent()||!rfid.PICC_ReadCardSerial()){lastCardUid="";return "";}
  String value;
  for(uint8_t i=0;i<rfid.uid.size;i++){char b[3];snprintf(b,sizeof(b),"%02X",rfid.uid.uidByte[i]);value+=b;}
  rfid.PICC_HaltA();rfid.PCD_StopCrypto1();
  if(value==lastCardUid)return "";
  lastCardUid=value;
  return value;
}
