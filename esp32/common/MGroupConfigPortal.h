#pragma once
#include <Arduino.h>
#include <WiFi.h>
#include <time.h>
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
  void setStatusExtra(const String &jsonFields){statusExtra_=jsonFields;}
  String tlsCaCertificate() {return prefs_.getString("tls_ca","");}
 private:
  AsyncWebServer server_{80}; Preferences prefs_;
  String *ssid_=nullptr,*password_=nullptr,*url_=nullptr,*id_=nullptr,*key_=nullptr;
  const char *label_="M-Group Device"; bool active_=false,cashierMode_=false;
  String sessionToken_="",statusExtra_=""; unsigned long sessionExpiresAt_=0,pinLockedUntil_=0,pinWindowStarted_=0; uint8_t pinFailures_=0;
  static String sha256Hex(const String &v){uint8_t d[32];mbedtls_sha256((const unsigned char*)v.c_str(),v.length(),d,0);char h[65];for(int i=0;i<32;i++)sprintf(h+i*2,"%02x",d[i]);h[64]=0;return String(h);}
  static String randomToken(){String t;for(int i=0;i<4;i++){char b[9];snprintf(b,sizeof(b),"%08lx",(unsigned long)esp_random());t+=b;}return t;}
  bool authorized(AsyncWebServerRequest *req){if(!cashierMode_)return true;if(!sessionExpiresAt_||(long)(millis()-sessionExpiresAt_)>=0||!req->hasHeader("Cookie"))return false;return req->getHeader("Cookie")->value().indexOf(String("mg_session=")+sessionToken_)>=0;}
  bool defaultPinActive(){return cashierMode_&&prefs_.getString("webui_pin_hash","9171e6f9e69f02676755d9b255fc23c1e7fd9578446cc5fbceea501f20b91356")=="9171e6f9e69f02676755d9b255fc23c1e7fd9578446cc5fbceea501f20b91356";}
  static String loginPage(){return String(F("<!doctype html><html lang=\"id\"><meta name=\"viewport\" content=\"width=device-width,initial-scale=1\"><title>PIN WebUI Cashier</title><body style=\"font:16px system-ui;max-width:440px;margin:10vh auto;padding:20px;background:#f3f5f7\"><h2>WebUI Cashier</h2><p>Masukkan PIN konfigurasi.</p><form method=\"post\" action=\"/login\"><input name=\"pin\" type=\"password\" maxlength=\"32\" required style=\"padding:12px;width:95%\"><button style=\"padding:12px;margin-top:12px\">Masuk</button></form><p>PIN awal: 19929900. Ganti setelah login.</p></body></html>"));}
  void requireAuth(AsyncWebServerRequest *req){req->send(401,"application/json","{\"ok\":false,\"detail\":\"login_required\"}");}
  String page(const char *label) {
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
<label>URL server M-Group</label><input name="server_url" type="url" placeholder="http://192.168.1.10:8011" maxlength="160" required>\n<label>Sertifikat CA server (wajib untuk HTTPS)</label><textarea name="tls_ca" maxlength="4096" rows="5" style="box-sizing:border-box;width:100%;font:12px monospace" placeholder="-----BEGIN CERTIFICATE----- ..."></textarea><small>HTTPS tanpa CA yang valid akan ditolak; jangan gunakan mode insecure.</small>\n<label>Device ID dari server</label><input name="device_id" maxlength="64" required autocomplete="off">
<label>Device Key</label><input name="device_key" type="password" maxlength="128" required autocomplete="off">
<small>Gunakan key aktif perangkat. Jangan gunakan key admin.</small><button type="submit">Simpan dan restart</button></form><script>fetch('/status').then(r=>r.json()).then(s=>document.getElementById('status').textContent='Device ID: '+s.device_id+'\\nIP DHCP: '+s.ip+'\\nWaktu lokal WIB: '+s.local_time+'\\nWi-Fi: '+(s.wifi_connected?'Terhubung':'Terputus')+'\\nRSSI: '+s.rssi+' dBm\\nServer: '+s.server_url+'\\nDevice key: '+(s.device_key_configured?'Tersimpan':'Belum diatur')+'\\nTLS CA: '+(s.tls_ca_configured?'Tersimpan':'Belum diatur')+(s.catalog_sync_status?'\\nSinkron katalog: '+s.catalog_sync_status:'')+(s.catalog_hash?'\\nHash katalog: '+s.catalog_hash:'')+(s.catalog_sync_at?'\\nSinkron terakhir WIB: '+new Date(s.catalog_sync_at*1000).toLocaleString('id-ID',{timeZone:'Asia/Jakarta'}):'')+(s.catalog_sync_error?'\\nError sinkron: '+s.catalog_sync_error:'')+(s.registration_status?'\\nStatus NFC: '+s.registration_status:'')).catch(()=>document.getElementById('status').textContent='Status belum tersedia');</script></main></html>)HTML";
    if(String(label).indexOf("Cashier")>=0){
      if(defaultPinActive()){String heading=String("<h2>Konfigurasi ")+label+"</h2>";h.replace(heading.c_str(),heading+"<p class=\"warn\">PIN masih default 19929900. Ganti PIN sebelum menyimpan konfigurasi.</p>");}
      String pinForm=R"HTML(<hr><h3>Keamanan WebUI Cashier</h3><form method="post" action="/change-pin"><label>PIN saat ini</label><input name="old_pin" type="password" maxlength="32" required><label>PIN baru (minimal 8 karakter)</label><input name="new_pin" type="password" minlength="8" maxlength="32" required><label>Ulangi PIN baru</label><input name="confirm_pin" type="password" minlength="8" maxlength="32" required><button type="submit">Ganti PIN WebUI</button></form>)HTML";
      h.replace("</main></html>",pinForm+"</main></html>");
    }
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
    server_.on("/",HTTP_GET,[this](AsyncWebServerRequest *req){if(cashierMode_&&!authorized(req)){req->send(200,"text/html; charset=utf-8",loginPage());return;}req->send(200,"text/html; charset=utf-8",page(label_));});
    server_.on("/login",HTTP_POST,[this](AsyncWebServerRequest *req){
      if(!cashierMode_){req->redirect("/");return;}
      if(millis()<pinLockedUntil_){req->send(429,"text/plain","Terlalu banyak percobaan. Coba lagi 15 menit.");return;}
      String pin=req->hasParam("pin",true)?req->getParam("pin",true)->value():"";String expected=prefs_.getString("webui_pin_hash","9171e6f9e69f02676755d9b255fc23c1e7fd9578446cc5fbceea501f20b91356");
      if(pin.length()<4||sha256Hex(pin)!=expected){if(pinWindowStarted_==0||millis()-pinWindowStarted_>900000UL){pinWindowStarted_=millis();pinFailures_=0;}if(++pinFailures_>=5){pinLockedUntil_=millis()+900000UL;pinFailures_=0;pinWindowStarted_=0;}req->send(401,"text/html; charset=utf-8",loginPage()+"<p>PIN salah atau percobaan dibatasi.</p>");return;}
      pinFailures_=0;pinWindowStarted_=0;sessionToken_=randomToken();sessionExpiresAt_=millis()+1800000UL;auto *response=req->beginResponse(303,"text/plain","Login berhasil.");response->addHeader("Location","/");response->addHeader("Set-Cookie",String("mg_session=")+sessionToken_+"; HttpOnly; SameSite=Strict; Path=/; Max-Age=1800");req->send(response);
    });
    server_.on("/status",HTTP_GET,[this](AsyncWebServerRequest *req){if(!authorized(req)){requireAuth(req);return;}
      time_t now=time(nullptr);struct tm localInfo;char localTime[24]="Belum sinkron";if(now>1700000000&&localtime_r(&now,&localInfo))strftime(localTime,sizeof(localTime),"%Y-%m-%d %H:%M:%S",&localInfo);
      String body="{\"device_type\":\""+String(label_)+"\",\"device_id\":\""+*id_+"\",\"local_time\":\""+String(localTime)+"\",\"wifi_connected\":"+String(WiFi.status()==WL_CONNECTED?"true":"false")+",\"ip\":\""+WiFi.localIP().toString()+"\",\"rssi\":"+String(WiFi.status()==WL_CONNECTED?WiFi.RSSI():0)+",\"server_url\":\""+*url_+"\",\"device_key_configured\":"+String(key_&&!key_->isEmpty()?"true":"false")+",\"tls_ca_configured\":"+String(!prefs_.getString("tls_ca","").isEmpty()?"true":"false")+statusExtra_+"}";
      req->send(200,"application/json; charset=utf-8",body);
    });
    server_.on("/test",HTTP_GET,[this](AsyncWebServerRequest *req){if(!authorized(req)){requireAuth(req);return;}
      if(WiFi.status()!=WL_CONNECTED){req->send(503,"application/json","{\"ok\":false,\"detail\":\"wifi_disconnected\"}");return;}
      String host=*url_; host.replace("https://","");host.replace("http://","");int slash=host.indexOf('/');if(slash>=0)host=host.substring(0,slash);
      uint16_t port=url_->startsWith("https://")?443:80;int colon=host.lastIndexOf(':');if(colon>0){port=(uint16_t)host.substring(colon+1).toInt();host=host.substring(0,colon);}
      WiFiClient client;client.setTimeout(3000);bool ok=client.connect(host.c_str(),port);if(ok)client.stop();
      String body=String("{\"ok\":")+(ok?"true":"false")+",\"detail\":\""+(ok?"tcp_reachable":"server_unreachable")+"\",\"host\":\""+host+"\",\"port\":"+String(port)+"}";
      req->send(ok?200:503,"application/json; charset=utf-8",body);
    });
    server_.on("/save",HTTP_POST,[this](AsyncWebServerRequest *req){if(!authorized(req)){requireAuth(req);return;}if(defaultPinActive()){req->send(403,"text/plain","Ganti PIN default 19929900 sebelum menyimpan konfigurasi perangkat.");return;}
      auto value=[req](const char *name)->String {return req->hasParam(name,true)?req->getParam(name,true)->value():"";};
      String ssid=value("ssid"),wifiPass=value("wifi_password"),serverUrl=value("server_url"),deviceId=value("device_id"),deviceKey=value("device_key"),tlsCa=value("tls_ca");
      ssid.trim();serverUrl.trim();deviceKey.trim();
      if(ssid.isEmpty()||wifiPass.isEmpty()||deviceId.isEmpty()||deviceKey.isEmpty()||ssid.length()>64||wifiPass.length()>128||deviceId.length()>64||serverUrl.length()>160||deviceKey.length()>128||tlsCa.length()>4096||!(serverUrl.startsWith("http://")||serverUrl.startsWith("https://"))||serverUrl.endsWith("/")) {
        req->send(400,"text/plain; charset=utf-8","Konfigurasi tidak valid. Periksa semua kolom dan URL tanpa slash akhir.");return;
      }
      prefs_.putString("wifi_ssid",ssid);prefs_.putString("wifi_pass",wifiPass);prefs_.putString("server_url",serverUrl);prefs_.putString("device_id",deviceId);prefs_.putString("device_key",deviceKey);prefs_.putString("tls_ca",tlsCa);
      req->send(200,"text/html; charset=utf-8","<!doctype html><meta name='viewport' content='width=device-width'><h2>Konfigurasi tersimpan</h2><p>Perangkat akan restart.</p>");
      delay(900);ESP.restart();
    });
    server_.on("/change-pin",HTTP_POST,[this](AsyncWebServerRequest *req){
      if(!cashierMode_){req->send(404,"text/plain","Not found");return;}if(!authorized(req)){requireAuth(req);return;}
      auto value=[req](const char *name)->String{return req->hasParam(name,true)?req->getParam(name,true)->value():"";};String oldPin=value("old_pin"),newPin=value("new_pin"),confirm=value("confirm_pin");
      if(sha256Hex(oldPin)!=prefs_.getString("webui_pin_hash","9171e6f9e69f02676755d9b255fc23c1e7fd9578446cc5fbceea501f20b91356")){req->send(403,"text/plain","PIN saat ini salah.");return;}
      if(newPin.length()<8||newPin.length()>32||newPin!=confirm||newPin=="19929900"){req->send(400,"text/plain","PIN baru harus 8-32 karakter, cocok dengan konfirmasi, dan bukan PIN default.");return;}
      prefs_.putString("webui_pin_hash",sha256Hex(newPin));req->send(200,"text/html; charset=utf-8","<!doctype html><meta name='viewport' content='width=device-width'><h2>PIN berhasil diganti</h2><p>Silakan kembali ke WebUI.</p><a href='/'>Kembali</a>");
    });
    server_.onNotFound([this](AsyncWebServerRequest *req){if(!authorized(req)){requireAuth(req);return;}req->send(404,"text/plain","Not found");});server_.begin();
  }
};
