#include <Arduino.h>
#include <Wire.h>
#include <WiFi.h>
#include <HTTPClient.h>
#include <Preferences.h>
#include <Adafruit_GFX.h>
#include <Adafruit_SSD1306.h>
#include <ESP32Servo.h>
#include "NvmCardReader.h"

const char* WIFI_SSID="CHANGE_ME";
const char* WIFI_PASSWORD="CHANGE_ME";
// Replace with the server LAN IP; default API port is 8011. Do not add a trailing slash.
const char* NVM_BASE_URL="http://192.168.1.10:8011";
const char* DEVICE_ID="vm-01";
const char* NVM_DEVICE_KEY="CHANGE_DEVICE_KEY";

#define I2C_SDA 8
#define I2C_SCL 9
#define PN532_IRQ 7
#define PN532_RESET 10
#define RC522_SCK 12
#define RC522_MISO 13
#define RC522_MOSI 11
#define RC522_SS 14
#define RC522_RST 15
#define BUTTON_UP 4
#define BUTTON_DOWN 5
#define BUTTON_SELECT 6
#define SERVO_COUNT 5
const int SERVO_PINS[SERVO_COUNT]={3,16,17,18,21};
#define OLED_ADDR 0x3C

NvmCardReader card(PN532_IRQ,PN532_RESET,RC522_SCK,RC522_MISO,RC522_MOSI,RC522_SS,RC522_RST);
Adafruit_SSD1306 display(128,64,&Wire,-1);
Servo dispensers[SERVO_COUNT];
Preferences vendingPrefs;
unsigned long lastHeartbeat=0,vendingSequence=0;
bool readerReady=false,displayReady=false,pendingDispenseReport=false,pendingDispenseSuccess=true;
String pendingDispenseTx="";
int selectedIndex=0,productCount=0;

struct Product{String id,name;long price;int stock;bool enabled;int servo_channel;};
Product productsList[16];

String request(const String& method,const String& path,const String& body,int& code){
  HTTPClient http;
  http.setConnectTimeout(3000);
  http.setTimeout(8000);
  http.begin(String(NVM_BASE_URL)+path);
  http.addHeader("Content-Type","application/json");
  http.addHeader("X-NVM-Device-Key",NVM_DEVICE_KEY);
  if(method=="GET")code=http.GET();else if(method=="POST")code=http.POST(body);else code=-1;
  String out=code>0?http.getString():"";http.end();return out;
}
String jsonString(const String& json,const String& key){
  String m="\""+key+"\":\"";int p=json.indexOf(m);if(p<0)return "";p+=m.length();int e=json.indexOf('"',p);return e<0?"":json.substring(p,e);
}
long jsonLong(const String& json,const String& key){
  String m="\""+key+"\":";int p=json.indexOf(m);if(p<0)return -1;p+=m.length();while(p<(int)json.length()&&json[p]==' ')p++;int e=p;while(e<(int)json.length()&&isDigit(json[e]))e++;return json.substring(p,e).toInt();
}
void showMessage(const String&a,const String&b="",const String&c=""){
  if(!displayReady){Serial.printf("DISPLAY: %s | %s | %s\n",a.c_str(),b.c_str(),c.c_str());return;}
  display.clearDisplay();display.setTextSize(1);display.setTextColor(SSD1306_WHITE);display.setCursor(0,0);
  display.println(a);if(b.length())display.println(b);if(c.length())display.println(c);display.display();
}
void heartbeat(){
  if(WiFi.status()!=WL_CONNECTED){Serial.println("HEARTBEAT skipped: WiFi offline");return;}
  int code=0;String body="{\"device_type\":\"esp32-s3-vending\",\"status\":\"active\"}";
  String reply=request("POST",String("/api/v1/devices/")+DEVICE_ID+"/heartbeat",body,code);
  Serial.printf("HEARTBEAT %d %s\n",code,reply.c_str());
}
bool connectWifi(unsigned long timeoutMs=10000){
  WiFi.mode(WIFI_STA);WiFi.setAutoReconnect(true);WiFi.begin(WIFI_SSID,WIFI_PASSWORD);Serial.print("WiFi");
  unsigned long started=millis();
  while(WiFi.status()!=WL_CONNECTED && millis()-started<timeoutMs){delay(250);Serial.print(".");}
  if(WiFi.status()!=WL_CONNECTED){Serial.println("\nWiFi unavailable; retry later");return false;}
  Serial.printf("\nIP %s\n",WiFi.localIP().toString().c_str());
  return true;
}
void parseProducts(const String&json){
  productCount=0;int pos=0;
  while(productCount<16){
    const String productPrefix="\"product_id\":\"";
    int p=json.indexOf(productPrefix,pos);if(p<0)break;int s=p+productPrefix.length(),e=json.indexOf('"',s);if(e<0)break;
    Product&x=productsList[productCount];x.id=json.substring(s,e);
    const String namePrefix="\"name\":\"";
    int n=json.indexOf(namePrefix,e),ns=n<0?-1:n+namePrefix.length(),ne=ns<0?-1:json.indexOf('"',ns);x.name=(ns>=0&&ne>=0)?json.substring(ns,ne):x.id;
    int q=json.indexOf("\"price\":",e);x.price=q>=0?jsonLong(json.substring(q),"price"):0;
    q=json.indexOf("\"stock\":",e);x.stock=q>=0?jsonLong(json.substring(q),"stock"):0;
    q=json.indexOf("\"enabled\":",e);x.enabled=q>=0&&json.substring(q,q+20).indexOf("true")>=0;
    q=json.indexOf("\"servo_channel\":",e);x.servo_channel=q>=0?jsonLong(json.substring(q),"servo_channel"):productCount+1;
    if(x.servo_channel<1||x.servo_channel>SERVO_COUNT)x.servo_channel=productCount+1;
    pos=e+1;productCount++;
  }
}
bool products(){
  int code=0;String reply=request("GET",String("/api/v1/vending/")+DEVICE_ID+"/products","",code);
  Serial.printf("PRODUCTS %d %s\n",code,reply.c_str());
  if(code<200||code>=300){showMessage("SERVER ERROR","Products unavailable");return false;}
  parseProducts(reply);if(!productCount){showMessage("NVM VENDING","No products");return false;}
  if(selectedIndex>=productCount)selectedIndex=0;Product&x=productsList[selectedIndex];
  showMessage("SELECT PRODUCT",x.name,"Rp "+String(x.price));return true;
}
String beginTransaction(const String&product,const String&credential,const String&seq){
  String body="{\"product_id\":\""+product+"\",\"credential_id\":\""+credential+"\",\"idempotency_key\":\""+String(DEVICE_ID)+":"+seq+"\"}";
  String path=String("/api/v1/vending/")+DEVICE_ID+"/transactions";
  for(int attempt=1;attempt<=2;attempt++){
    if(WiFi.status()!=WL_CONNECTED && !connectWifi(3000))continue;
    int code=0;String reply=request("POST",path,body,code);
    String tx=jsonString(reply,"transaction_id");
    Serial.printf("BEGIN attempt=%d code=%d %s\n",attempt,code,reply.c_str());
    if(tx.length())return tx;
    if(code>0 && code<500)return "";
    delay(250);
  }
  return "";
}
bool authorize(const String&tx){
  int code=0;String reply=request("POST","/api/v1/vending/transactions/"+tx+"/authorize","",code);
  Serial.printf("AUTHORIZE %d %s\n",code,reply.c_str());return code>=200&&code<300;
}
void savePendingDispense(const String&tx,bool success){
  vendingPrefs.putString("disp_tx",tx);
  vendingPrefs.putBool("disp_success",success);
  vendingPrefs.putBool("disp_pending",true);
  pendingDispenseTx=tx;pendingDispenseSuccess=success;pendingDispenseReport=true;
}
void clearPendingDispense(){
  vendingPrefs.putBool("disp_pending",false);
  vendingPrefs.remove("disp_tx");vendingPrefs.remove("disp_success");
  pendingDispenseTx="";pendingDispenseReport=false;pendingDispenseSuccess=true;
}
bool reportDispense(const String&tx,bool success){
  String body=success?"{\"success\":true}":"{\"success\":false}";
  for(int attempt=1;attempt<=3;attempt++){
    if(WiFi.status()!=WL_CONNECTED && !connectWifi(3000))continue;
    int code=0;String reply=request("POST","/api/v1/vending/transactions/"+tx+"/dispense",body,code);
    Serial.printf("DISPENSE REPORT attempt=%d code=%d %s\n",attempt,code,reply.c_str());
    if(code>=200&&code<300){clearPendingDispense();return true;}
    if(code>0&&code<500)break;
    delay(300);
  }
  return false;
}
bool dispense(const String&tx,int servoChannel){
  if(servoChannel<1||servoChannel>SERVO_COUNT){
    savePendingDispense(tx,false);
    reportDispense(tx,false);
    return false;
  }
  Servo&servo=dispensers[servoChannel-1];
  servo.write(70);delay(700);servo.write(10);
  // Persist the physical action result before reporting it. A retry must report,
  // never actuate the servo a second time.
  savePendingDispense(tx,true);
  return reportDispense(tx,true);
}
void scanCard(){
  if(!readerReady||!productCount)return;Product&x=productsList[selectedIndex];if(!x.enabled||x.stock<=0)return;
  uint8_t uid[NVM_MAX_UID_LENGTH]={0},len=0;if(!card.readUID(uid,len))return;
  String credential="nfc-";for(uint8_t i=0;i<len;i++){if(uid[i]<16)credential+="0";credential+=String(uid[i],HEX);}credential.toLowerCase();
  showMessage("CARD DETECTED",credential,"Checking...");
  ++vendingSequence;vendingPrefs.putULong("tx_seq",vendingSequence);
  String tx=beginTransaction(x.id,credential,String(vendingSequence));
  if(!tx.length()||!authorize(tx)){showMessage("PAYMENT FAILED");delay(1200);return;}
  showMessage("PAYMENT OK",x.name,"Dispensing...");
  if(dispense(tx,x.servo_channel)){showMessage("TAKE PRODUCT",x.name);delay(800);products();}
  else if(pendingDispenseReport)showMessage("RESULT PENDING","Retry server report");
  else showMessage("DISPENSE ERROR","Refund recorded");
  delay(1000);
}
void setup(){
  Serial.begin(115200);delay(300);
  vendingPrefs.begin("nvm-vend",false);
  vendingSequence=vendingPrefs.getULong("tx_seq",0);
  pendingDispenseReport=vendingPrefs.getBool("disp_pending",false);
  if(pendingDispenseReport){
    pendingDispenseTx=vendingPrefs.getString("disp_tx","");
    pendingDispenseSuccess=vendingPrefs.getBool("disp_success",true);
    if(!pendingDispenseTx.length()){Serial.println("FATAL: pending dispense transaction ID missing");while(true)delay(1000);}
  }
  pinMode(BUTTON_UP,INPUT_PULLUP);pinMode(BUTTON_DOWN,INPUT_PULLUP);pinMode(BUTTON_SELECT,INPUT_PULLUP);
  Wire.begin(I2C_SDA,I2C_SCL);displayReady=display.begin(SSD1306_SWITCHCAPVCC,OLED_ADDR);
  for(int i=0;i<SERVO_COUNT;i++){dispensers[i].setPeriodHertz(50);dispensers[i].attach(SERVO_PINS[i],500,2400);dispensers[i].write(10);}
  showMessage("NVM VENDING","Starting...");
  if(connectWifi()){heartbeat();products();}
  readerReady=card.begin(I2C_SDA,I2C_SCL);
}
void loop(){
  if(WiFi.status()!=WL_CONNECTED){showMessage("SERVER ERROR","WiFi disconnected");connectWifi(3000);delay(100);return;}
  if(pendingDispenseReport){
    showMessage("RESULT PENDING","Retry server report");
    reportDispense(pendingDispenseTx,pendingDispenseSuccess);
    delay(250);return;
  }
  if(millis()-lastHeartbeat>=30000UL){lastHeartbeat=millis();heartbeat();}
  if(digitalRead(BUTTON_UP)==LOW){if(productCount)selectedIndex=(selectedIndex+productCount-1)%productCount;products();delay(250);}
  if(digitalRead(BUTTON_DOWN)==LOW){if(productCount)selectedIndex=(selectedIndex+1)%productCount;products();delay(250);}
  if(digitalRead(BUTTON_SELECT)==LOW){showMessage("READY",productCount?productsList[selectedIndex].name:"No product","Tap NFC card");delay(250);}
  scanCard();
  if(Serial.available()){String line=Serial.readStringUntil('\n');line.trim();if(line=="PRODUCTS")products();}
}
