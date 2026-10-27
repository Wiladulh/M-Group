#include <Arduino.h>
#include <Wire.h>
#include <SPI.h>
#include <MFRC522.h>
#include <Adafruit_PN532.h>
#include <Adafruit_GFX.h>
#include <Adafruit_SSD1306.h>
#include <ESP32Servo.h>
#include <ArduinoJson.h>
#include "MGroupV2Runtime.h"

namespace {
constexpr uint8_t OLED_SDA=8,OLED_SCL=9;
constexpr uint8_t BUTTON_UP=4,BUTTON_DOWN=5,BUTTON_SELECT=6;
constexpr uint8_t PN532_IRQ=7,PN532_RESET=10;
constexpr uint8_t RFID_SS=14,RFID_RST=15;
constexpr uint8_t IR_SENSOR=1;
constexpr uint8_t SERVO_COUNT=5;
const uint8_t servoPins[SERVO_COUNT]={3,16,17,18,21};
constexpr int PRODUCT_SENSOR_BLOCKED_LEVEL=HIGH;
Adafruit_SSD1306 oled(128,64,&Wire,-1);
MFRC522 rfid(RFID_SS,RFID_RST);
Adafruit_PN532 pn532(PN532_IRQ,PN532_RESET);
Servo servos[SERVO_COUNT];
bool displayReady=false,pn532Ready=false,rc522Ready=false,catalogOnline=false;
struct Product { int id=0;String name;long price=0;int stock=0;int capacity=0; };
Product products[5];
int productCount=0,selected=0,currentDigit=0;
String lastCardUid,pinDigits,pendingCardUid,pendingRequestId,pendingTransactionId,pendingStage,pendingReason;
int pendingProduct=0;long pendingAmount=0;bool pendingResult=false;
enum Flow { SELECT_PRODUCT, WAIT_CARD, ENTER_PIN, MANUAL_REVIEW };
Flow flow=SELECT_PRODUCT;
unsigned long lastCatalogAt=0,lastReportRetryAt=0,lastButtonAt=0,selectPressedAt=0;
bool previousUp=HIGH,previousDown=HIGH,previousSelect=HIGH;

void draw(const String& a,const String& b="",const String& c="") {
  if(!displayReady)return;
  oled.clearDisplay();oled.setTextColor(SSD1306_WHITE);oled.setTextSize(1);
  oled.setCursor(0,0);oled.println(a.substring(0,21));
  oled.setCursor(0,18);oled.println(b.substring(0,21));
  oled.setCursor(0,36);oled.println(c.substring(0,21));oled.display();
}
void clearPending() {
  Preferences& p=mgroup.prefs();
  for(const char* key:{"purchase_req","purchase_product","purchase_amount","purchase_stage","purchase_txn","purchase_result","purchase_reason"})p.remove(key);
  pendingRequestId="";pendingProduct=0;pendingAmount=0;pendingStage="";pendingTransactionId="";pendingReason="";pendingResult=false;
}
void persistCreateRequest(int productId,long amount) {
  pendingRequestId=mgroup.nextRequestId("vending-purchase");pendingProduct=productId;pendingAmount=amount;pendingStage="create";
  Preferences& p=mgroup.prefs();p.putString("purchase_req",pendingRequestId);p.putInt("purchase_product",productId);p.putLong("purchase_amount",amount);p.putString("purchase_stage",pendingStage);
}
String responseCode(const String& body) {
  JsonDocument doc;if(deserializeJson(doc,body)==DeserializationError::Ok) {
    if(doc["detail"]["code"].is<const char*>())return doc["detail"]["code"].as<String>();
    if(doc["code"].is<const char*>())return doc["code"].as<String>();
  }
  return "";
}
bool validateCatalog(const JsonDocument& doc,Product out[5]) {
  JsonArrayConst items=doc["items"].as<JsonArrayConst>();
  if(items.isNull()||items.size()!=SERVO_COUNT)return false;
  bool seen[6]={false};
  for(JsonObjectConst item:items) {
    int id=item["product_id"]|0;long price=item["price_minor"]|0L;int stock=item["stock"]|0;int capacity=item["capacity"]|0;
    if(id<1||id>SERVO_COUNT||seen[id]||price<0||stock<0||capacity<0||stock>capacity)return false;
    seen[id]=true;out[id-1].id=id;out[id-1].name=item["name"]|String("Produk ")+String(id);
    out[id-1].price=price;out[id-1].stock=stock;out[id-1].capacity=capacity;
  }
  for(int id=1;id<=SERVO_COUNT;id++)if(!seen[id])return false;
  return true;
}
void loadCache() {
  String cached=mgroup.prefs().getString("catalog_json","");
  if(cached.isEmpty()){productCount=0;return;}
  JsonDocument doc;
  if(deserializeJson(doc,cached)!=DeserializationError::Ok||!validateCatalog(doc,products)){productCount=0;return;}
  productCount=SERVO_COUNT;
}
bool refreshCatalog() {
  String response;int status=0;
  if(!mgroup.apiGet("/api/v2/device/products",response,status)) {
    catalogOnline=false;mgroup.setRuntimeStatus("catalog_offline","Katalog cache hanya untuk display; transaksi dinonaktifkan.");
    loadCache();return false;
  }
  JsonDocument doc;
  if(deserializeJson(doc,response)!=DeserializationError::Ok) {
    catalogOnline=false;mgroup.setRuntimeStatus("catalog_invalid","Respons katalog bukan JSON valid.");loadCache();return false;
  }
  Product candidate[5];
  if(!validateCatalog(doc,candidate)) {
    catalogOnline=false;mgroup.setRuntimeStatus("catalog_invalid","Lima slot produk atau kapasitas tidak konsisten.");loadCache();return false;
  }
  String normalized;serializeJson(doc,normalized);
  // Replace last-known-good cache only after full structural validation.
  mgroup.prefs().putString("catalog_json",normalized);
  for(int i=0;i<SERVO_COUNT;i++)products[i]=candidate[i];
  productCount=SERVO_COUNT;catalogOnline=true;lastCatalogAt=millis();
  mgroup.setRuntimeStatus("catalog_online","Katalog valid dan sinkron dengan server.");
  if(selected>=productCount)selected=0;
  return true;
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
  lastCardUid=value;return value;
}
bool reportDispenseResult() {
  if(pendingTransactionId.isEmpty()||pendingStage!="report_pending")return false;
  JsonDocument doc;doc["succeeded"]=pendingResult;
  if(!pendingResult)doc["reason"]=pendingReason.isEmpty()?"sensor_no_product":pendingReason;
  String body;serializeJson(doc,body);String response;int status=0;
  String path="/api/v2/vending/transactions/"+pendingTransactionId+"/dispense-result";
  if(!mgroup.apiPost(path,body,response,status)) {
    mgroup.setRuntimeStatus("dispense_report_pending","Hasil dispensing belum dikonfirmasi server; retry otomatis.");
    return false;
  }
  String resultCode=responseCode(response);
  clearPending();flow=SELECT_PRODUCT;pinDigits="";pendingCardUid="";
  refreshCatalog();
  draw(pendingResult?"DISPENSING OK":"REFUND BERHASIL",pendingResult?"Transaksi selesai":"Stok dan saldo dipulihkan",resultCode);
  delay(1300);return true;
}
bool waitForProduct(uint32_t timeoutMs=4000) {
  unsigned long start=millis();bool blocked=false;
  while(millis()-start<timeoutMs) {
    mgroup.loop();
    int level=digitalRead(IR_SENSOR);
    if(level==PRODUCT_SENSOR_BLOCKED_LEVEL)blocked=true;
    if(blocked&&level!=PRODUCT_SENSOR_BLOCKED_LEVEL)return true;
    delay(5);
  }
  return false;
}
void actuateAndVerify() {
  if(pendingStage!="dispensing"||pendingTransactionId.isEmpty())return;
  if(pendingProduct<1||pendingProduct>SERVO_COUNT){flow=MANUAL_REVIEW;draw("MANUAL REVIEW","Slot tidak valid","Jangan dispense");return;}
  // Persist "dispensing" before touching hardware. On reboot this stage is
  // never replayed automatically because the physical outcome is uncertain.
  draw("DISPENSING","Tunggu sensor","Jangan cabut daya");
  Servo& servo=servos[pendingProduct-1];
  servo.write(70);delay(550);servo.write(10);delay(300);
  bool succeeded=waitForProduct();
  pendingResult=succeeded;pendingReason=succeeded?"":"sensor_no_product";pendingStage="report_pending";
  Preferences& p=mgroup.prefs();p.putString("purchase_stage",pendingStage);p.putBool("purchase_result",pendingResult);p.putString("purchase_reason",pendingReason);
  lastReportRetryAt=0;
  reportDispenseResult();
}
void beginPurchase() {
  if(!catalogOnline){draw("SERVER OFFLINE","Pembayaran mati","Coba lagi nanti");flow=SELECT_PRODUCT;return;}
  Product& p=products[selected];
  if(p.price<=0){draw("PRODUK BELUM SIAP","Atur harga di WebUI");flow=SELECT_PRODUCT;return;}
  if(p.stock<=0){draw("STOK HABIS",p.name,"Pilih produk lain");flow=SELECT_PRODUCT;return;}
  if(pendingRequestId.isEmpty())persistCreateRequest(p.id,p.price);
  pendingCardUid="";pinDigits="";currentDigit=0;flow=WAIT_CARD;
  draw(p.name,"Tempel kartu NFC","Harga "+String(p.price));
}
void sendPurchase() {
  if(pinDigits.length()<6){draw("PIN MINIMAL 6","Pilih 6 digit");return;}
  JsonDocument doc;doc["request_id"]=pendingRequestId;doc["card_uid"]=pendingCardUid;doc["pin"]=pinDigits;
  doc["product_id"]=pendingProduct;doc["payment_method"]="nfc";doc["expected_amount_minor"]=pendingAmount;
  String body;serializeJson(doc,body);String response;int status=0;
  bool ok=mgroup.apiPost("/api/v2/vending/purchases",body,response,status);
  pinDigits="";
  if(!ok) {
    String code=responseCode(response);
    if(status>=400&&status<500&&code!="IDEMPOTENCY_CONFLICT") {
      clearPending();flow=SELECT_PRODUCT;pendingCardUid="";
      draw("TRANSAKSI DITOLAK",code.substring(0,21),"Pilih ulang");
    } else {
      flow=WAIT_CARD;pendingCardUid="";
      draw("HASIL BELUM ADA","Tap ulang; PIN ulang","Request tetap sama");
    }
    return;
  }
  JsonDocument result;
  if(deserializeJson(result,response)!=DeserializationError::Ok||!result["transaction_id"].is<const char*>()) {
    flow=WAIT_CARD;pendingCardUid="";draw("RESPONS INVALID","Tap ulang; PIN ulang");return;
  }
  pendingTransactionId=result["transaction_id"].as<String>();
  String statusText=result["status"]|String("pending");
  if(statusText=="succeeded") {clearPending();flow=SELECT_PRODUCT;draw("SUDAH SELESAI","Replay idempoten");return;}
  pendingStage="dispensing";
  Preferences& prefs=mgroup.prefs();prefs.putString("purchase_txn",pendingTransactionId);prefs.putString("purchase_stage",pendingStage);
  prefs.putString("purchase_req",pendingRequestId);prefs.putInt("purchase_product",pendingProduct);prefs.putLong("purchase_amount",pendingAmount);
  pendingCardUid="";
  actuateAndVerify();
}
void restorePending() {
  Preferences& p=mgroup.prefs();pendingRequestId=p.getString("purchase_req","");pendingProduct=p.getInt("purchase_product",0);
  pendingAmount=p.getLong("purchase_amount",0);pendingStage=p.getString("purchase_stage","");
  pendingTransactionId=p.getString("purchase_txn","");pendingResult=p.getBool("purchase_result",false);pendingReason=p.getString("purchase_reason","");
  if(pendingStage=="report_pending"&&!pendingTransactionId.isEmpty()) {
    flow=MANUAL_REVIEW;mgroup.setRuntimeStatus("dispense_report_pending","Retry report hasil dispense tanpa menggerakkan servo ulang.");
    draw("LAPORAN TERTUNDA","Mengirim hasil","Servo tidak diulang");
  } else if(pendingStage=="dispensing"&&!pendingTransactionId.isEmpty()) {
    flow=MANUAL_REVIEW;mgroup.setRuntimeStatus("dispense_manual_review","Daya terputus saat dispensing; tindakan fisik tidak diulang otomatis.");
    draw("MANUAL REVIEW","Dispense ambigu","Jangan ulangi servo");
  } else if(pendingStage=="create"&&!pendingRequestId.isEmpty()&&pendingProduct>0&&pendingAmount>0) {
    flow=WAIT_CARD;draw("TRANSAKSI TERTUNDA","Tap ulang kartu","PIN ulang; request sama");
  } else {clearPending();flow=SELECT_PRODUCT;}
}
void handleButtons() {
  bool up=digitalRead(BUTTON_UP),down=digitalRead(BUTTON_DOWN),select=digitalRead(BUTTON_SELECT);
  unsigned long now=millis();
  if(flow==SELECT_PRODUCT&&now-lastButtonAt>140) {
    if(previousUp==HIGH&&up==LOW&&productCount){selected=(selected+productCount-1)%productCount;lastButtonAt=now;}
    else if(previousDown==HIGH&&down==LOW&&productCount){selected=(selected+1)%productCount;lastButtonAt=now;}
    else if(previousSelect==HIGH&&select==LOW){lastButtonAt=now;beginPurchase();}
  } else if(flow==ENTER_PIN) {
    if(previousUp==HIGH&&up==LOW){currentDigit=(currentDigit+1)%10;lastButtonAt=now;}
    if(previousDown==HIGH&&down==LOW){currentDigit=(currentDigit+9)%10;lastButtonAt=now;}
    if(previousSelect==HIGH&&select==LOW) {
      if(pinDigits.length()<6)pinDigits+=char('0'+currentDigit);
      currentDigit=0;lastButtonAt=now;
      if(pinDigits.length()>=6)sendPurchase();
    }
    draw("MASUKKAN PIN",String("PIN: ")+String(String(pinDigits.length(),'*')),"UP/DN digit SEL");
  }
  previousUp=up;previousDown=down;previousSelect=select;
}
void pollCard() {
  if(flow!=WAIT_CARD)return;
  String uid=cardUid();if(uid.isEmpty())return;
  pendingCardUid=uid;pinDigits="";currentDigit=0;flow=ENTER_PIN;
  draw("PIN TRANSAKSI","UP/DN digit SEL","6 digit minimum");
}
}

void setup() {
  mgroup.begin();
  Wire.begin(OLED_SDA,OLED_SCL);
  displayReady=oled.begin(SSD1306_SWITCHCAPVCC,0x3C);
  if(displayReady)draw("M-GROUP VENDING","Memulai...");
  pinMode(BUTTON_UP,INPUT_PULLUP);pinMode(BUTTON_DOWN,INPUT_PULLUP);pinMode(BUTTON_SELECT,INPUT_PULLUP);
  pinMode(IR_SENSOR,INPUT_PULLUP);
  SPI.begin(12,13,11,RFID_SS);
  pn532.begin();uint32_t version=pn532.getFirmwareVersion();
  if(version){pn532.SAMConfig();pn532Ready=true;}
  else {rfid.PCD_Init();rc522Ready=rfid.PCD_PerformSelfTest();}
  for(int i=0;i<SERVO_COUNT;i++){servos[i].setPeriodHertz(50);servos[i].attach(servoPins[i],500,2400);servos[i].write(10);}
  restorePending();
  if(!pn532Ready&&!rc522Ready)draw("NFC READER ERROR","Check wiring");
  else if(flow==SELECT_PRODUCT)draw("SINKRON KATALOG","Tunggu server");
  refreshCatalog();
}
void loop() {
  mgroup.loop();
  if(millis()-lastCatalogAt>60000UL&&flow==SELECT_PRODUCT)refreshCatalog();
  if(flow==MANUAL_REVIEW&&pendingStage=="report_pending"&&millis()-lastReportRetryAt>5000UL) {
    lastReportRetryAt=millis();reportDispenseResult();
  }
  if(flow==SELECT_PRODUCT&&productCount) {
    Product& p=products[selected];
    draw(String(p.id)+". "+p.name, p.price>0?("Rp "+String(p.price)):"Harga belum diatur",
         catalogOnline?(p.stock>0?"Stok "+String(p.stock)+" | SELECT":"STOK HABIS"):"OFFLINE - BAYAR MATI");
  } else if(flow==SELECT_PRODUCT&&!productCount)draw("KATALOG KOSONG","Atur produk di WebUI");
  pollCard();handleButtons();delay(12);
}
