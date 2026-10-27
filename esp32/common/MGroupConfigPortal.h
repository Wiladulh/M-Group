#pragma once
#include <Arduino.h>
#include <WiFi.h>
#include <Preferences.h>
#include <AsyncTCP.h>
#include <ESPAsyncWebServer.h>
#include <mbedtls/sha256.h>
class MGroupConfigPortal {
 public:
  void begin(String &wifiSsid,String &wifiPassword,String &baseUrl,String &deviceId,String &deviceKey,const char *deviceLabel,const char *storageNamespace,bool forceSetup) {
    ssid_=&wifiSsid; password_=&wifiPassword; url_=&baseUrl; id_=&deviceId; key_=&deviceKey; label_=deviceLabel;
    prefs_.begin(storageNamespace,false);
    cashierMode_=String(deviceLabel).indexOf("Cashier")>=0;
    if(cashierMode_&&!prefs_.isKey("webui_pin_hash"))prefs_.putString("webui_pin_hash","9171e6f9e69f02676755d9b255fc23c1e7fd9578446cc5fbceea501f20b91356");
    if(cashierMode_)sessionToken_=randomToken();
    *ssid_=prefs_.getString("wifi_ssid",*ssid_); *password_=prefs_.getString("wifi_pass",*password_);
    *url_=prefs_.getString("server_url",*url_); *id_=prefs_.getString("device_id",*id_); *key_=prefs_.getString("device_key",*key_);
    // Initialize the station interface before reading its hardware MAC.
    WiFi.mode(WIFI_STA);
    bool needed=forceSetup||ssid_->isEmpty()||password_->isEmpty()||url_->isEmpty()||id_->isEmpty()||key_->isEmpty()||*key_=="CHANGE_DEVICE_KEY"||*ssid_=="CHANGE_ME";
    startPortal(needed);
  }
  bool active() const { return active_; }
 private:
  AsyncWebServer server_{80}; Preferences prefs_;
  String *ssid_=nullptr,*password_=nullptr,*url_=nullptr,*id_=nullptr,*key_=nullptr;
  const char *label_="M-Group Device"; bool active_=false,cashierMode_=false;
  String sessionToken_=""; unsigned long pinLockedUntil_=0,pinWindowStarted_=0; uint8_t pinFailures_=0;
  static String sha256Hex(const String &v){uint8_t d[32];mbedtls_sha256((const unsigned char*)v.c_str(),v.length(),d,0);char h[65];for(int i=0;i<32;i++)sprintf(h+i*2,"%02x",d[i]);h[64]=0;return String(h);}
  static String randomToken(){String t;for(int i=0;i<4;i++){char b[9];snprintf(b,sizeof(b),"%08lx",(unsigned long)esp_random());t+=b;}return t;}
  bool authorized(AsyncWebServerRequest *req){if(!cashierMode_)return true;if(!req->hasHeader("Cookie"))return false;return req->getHeader("Cookie")->value().indexOf(String("mg_session=")+sessionToken_)>=0;}
  static String loginPage(){return String(F("<!doctype html><html lang=\"id\"><meta name=\"viewport\" content=\"width=device-width,initial-scale=1\"><title>PIN WebUI Cashier</title><body style=\"font:16px system-ui;max-width:440px;margin:10vh auto;padding:20px;background:#f3f5f7\"><h2>WebUI Cashier</h2><p>Masukkan PIN konfigurasi.</p><form method=\"post\" action=\"/login\"><input name=\"pin\" type=\"password\" maxlength=\"32\" required style=\"padding:12px;width:95%\"><button style=\"padding:12px;margin-top:12px\">Masuk</button></form><p>PIN awal: 19929900. Ganti setelah login.</p></body></html>"));}
  void requireAuth(AsyncWebServerRequest *req){req->send(401,"application/json","{\"ok\":false,\"detail\":\"login_required\"}");}
  static String page(const char *label) {
    String h=R"HTML(<!doctype html><html lang="id"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>Konfigurasi M-Group</title><style>
body{font:16px system-ui;background:#f3f5f7;color:#17202a;margin:0;padding:20px}
main{max-width:520px;margin:auto;background:white;padding:22px;border-radius:14px;box-shadow:0 4px 18px #0001}
label{display:block;font-weight:600;margin:14px 0 5px}input{box-sizing:border-box;width:100%;padding:12px;border:1px solid #bbc4cc;border-radius:8px;font:inherit}
button{margin-top:20px;width:100%;padding:13px;background:#175cd3;color:white;border:0;border-radius:8px;font:inherit;font-weight:700}
small{color:#52606d}.warn{background:#fff7e6;padding:10px;border-radius:8px}
</style><main><h2>Konfigurasi )HTML";
    h+=label;
    h+=R"HTML(</h2><p>Masukkan Wi-Fi, alamat server, dan Device Key dari Dashboard Management M-Group.</p>
<p class="warn">Masukkan Device ID dan Device Key yang dibuat server saat perangkat diprovisikan. Jangan menggunakan ID dari perangkat lain.</p><section><h3>Status perangkat</h3><pre id="status">Memuat status...</pre><button type="button" onclick="fetch('/test').then(r=>r.json()).then(x=>alert(x.detail+' ('+x.host+':'+x.port+')')).catch(()=>alert('Uji koneksi gagal'))">Uji koneksi server</button></section>
<form method="post" action="/save">
<label>Wi-Fi SSID</label><input name="ssid" maxlength="64" required autocomplete="off">
<label>Password Wi-Fi</label><input name="wifi_password" type="password" maxlength="128" required>
<label>URL server M-Group</label><input name="server_url" type="url" placeholder="http://192.168.1.10:8011" maxlength="160" required>\n<label>Device ID dari server</label><input name="device_id" maxlength="64" required autocomplete="off">
<label>Device Key</label><input name="device_key" type="password" maxlength="128" required autocomplete="off">
<small>Gunakan key aktif perangkat. Jangan gunakan key admin.</small><button type="submit">Simpan dan restart</button></form><script>fetch('/status').then(r=>r.json()).then(s=>document.getElementById('status').textContent='Device ID: '+s.device_id+'\\nIP DHCP: '+s.ip+'\\nWi-Fi: '+(s.wifi_connected?'Terhubung':'Terputus')+'\\nRSSI: '+s.rssi+' dBm\\nServer: '+s.server_url+'\\nDevice key: '+(s.device_key_configured?'Tersimpan':'Belum diatur')).catch(()=>document.getElementById('status').textContent='Status belum tersedia');</script></main></html>)HTML";
    return h;
  }
  void startPortal(bool setupAp=true) {
    if(setupAp) {
      WiFi.mode(WIFI_AP_STA);
      uint64_t mac=ESP.getEfuseMac(); char suffix[7]; snprintf(suffix,sizeof(suffix),"%06X",(uint32_t)(mac&0xFFFFFF));
      String apName=String("MGroup-Setup-")+suffix; char pass[17]; snprintf(pass,sizeof(pass),"%08X%08X",(uint32_t)esp_random(),(uint32_t)esp_random());
      WiFi.softAP(apName.c_str(),pass); active_=true;
      Serial.printf("\nM-GROUP CONFIG PORTAL: %s\nPassword setup: %s\nBuka http://192.168.4.1/\n",apName.c_str(),pass);
    } else {
      active_=false;
      Serial.println("M-GROUP DEVICE WEBUI will be available at the DHCP IP on port 80 after Wi-Fi connects.");
    }
    server_.on("/",HTTP_GET,[this](AsyncWebServerRequest *req){req->send(200,"text/html; charset=utf-8",page(label_));});
    server_.on("/status",HTTP_GET,[this](AsyncWebServerRequest *req){
      String body="{\"device_type\":\""+String(label_)+"\",\"device_id\":\""+*id_+"\",\"wifi_connected\":"+String(WiFi.status()==WL_CONNECTED?"true":"false")+",\"ip\":\""+WiFi.localIP().toString()+"\",\"rssi\":"+String(WiFi.status()==WL_CONNECTED?WiFi.RSSI():0)+",\"server_url\":\""+*url_+"\",\"device_key_configured\":"+String(key_&&!key_->isEmpty()?"true":"false")+"}";
      req->send(200,"application/json; charset=utf-8",body);
    });
    server_.on("/test",HTTP_GET,[this](AsyncWebServerRequest *req){
      if(WiFi.status()!=WL_CONNECTED){req->send(503,"application/json","{\"ok\":false,\"detail\":\"wifi_disconnected\"}");return;}
      String host=*url_; host.replace("https://","");host.replace("http://","");int slash=host.indexOf('/');if(slash>=0)host=host.substring(0,slash);
      uint16_t port=url_->startsWith("https://")?443:80;int colon=host.lastIndexOf(':');if(colon>0){port=(uint16_t)host.substring(colon+1).toInt();host=host.substring(0,colon);}
      WiFiClient client;client.setTimeout(3000);bool ok=client.connect(host.c_str(),port);if(ok)client.stop();
      String body=String("{\"ok\":")+(ok?"true":"false")+",\"detail\":\""+(ok?"tcp_reachable":"server_unreachable")+"\",\"host\":\""+host+"\",\"port\":"+String(port)+"}";
      req->send(ok?200:503,"application/json; charset=utf-8",body);
    });
    server_.on("/save",HTTP_POST,[this](AsyncWebServerRequest *req){
      auto value=[req](const char *name)->String {return req->hasParam(name,true)?req->getParam(name,true)->value():"";};
      String ssid=value("ssid"),wifiPass=value("wifi_password"),serverUrl=value("server_url"),deviceId=value("device_id"),deviceKey=value("device_key");
      ssid.trim();serverUrl.trim();deviceKey.trim();
      if(ssid.isEmpty()||wifiPass.isEmpty()||deviceId.isEmpty()||deviceKey.isEmpty()||ssid.length()>64||wifiPass.length()>128||deviceId.length()>64||serverUrl.length()>160||deviceKey.length()>128||!(serverUrl.startsWith("http://")||serverUrl.startsWith("https://"))||serverUrl.endsWith("/")) {
        req->send(400,"text/plain; charset=utf-8","Konfigurasi tidak valid. Periksa semua kolom dan URL tanpa slash akhir.");return;
      }
      prefs_.putString("wifi_ssid",ssid);prefs_.putString("wifi_pass",wifiPass);prefs_.putString("server_url",serverUrl);prefs_.putString("device_id",deviceId);prefs_.putString("device_key",deviceKey);
      req->send(200,"text/html; charset=utf-8","<!doctype html><meta name='viewport' content='width=device-width'><h2>Konfigurasi tersimpan</h2><p>Perangkat akan restart.</p>");
      delay(900);ESP.restart();
    });
    server_.onNotFound([](AsyncWebServerRequest *req){req->send(404,"text/plain","Not found");});server_.begin();
  }
};
