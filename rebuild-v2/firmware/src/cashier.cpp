#include <Arduino.h>
#include <Wire.h>
#include <SPI.h>
#include <Keypad.h>
#include <LiquidCrystal_I2C.h>
#include <MFRC522.h>
#include <Adafruit_PN532.h>
#include <ArduinoJson.h>
#include "MGroupV2Runtime.h"

namespace {
constexpr uint8_t RFID_SS=27, RFID_RST=4;
constexpr uint8_t PN532_IRQ=39, PN532_RESET=5;
constexpr byte ROWS=4,COLS=4;
char keyMap[ROWS][COLS]={{'1','2','3','A'},{'4','5','6','B'},{'7','8','9','C'},{'*','0','#','D'}};
byte rowPins[ROWS]={32,33,25,26};
byte colPins[COLS]={13,14,16,17};
Keypad keypad=Keypad(makeKeymap(keyMap),rowPins,colPins,ROWS,COLS);
LiquidCrystal_I2C lcd(0x27,16,2);
MFRC522 rfid(RFID_SS,RFID_RST);
Adafruit_PN532 pn532(PN532_IRQ,PN532_RESET);
bool pn532Ready=false,rc522Ready=false;
enum Mode { HOME, AMOUNT_PAYMENT, AMOUNT_TOPUP, WAIT_CARD_PAYMENT, ENTER_PIN_PAYMENT,
            ENTER_OPERATOR_PIN, WAIT_CARD_TOPUP, ENTER_PIN_TOPUP, NFC_WAIT_CARD, NFC_ENTER_PIN };
Mode mode=HOME;
String inputDigits,pinDigits,operatorPin,pendingCardUid,pendingOp,pendingRequestId,nfcSessionId;
long pendingAmount=0;
unsigned long lastNfcPoll=0;
String lastCardUid;
bool cardReadThisLoop=false;

void lines(const String& a,const String& b="") {
  lcd.clear();lcd.setCursor(0,0);lcd.print(a.substring(0,16));lcd.setCursor(0,1);lcd.print(b.substring(0,16));
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
void finishRequest(const String& path,const String& body) {
  String response;int status=-1;bool ok=mgroup.apiPost(path,body,response,status);
  pinDigits="";operatorPin="";
  if(ok) {
    JsonDocument doc;deserializeJson(doc,response);
    String tx=doc["transaction_id"]|String("");
    String state=doc["status"]|String("succeeded");
    clearPending();mode=HOME;pendingCardUid="";
    lines(state=="succeeded"?"TRANSAKSI OK":"TRANSAKSI",tx.length()?tx.substring(0,16):state);
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
    mode=pendingOp=="topup"?WAIT_CARD_TOPUP:WAIT_CARD_PAYMENT;
    pendingCardUid="";
    lines("HASIL BELUM ADA","Tap ulang; PIN ulang");
  }
}
String cardUid() {
  uint8_t uid[10];uint8_t length=0;String value;
  if(pn532Ready) {
    if(!pn532.readPassiveTargetID(PN532_MIFARE_ISO14443A,uid,&length,30)){lastCardUid="";return "";}
  } else if(rc522Ready) {
    if(!rfid.PICC_IsNewCardPresent()||!rfid.PICC_ReadCardSerial()){lastCardUid="";return "";}
    length=rfid.uid.size;for(uint8_t i=0;i<length;i++)uid[i]=rfid.uid.uidByte[i];
    rfid.PICC_HaltA();rfid.PCD_StopCrypto1();
  } else return "";
  for(uint8_t i=0;i<length;i++){char b[3];snprintf(b,sizeof(b),"%02X",uid[i]);value+=b;}
  if(value==lastCardUid)return "";
  lastCardUid=value;
  return value;
}
void pollNfcSession() {
  if(mode!=HOME||millis()-lastNfcPoll<1800)return;
  lastNfcPoll=millis();
  String response;int status=0;
  if(!mgroup.apiGet("/api/v2/cashier/nfc-registration",response,status))return;
  JsonDocument doc;if(deserializeJson(doc,response)!=DeserializationError::Ok)return;
  String state=doc["status"]|String("idle");
  if(state=="scan_pending"||state=="waiting_nfc") {
    String id=doc["session_id"]|String("");
    if(id.isEmpty())return;
    nfcSessionId=id;
    if(state=="scan_pending") {
      JsonDocument progress;progress["session_id"]=nfcSessionId;progress["status"]="waiting_nfc";
      String body;serializeJson(progress,body);String reply;int code;
      mgroup.apiPost("/api/v2/cashier/nfc-registration/progress",body,reply,code);
    }
    mode=NFC_WAIT_CARD;lines("REGISTRASI NFC","Tempel kartu baru");
  } else if(state=="pin_pending"||state=="processing") {
    // UID is never stored across reboot. Fail closed rather than complete with
    // an unknown card identity or ask the server to bind a different card.
    String id=doc["session_id"]|String("");
    if(!id.isEmpty()) {
      JsonDocument progress;progress["session_id"]=id;progress["status"]="failed";
      String body;serializeJson(progress,body);String reply;int code;
      mgroup.apiPost("/api/v2/cashier/nfc-registration/progress",body,reply,code);
    }
  }
}
void submitPayment() {
  if(pinDigits.length()<6){lines("PIN MINIMAL 6","Masukkan PIN #");return;}
  JsonDocument body;body["request_id"]=pendingRequestId;body["card_uid"]=pendingCardUid;
  body["pin"]=pinDigits;body["amount_minor"]=pendingAmount;
  String json;serializeJson(body,json);
  finishRequest("/api/v2/cashier/payments",json);
}
void submitTopup() {
  if(pinDigits.length()<6||operatorPin.length()<6){lines("PIN TIDAK VALID","Coba kembali");return;}
  JsonDocument body;body["request_id"]=pendingRequestId;body["card_uid"]=pendingCardUid;
  body["operator_pin"]=operatorPin;body["member_pin"]=pinDigits;body["amount_minor"]=pendingAmount;
  String json;serializeJson(body,json);
  finishRequest("/api/v2/cashier/top-ups",json);
}
void submitNfcRegistration() {
  if(pinDigits.length()<6){lines("PIN MINIMAL 6","Masukkan PIN #");return;}
  JsonDocument progress;progress["session_id"]=nfcSessionId;progress["status"]="processing";
  String body;serializeJson(progress,body);String reply;int code;
  if(!mgroup.apiPost("/api/v2/cashier/nfc-registration/progress",body,reply,code)) {
    lines("SERVER OFFLINE","Ulangi sebentar");return;
  }
  JsonDocument payload;payload["session_id"]=nfcSessionId;payload["card_uid"]=pendingCardUid;payload["pin"]=pinDigits;
  String json;serializeJson(payload,json);
  bool ok=mgroup.apiPost("/api/v2/cashier/nfc-registration/complete",json,reply,code);
  pinDigits="";pendingCardUid="";
  if(ok){lines("NFC BERHASIL","Kartu terdaftar");nfcSessionId="";mode=HOME;delay(1600);lines("A=Bayar B=Topup","Terminal siap");}
  else {lines("REGISTRASI GAGAL",responseCode(reply).substring(0,16));mode=HOME;nfcSessionId="";delay(1500);lines("A=Bayar B=Topup","Terminal siap");}
}
void restorePending() {
  Preferences& p=mgroup.prefs();pendingOp=p.getString("pending_op","");pendingRequestId=p.getString("pending_req","");pendingAmount=p.getLong("pending_amount",0);
  if((pendingOp=="payment"||pendingOp=="topup")&&!pendingRequestId.isEmpty()&&pendingAmount>0) {
    mode=pendingOp=="topup"?ENTER_OPERATOR_PIN:WAIT_CARD_PAYMENT;
    if(pendingOp=="topup")lines("TOPUP TERTUNDA","Masukkan PIN op");
    else lines("PAYMENT TERTUNDA","Tap kartu lagi");
  } else {clearPending();mode=HOME;lines("A=Bayar B=Topup","Terminal siap");}
}
void handleKey(char key) {
  if(!key)return;
  if(key=='D'&&mode!=WAIT_CARD_PAYMENT&&mode!=WAIT_CARD_TOPUP&&mode!=NFC_WAIT_CARD&&mode!=NFC_ENTER_PIN&&mode!=ENTER_PIN_PAYMENT&&mode!=ENTER_PIN_TOPUP) {
    if(mode==AMOUNT_PAYMENT||mode==AMOUNT_TOPUP){inputDigits="";mode=HOME;lines("A=Bayar B=Topup","Terminal siap");}return;
  }
  if(mode==HOME) {
    if(key=='A'){inputDigits="";mode=AMOUNT_PAYMENT;lines("NOMINAL BAYAR","Angka, # OK");}
    else if(key=='B'){inputDigits="";mode=AMOUNT_TOPUP;lines("NOMINAL TOPUP","Angka, # OK");}
    return;
  }
  if(mode==AMOUNT_PAYMENT||mode==AMOUNT_TOPUP) {
    if(key>='0'&&key<='9'&&inputDigits.length()<9)inputDigits+=key;
    else if(key=='*'&&inputDigits.length())inputDigits.remove(inputDigits.length()-1);
    else if(key=='#'&&inputDigits.length()&&inputDigits.toInt()>0) {
      long amount=inputDigits.toInt();inputDigits="";
      if(pendingRequestId.isEmpty())persistPending(mode==AMOUNT_TOPUP?"topup":"payment",amount);
      mode=pendingOp=="topup"?ENTER_OPERATOR_PIN:WAIT_CARD_PAYMENT;
      lines(mode==ENTER_OPERATOR_PIN?"PIN OPERATOR":"TEMPEL KARTU",mode==ENTER_OPERATOR_PIN?"Masukkan PIN op":"Nominal "+String(pendingAmount));
    }
    lcd.setCursor(0,1);lcd.print("                ");lcd.setCursor(0,1);lcd.print(inputDigits.length()?inputDigits.substring(inputDigits.length()>16?inputDigits.length()-16:0):"Angka, # OK");
    return;
  }
  if(mode==ENTER_OPERATOR_PIN) {
    if(key>='0'&&key<='9'&&operatorPin.length()<12)operatorPin+=key;
    else if(key=='*'&&operatorPin.length())operatorPin.remove(operatorPin.length()-1);
    else if(key=='#'&&operatorPin.length()>=6){mode=WAIT_CARD_TOPUP;lines("TEMPEL KARTU","PIN op "+masked(operatorPin));}
    lcd.setCursor(0,1);lcd.print(masked(operatorPin));return;
  }
  if(mode==ENTER_PIN_PAYMENT||mode==ENTER_PIN_TOPUP||mode==NFC_ENTER_PIN) {
    if(key>='0'&&key<='9'&&pinDigits.length()<12)pinDigits+=key;
    else if(key=='*'&&pinDigits.length())pinDigits.remove(pinDigits.length()-1);
    else if(key=='#'&&pinDigits.length()>=6) {
      if(mode==ENTER_PIN_PAYMENT)submitPayment();
      else if(mode==ENTER_PIN_TOPUP)submitTopup();
      else submitNfcRegistration();
      return;
    }
    lcd.setCursor(0,1);lcd.print("                ");lcd.setCursor(0,1);lcd.print(masked(pinDigits));return;
  }
}
void pollPendingRegistration() {
  if(mode!=NFC_WAIT_CARD)return;
  String uid=cardUid();if(uid.isEmpty())return;
  pendingCardUid=uid;pinDigits="";mode=NFC_ENTER_PIN;
  JsonDocument progress;progress["session_id"]=nfcSessionId;progress["status"]="pin_pending";
  String body;serializeJson(progress,body);String response;int status;
  if(!mgroup.apiPost("/api/v2/cashier/nfc-registration/progress",body,response,status)) {
    mode=NFC_WAIT_CARD;pendingCardUid="";lines("SERVER OFFLINE","Coba tap lagi");return;
  }
  lines("SET PIN MEMBER","Angka, # OK");
}
void pollCardForPayment() {
  if(mode!=WAIT_CARD_PAYMENT&&mode!=WAIT_CARD_TOPUP)return;
  String uid=cardUid();if(uid.isEmpty())return;
  pendingCardUid=uid;pinDigits="";
  mode=mode==WAIT_CARD_PAYMENT?ENTER_PIN_PAYMENT:ENTER_PIN_TOPUP;
  lines(mode==ENTER_PIN_PAYMENT?"MASUKKAN PIN":"PIN MEMBER","Angka, # OK");
}
}

void setup() {
  mgroup.begin();
  Wire.begin(21,22);lcd.init();lcd.backlight();
  SPI.begin(18,19,23,RFID_SS);
  pn532.begin();uint32_t version=pn532.getFirmwareVersion();
  if(version){pn532.SAMConfig();pn532Ready=true;}
  else {rfid.PCD_Init();rc522Ready=rfid.PCD_PerformSelfTest();}
  Serial.printf("Cashier reader: %s\n",pn532Ready?"PN532":(rc522Ready?"RC522":"NOT_FOUND"));
  restorePending();
  if(!pn532Ready&&!rc522Ready)lines("NFC READER ERROR","Check wiring");
}
void loop() {
  mgroup.loop();
  pollNfcSession();
  pollPendingRegistration();
  pollCardForPayment();
  handleKey(keypad.getKey());
  if(mode==HOME&&millis()%4000<30&&mgroup.wifiConnected()) {
    lines("A=Bayar B=Topup",mgroup.registryId().isEmpty()?"Menunggu registrasi":"Siap "+mgroup.registryId().substring(0,8));
  }
  delay(8);
}
