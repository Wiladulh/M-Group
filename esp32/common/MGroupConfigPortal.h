#pragma once
#include <Arduino.h>
#include <WiFi.h>
#include <Preferences.h>
#include <AsyncTCP.h>
#include <ESPAsyncWebServer.h>
class MGroupConfigPortal {
 public:
  void begin(String &wifiSsid,String &wifiPassword,String &baseUrl,String &deviceId,String &deviceKey,const char *deviceLabel,const char *storageNamespace,bool forceSetup) {
    ssid_=&wifiSsid; password_=&wifiPassword; url_=&baseUrl; id_=&deviceId; key_=&deviceKey; label_=deviceLabel;
    prefs_.begin(storageNamespace,false);
    *ssid_=prefs_.getString("wifi_ssid",*ssid_); *password_=prefs_.getString("wifi_pass",*password_);
    *url_=prefs_.getString("server_url",*url_); *key_=prefs_.getString("device_key",*key_);
    // Initialize the station interface before reading its hardware MAC.
    WiFi.mode(WIFI_STA);
    const bool vending=String(label_).startsWith("Vending");
    *id_=vending?prefs_.getString("machine_id",""):"";
    bool needed=forceSetup||ssid_->isEmpty()||password_->isEmpty()||url_->isEmpty()||key_->isEmpty()||*key_=="CHANGE_DEVICE_KEY"||*ssid_=="CHANGE_ME"||(vending&&id_->isEmpty());
    if(needed) startPortal();
  }
  bool active() const { return active_; }
 private:
  AsyncWebServer server_{80}; Preferences prefs_;
  String *ssid_=nullptr,*password_=nullptr,*url_=nullptr,*id_=nullptr,*key_=nullptr;
  const char *label_="M-Group Device"; bool active_=false;
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
<p class="warn">Server mengautentikasi perangkat menggunakan Device Key. Untuk Vending, masukkan Machine ID yang sudah dibuat di dashboard; MAC address tidak digunakan sebagai identitas.</p>
<form method="post" action="/save">
<label>Wi-Fi SSID</label><input name="ssid" maxlength="64" required autocomplete="off">
<label>Password Wi-Fi</label><input name="wifi_password" type="password" maxlength="128" required>
<label>URL server M-Group</label><input name="server_url" type="url" placeholder="http://192.168.1.10:8011" maxlength="160" required>
<label>Machine ID (khusus Vending)</label><input name="machine_id" maxlength="128" autocomplete="off" placeholder="Contoh: vending-01"><label>Device Key</label><input name="device_key" type="password" maxlength="128" required autocomplete="off">
<small>Gunakan key aktif perangkat. Jangan gunakan key admin.</small><button type="submit">Simpan dan restart</button></form></main></html>)HTML";
    return h;
  }
  void startPortal() {
    WiFi.mode(WIFI_AP_STA);
    uint64_t mac=ESP.getEfuseMac(); char suffix[7]; snprintf(suffix,sizeof(suffix),"%06X",(uint32_t)(mac&0xFFFFFF));
    String apName=String("MGroup-Setup-")+suffix; char pass[17]; snprintf(pass,sizeof(pass),"%08X%08X",(uint32_t)esp_random(),(uint32_t)esp_random());
    WiFi.softAP(apName.c_str(),pass); active_=true;
    Serial.printf("\nM-GROUP CONFIG PORTAL: %s\nPassword setup: %s\nBuka http://192.168.4.1/\n",apName.c_str(),pass);
    server_.on("/",HTTP_GET,[this](AsyncWebServerRequest *req){req->send(200,"text/html; charset=utf-8",page(label_));});
    server_.on("/save",HTTP_POST,[this](AsyncWebServerRequest *req){
      auto value=[req](const char *name)->String {return req->hasParam(name,true)?req->getParam(name,true)->value():"";};
      String ssid=value("ssid"),wifiPass=value("wifi_password"),serverUrl=value("server_url"),deviceKey=value("device_key"),machineId=value("machine_id");
      ssid.trim();serverUrl.trim();deviceKey.trim();machineId.trim();
      if(ssid.isEmpty()||wifiPass.isEmpty()||deviceKey.isEmpty()||(String(label_).startsWith("Vending")&&machineId.isEmpty())||ssid.length()>64||wifiPass.length()>128||serverUrl.length()>160||deviceKey.length()>128||machineId.length()>128||!(serverUrl.startsWith("http://")||serverUrl.startsWith("https://"))||serverUrl.endsWith("/")) {
        req->send(400,"text/plain; charset=utf-8","Konfigurasi tidak valid. Periksa semua kolom dan URL tanpa slash akhir.");return;
      }
      prefs_.putString("wifi_ssid",ssid);prefs_.putString("wifi_pass",wifiPass);prefs_.putString("server_url",serverUrl);prefs_.putString("device_key",deviceKey);if(String(label_).startsWith("Vending"))prefs_.putString("machine_id",machineId);
      req->send(200,"text/html; charset=utf-8","<!doctype html><meta name='viewport' content='width=device-width'><h2>Konfigurasi tersimpan</h2><p>Perangkat akan restart.</p>");
      delay(900);ESP.restart();
    });
    server_.onNotFound([](AsyncWebServerRequest *req){req->send(404,"text/plain","Not found");});server_.begin();
  }
};
