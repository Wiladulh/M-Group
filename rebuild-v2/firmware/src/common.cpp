#include "MGroupV2Runtime.h"
#include <WiFi.h>
#include <time.h>
#include <WiFiClient.h>
#include <WiFiClientSecure.h>
#include <HTTPClient.h>
#include <ArduinoJson.h>
#include <mbedtls/sha256.h>

MGroupV2Runtime mgroup;

String MGroupV2Runtime::randomToken(size_t bytes) {
  String value;
  for (size_t i=0;i<(bytes+3)/4;i++) {
    char part[9]; snprintf(part,sizeof(part),"%08lx",(unsigned long)esp_random()); value+=part;
  }
  value.toLowerCase();
  return value.substring(0,bytes*2);
}

String MGroupV2Runtime::sha256Hex(const String& value) {
  uint8_t digest[32]; mbedtls_sha256((const unsigned char*)value.c_str(),value.length(),digest,0);
  char output[65];
  for(int i=0;i<32;i++) snprintf(output+i*2,3,"%02x",digest[i]);
  output[64]='\0';
  return String(output);
}

void MGroupV2Runtime::loadConfiguration() {
  prefs_.begin("mgroup-v2",false);
  ssid_=prefs_.getString("wifi_ssid","");
  wifiPassword_=prefs_.getString("wifi_pass","");
  serverUrl_=prefs_.getString("server_url","");
  deviceKey_=prefs_.getString("device_key","");
  tlsCa_=prefs_.getString("tls_ca","");
  registryId_=prefs_.getString("registry_id","");
  uint64_t mac=ESP.getEfuseMac();
  char macText[13]; snprintf(macText,sizeof(macText),"%012llX",(unsigned long long)mac);
  macAddress_=String(macText);
#ifdef DEVICE_CASHIER
  hardwareId_="MG-CASHIER-"+macAddress_;
#else
  hardwareId_="MG-VENDING-"+macAddress_;
#endif
  webPinSalt_=prefs_.getString("web_pin_salt","");
  webPinHash_=prefs_.getString("web_pin_hash","");
  if(webPinSalt_.isEmpty()||webPinHash_.isEmpty()) {
    uint32_t pin=esp_random()%100000000UL;
    char pinText[9];snprintf(pinText,sizeof(pinText),"%08lu",(unsigned long)pin);
    storeWebPin(String(pinText));
    Serial.printf("Initial local WebUI PIN (save it, then rotate): %s\n",pinText);
  }
}

void MGroupV2Runtime::storeWebPin(const String& pin) {
  webPinSalt_=randomToken(16);
  webPinHash_=sha256Hex(webPinSalt_+pin);
  prefs_.putString("web_pin_salt",webPinSalt_);
  prefs_.putString("web_pin_hash",webPinHash_);
}

bool MGroupV2Runtime::pinMatches(const String& pin) {
  if(pin.length()<8||pin.length()>32)return false;
  String candidate=sha256Hex(webPinSalt_+pin);
  if(candidate.length()!=webPinHash_.length())return false;
  uint8_t difference=0;for(size_t i=0;i<candidate.length();i++)difference|=(uint8_t)(candidate[i]^webPinHash_[i]);
  return difference==0;
}

bool MGroupV2Runtime::wifiConnected() const { return WiFi.status()==WL_CONNECTED; }

void MGroupV2Runtime::connectNetwork() {
  WiFi.mode(WIFI_STA);
  if(!ssid_.isEmpty()) {
    WiFi.begin(ssid_.c_str(),wifiPassword_.c_str());
    unsigned long until=millis()+15000UL;
    while(WiFi.status()!=WL_CONNECTED&&(long)(millis()-until)<0)delay(250);
  }
  if(WiFi.status()!=WL_CONNECTED) {
    WiFi.mode(WIFI_AP_STA);
    String suffix=macAddress_.substring(macAddress_.length()-4);
    String apName="MGroupV2-Setup-"+suffix;
    String apPass=randomToken(8).substring(0,12);
    WiFi.softAP(apName.c_str(),apPass.c_str());
    apMode_=true;
    Serial.printf("M-GROUP V2 setup AP: %s\nAP password: %s\nOpen http://192.168.4.1/\n",apName.c_str(),apPass.c_str());
  } else {
    apMode_=false;
    configTime(0,0,"pool.ntp.org","time.google.com");
    Serial.printf("M-GROUP V2 WebUI: http://%s/\n",WiFi.localIP().toString().c_str());
  }
}

bool MGroupV2Runtime::authorized() {
  if(!sessionExpiresAt_||(long)(millis()-sessionExpiresAt_)>=0||!server_.hasHeader("Cookie"))return false;
  String cookie=server_.header("Cookie");
  String needle="mg_session="+sessionToken_;
  int pos=cookie.indexOf(needle);
  if(pos<0)return false;
  if(pos>0&&cookie.charAt(pos-1)!=' '&&cookie.charAt(pos-1)!=';')return false;
  int end=pos+needle.length();
  return end==cookie.length()||cookie.charAt(end)==';'||cookie.charAt(end)==' ';
}

String MGroupV2Runtime::loginPage() {
  return F("<!doctype html><html lang='id'><meta name='viewport' content='width=device-width,initial-scale=1'><title>M-Group Device Login</title><body style='font:16px system-ui;max-width:440px;margin:10vh auto;padding:20px;background:#f3f5f7'><h2>WebUI Perangkat M-Group v2</h2><p>Masukkan PIN WebUI lokal. PIN awal ditampilkan satu kali pada Serial Monitor saat boot pertama.</p><form method='post' action='/login'><input name='pin' type='password' minlength='8' maxlength='32' autocomplete='current-password' required style='padding:12px;width:95%;box-sizing:border-box'><button style='padding:12px;margin-top:12px'>Masuk</button></form></body></html>");
}

String MGroupV2Runtime::statusJson() {
  JsonDocument doc;
  doc["hardware_id"]=hardwareId_;
  doc["registry_id"]=registryId_;
#ifdef DEVICE_CASHIER
  doc["device_type"]="cashier";
#else
  doc["device_type"]="vending";
#endif
  doc["wifi_connected"]=wifiConnected();
  doc["ip"]=wifiConnected()?WiFi.localIP().toString():(apMode_?WiFi.softAPIP().toString():String(""));
  doc["rssi"]=wifiConnected()?WiFi.RSSI():0;
  doc["server_url"]=serverUrl_;
  doc["device_key_configured"]=!deviceKey_.isEmpty();
  doc["tls_ca_configured"]=!tlsCa_.isEmpty();
  doc["runtime_status"]=runtimeStatus_;
  doc["runtime_detail"]=runtimeDetail_;
  String body;serializeJson(doc,body);return body;
}

String MGroupV2Runtime::configPage() {
  String h=F("<!doctype html><html lang='id'><meta name='viewport' content='width=device-width,initial-scale=1'><title>Konfigurasi M-Group v2</title><style>body{font:16px system-ui;background:#f3f5f7;color:#17202a;margin:0;padding:20px}main{max-width:620px;margin:auto;background:white;padding:22px;border-radius:14px;box-shadow:0 4px 18px #0001}label{display:block;font-weight:600;margin:14px 0 5px}input,textarea{box-sizing:border-box;width:100%;padding:12px;border:1px solid #bbc4cc;border-radius:8px;font:inherit}button{margin-top:16px;padding:12px;background:#175cd3;color:white;border:0;border-radius:8px;font:inherit;font-weight:700}pre{white-space:pre-wrap;background:#f3f5f7;padding:12px;border-radius:8px}.warn{background:#fff7e6;padding:10px;border-radius:8px}</style><main><h2>Konfigurasi Perangkat M-Group v2</h2><p>WebUI tersedia pada IP DHCP perangkat, port 80. Simpan Device Key secara rahasia; key tidak pernah ditampilkan pada halaman status.</p><section><h3>Status</h3><pre id='status'>Memuat...</pre><button type='button' onclick="fetch('/test').then(r=>r.json()).then(x=>alert(x.detail)).catch(()=>alert('Uji koneksi gagal'))">Uji koneksi server</button></section><form method='post' action='/save'><label>Wi-Fi SSID</label><input name='ssid' maxlength='64' required autocomplete='off'><label>Password Wi-Fi</label><input name='wifi_password' type='password' maxlength='128' autocomplete='new-password'><label>URL server v2</label><input name='server_url' type='url' maxlength='160' placeholder='https://server-anda' required><label>CA certificate untuk HTTPS (wajib untuk HTTPS)</label><textarea name='tls_ca' maxlength='3500' rows='5' placeholder='-----BEGIN CERTIFICATE----- ...'></textarea><label>Device Key dari dashboard</label><input name='device_key' type='password' maxlength='128' required autocomplete='off'><button type='submit'>Simpan & Restart</button></form><hr><h3>Ganti PIN WebUI</h3><form method='post' action='/change-pin'><label>PIN saat ini</label><input name='old_pin' type='password' minlength='8' maxlength='32' required><label>PIN baru</label><input name='new_pin' type='password' minlength='8' maxlength='32' required><label>Ulangi PIN baru</label><input name='confirm_pin' type='password' minlength='8' maxlength='32' required><button type='submit'>Ganti PIN</button></form><p class='warn'>HTTPS tanpa CA valid ditolak. Jangan memakai mode insecure. Device Key, PIN, dan password Wi-Fi tidak ditulis ke log.</p><button type='button' onclick="fetch('/logout',{method:'POST'}).then(()=>location.reload())">Logout</button><script>fetch('/status').then(r=>r.json()).then(s=>document.getElementById('status').textContent='Hardware ID: '+s.hardware_id+'\\nRegistry ID: '+s.registry_id+'\\nIP DHCP: '+s.ip+'\\nWi-Fi: '+(s.wifi_connected?'Terhubung':'Terputus')+'\\nRSSI: '+s.rssi+' dBm\\nServer: '+s.server_url+'\\nDevice key: '+(s.device_key_configured?'Tersimpan':'Belum diatur')+'\\nTLS CA: '+(s.tls_ca_configured?'Tersimpan':'Belum diatur')+'\\nStatus: '+s.runtime_status+'\\nDetail: '+s.runtime_detail).catch(()=>document.getElementById('status').textContent='Status tidak tersedia');</script></main></html>");
  return h;
}

void MGroupV2Runtime::startWebUI() {
  const char* headers[]={"Cookie"};server_.collectHeaders(headers,1);
  server_.on("/",HTTP_GET,[this](){if(!authorized()){server_.send(200,"text/html; charset=utf-8",loginPage());return;}server_.send(200,"text/html; charset=utf-8",configPage());});
  server_.on("/login",HTTP_POST,[this](){
    if(millis()<pinLockUntil_){server_.send(429,"text/plain","Terlalu banyak percobaan. Coba lagi 15 menit.");return;}
    String pin=server_.arg("pin");
    if(!pinMatches(pin)){
      if(++pinFailures_>=5){pinFailures_=0;pinLockUntil_=millis()+900000UL;}
      server_.send(401,"text/html; charset=utf-8",loginPage()+"<p>PIN salah atau percobaan dibatasi.</p>");return;
    }
    pinFailures_=0;sessionToken_=randomToken(24);sessionExpiresAt_=millis()+1800000UL;
    server_.sendHeader("Location","/");
    server_.sendHeader("Set-Cookie","mg_session="+sessionToken_+"; HttpOnly; SameSite=Strict; Path=/; Max-Age=1800");
    server_.send(303,"text/plain","Login berhasil.");
  });
  server_.on("/logout",HTTP_POST,[this](){sessionExpiresAt_=0;sessionToken_="";server_.sendHeader("Set-Cookie","mg_session=; HttpOnly; SameSite=Strict; Path=/; Max-Age=0");server_.send(200,"text/plain","Logout.");});
  server_.on("/status",HTTP_GET,[this](){if(!authorized()){server_.send(401,"application/json","{\"detail\":\"login_required\"}");return;}server_.send(200,"application/json",statusJson());});
  server_.on("/test",HTTP_GET,[this](){
    if(!authorized()){server_.send(401,"application/json","{\"detail\":\"login_required\"}");return;}
    String response;int code=0;bool ok=serverHealth();
    JsonDocument doc;doc["ok"]=ok;doc["detail"]=ok?"server_reachable":"server_unreachable";doc["host"]=serverUrl_;
    String body;serializeJson(doc,body);server_.send(ok?200:503,"application/json",body);
  });
  server_.on("/save",HTTP_POST,[this](){
    if(!authorized()){server_.send(401,"text/plain","Login required.");return;}
    String ssid=server_.arg("ssid"),password=server_.arg("wifi_password"),url=server_.arg("server_url"),key=server_.arg("device_key"),ca=server_.arg("tls_ca");
    ssid.trim();url.trim();key.trim();
    if(ssid.isEmpty()||ssid.length()>64||password.length()>128||key.isEmpty()||key.length()>128||url.length()>160||ca.length()>3500||
       !(url.startsWith("http://")||url.startsWith("https://"))||url.endsWith("/")||(url.startsWith("https://")&&ca.isEmpty())){
      server_.send(400,"text/plain","Konfigurasi tidak valid. HTTPS membutuhkan CA tepercaya dan URL tanpa slash akhir.");return;
    }
    prefs_.putString("wifi_ssid",ssid);prefs_.putString("wifi_pass",password);prefs_.putString("server_url",url);prefs_.putString("device_key",key);prefs_.putString("tls_ca",ca);
    prefs_.remove("registry_id");
    registryId_="";
    server_.send(200,"text/html; charset=utf-8","<!doctype html><meta name='viewport' content='width=device-width'><h2>Konfigurasi tersimpan</h2><p>Perangkat akan restart.</p>");
    delay(700);ESP.restart();
  });
  server_.on("/change-pin",HTTP_POST,[this](){
    if(!authorized()){server_.send(401,"text/plain","Login required.");return;}
    String oldPin=server_.arg("old_pin"),newPin=server_.arg("new_pin"),confirm=server_.arg("confirm_pin");
    if(!pinMatches(oldPin)){server_.send(403,"text/plain","PIN saat ini salah.");return;}
    if(newPin.length()<8||newPin.length()>32||newPin!=confirm){server_.send(400,"text/plain","PIN baru harus 8-32 karakter dan cocok dengan konfirmasi.");return;}
    storeWebPin(newPin);server_.send(200,"text/html; charset=utf-8","<!doctype html><meta name='viewport' content='width=device-width'><h2>PIN WebUI diperbarui.</h2><a href='/'>Kembali</a>");
  });
  server_.onNotFound([this](){if(!authorized()){server_.send(401,"text/plain","Login required.");return;}server_.send(404,"text/plain","Not found");});
  server_.begin();serverStarted_=true;
}

void MGroupV2Runtime::begin() {
  Serial.begin(115200);
  loadConfiguration();
  connectNetwork();
  startWebUI();
  if(wifiConnected()&&serverUrl_.length()&&deviceKey_.length())ensureRegistered();
  else setRuntimeStatus("configuration_required","Isi Wi-Fi, server URL, dan Device Key melalui WebUI lokal.");
}

void MGroupV2Runtime::loop() {
  if(serverStarted_)server_.handleClient();
  static unsigned long lastReconnect=0;
  if(!wifiConnected()&&ssid_.length()&&millis()-lastReconnect>10000UL) {
    lastReconnect=millis();WiFi.disconnect();WiFi.begin(ssid_.c_str(),wifiPassword_.c_str());
  }
  static unsigned long lastEnroll=0;
  if(wifiConnected()&&deviceKey_.length()&&serverUrl_.length()&&registryId_.isEmpty()&&millis()-lastEnroll>10000UL) {
    lastEnroll=millis();ensureRegistered();
  }
}

int MGroupV2Runtime::requestHttp(const String& method,const String& path,const String& body,String& response,bool withDeviceKey) {
  if(!wifiConnected()||serverUrl_.isEmpty())return -1;
  String url=serverUrl_+path;HTTPClient http;http.setConnectTimeout(3500);http.setTimeout(8000);
  int code=-1;
  if(url.startsWith("https://")) {
    if(tlsCa_.isEmpty())return -2;
    WiFiClientSecure client;client.setCACert(tlsCa_.c_str());
    if(!http.begin(client,url))return -2;
    if(withDeviceKey)http.addHeader("X-Device-Key",deviceKey_);
    if(method!="GET")http.addHeader("Content-Type","application/json");
    code=method=="GET"?http.GET():http.POST(body);response=http.getString();http.end();
  } else {
    WiFiClient client;
    if(!http.begin(client,url))return -2;
    if(withDeviceKey)http.addHeader("X-Device-Key",deviceKey_);
    if(method!="GET")http.addHeader("Content-Type","application/json");
    code=method=="GET"?http.GET():http.POST(body);response=http.getString();http.end();
  }
  return code;
}

bool MGroupV2Runtime::apiGet(const String& path,String& response,int& status) {
  status=requestHttp("GET",path,"",response,true);
  return status>=200&&status<300;
}
bool MGroupV2Runtime::apiPost(const String& path,const String& body,String& response,int& status) {
  status=requestHttp("POST",path,body,response,true);
  return status>=200&&status<300;
}
bool MGroupV2Runtime::serverHealth() {
  String response;int status=requestHttp("GET","/api/v2/health","",response,false);
  return status>=200&&status<300;
}
bool MGroupV2Runtime::ensureRegistered() {
  if(!wifiConnected()||deviceKey_.isEmpty()||serverUrl_.isEmpty())return false;
  JsonDocument doc;doc["hardware_id"]=hardwareId_;doc["mac_address"]=macAddress_;
  String body;serializeJson(doc,body);String response;int status=requestHttp("POST","/api/v2/device/register",body,response,true);
  if(status>=200&&status<300) {
    JsonDocument result; if(deserializeJson(result,response)==DeserializationError::Ok&&result["registry_id"].is<const char*>()) {
      registryId_=result["registry_id"].as<String>();prefs_.putString("registry_id",registryId_);
      setRuntimeStatus("registered","Device key diterima server; registry terikat ke hardware_id.");
      Serial.printf("Device enrolled. Hardware identity: %s; registry assigned by server.\n",hardwareId_.c_str());
      return true;
    }
  }
  setRuntimeStatus("enrollment_pending","Enrollment server belum berhasil; retry otomatis.");
  return false;
}
String MGroupV2Runtime::nextRequestId(const String& operation) {
  uint64_t seq=prefs_.getULong64("request_seq",0)+1;prefs_.putULong64("request_seq",seq);
  return hardwareId_+"-"+operation+"-"+String((unsigned long)seq);
}
void MGroupV2Runtime::setRuntimeStatus(const String& status,const String& detail) {
  runtimeStatus_=status;runtimeDetail_=detail;
}
