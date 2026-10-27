#pragma once
#include <Arduino.h>
#include <Preferences.h>
#include <WebServer.h>

class MGroupV2Runtime {
 public:
  void begin();
  void loop();
  bool apiGet(const String& path, String& response, int& status);
  bool apiPost(const String& path, const String& body, String& response, int& status);
  bool serverHealth();
  bool ensureRegistered();
  String hardwareId() const { return hardwareId_; }
  String registryId() const { return registryId_; }
  String serverUrl() const { return serverUrl_; }
  String macAddress() const { return macAddress_; }
  bool wifiConnected() const;
  Preferences& prefs() { return prefs_; }
  String nextRequestId(const String& operation);
  void setRuntimeStatus(const String& status, const String& detail = "");
  String runtimeStatus() const { return runtimeStatus_; }
  String runtimeDetail() const { return runtimeDetail_; }
 private:
  Preferences prefs_;
  WebServer server_{80};
  String ssid_, wifiPassword_, serverUrl_, deviceKey_, tlsCa_;
  String hardwareId_, registryId_, macAddress_;
  String webPinSalt_, webPinHash_, sessionToken_;
  String runtimeStatus_="booting", runtimeDetail_="";
  unsigned long sessionExpiresAt_=0;
  uint8_t pinFailures_=0;
  unsigned long pinLockUntil_=0;
  bool apMode_=false, serverStarted_=false;
  String randomToken(size_t bytes=24);
  String sha256Hex(const String& value);
  void loadConfiguration();
  void connectNetwork();
  void startWebUI();
  bool authorized();
  bool pinMatches(const String& pin);
  void storeWebPin(const String& pin);
  String loginPage();
  String configPage();
  String statusJson();
  int requestHttp(const String& method, const String& path, const String& body, String& response, bool withDeviceKey);
};
extern MGroupV2Runtime mgroup;
