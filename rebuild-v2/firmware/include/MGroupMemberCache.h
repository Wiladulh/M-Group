#pragma once
#include <Arduino.h>
#include <Preferences.h>
#include <ArduinoJson.h>
#include <time.h>
#include <limits.h>
#include <mbedtls/sha256.h>

// Last-known balance cache only. It never authorizes offline payments.
// Raw NFC UIDs, PINs, and full NIK values are never persisted.
// Each member snapshot is one Preferences value so it is replaced atomically.
namespace MGroupMemberCache {
struct Snapshot {
  String memberId;
  String displayName;
  String currency;
  String balanceVersion;
  String memberStatus;
  String accountStatus;
  String cardStatus;
  long balanceMinor = 0;
  unsigned long syncedAt = 0;
};

inline String cardReference(Preferences& prefs, const String& cardUid) {
  String salt=prefs.getString("mc_salt","");
  if(salt.isEmpty()) {
    for(uint8_t i=0;i<4;i++){char part[9];snprintf(part,sizeof(part),"%08lx",(unsigned long)esp_random());salt+=part;}
    prefs.putString("mc_salt",salt);
  }
  String input=salt+cardUid;
  uint8_t digest[32];
  mbedtls_sha256((const unsigned char*)input.c_str(), input.length(), digest, 0);
  char hex[65];
  for(int i=0;i<32;i++) snprintf(hex+i*2,3,"%02x",digest[i]);
  hex[64]='\\0';
  return String(hex);
}

inline String slotKey(uint8_t slot) {
  char key[6];
  snprintf(key,sizeof(key),"mc%02u",slot);
  return String(key);
}

inline bool readSlot(Preferences& prefs, uint8_t slot, JsonDocument& doc) {
  String raw=prefs.getString(slotKey(slot).c_str(),"");
  if(raw.isEmpty())return false;
  return deserializeJson(doc,raw)==DeserializationError::Ok;
}

inline void saveByReference(Preferences& prefs, const String& reference,
                            const String& memberId, const String& displayName,
                            long balanceMinor, const String& currency,
                            const String& balanceVersion, const String& memberStatus="active",
                            const String& accountStatus="active", const String& cardStatus="active") {
  if(reference.length()!=64 || memberId.isEmpty() || balanceMinor<0) return;
  int target=-1;
  unsigned long oldest=ULONG_MAX;
  uint8_t oldestSlot=0;
  for(uint8_t i=0;i<100;i++) {
    JsonDocument existing;
    if(readSlot(prefs,i,existing)) {
      String existingRef=existing["card_ref"]|String("");
      if(existingRef==reference) { target=i; break; }
      unsigned long at=existing["last_used_at"]|existing["synced_at"]|0UL;
      if(at<oldest) { oldest=at; oldestSlot=i; }
    } else if(target<0) target=i;
  }
  if(target<0) target=oldestSlot;
  JsonDocument record;
  record["card_ref"]=reference;
  record["member_id"]=memberId;
  record["display_name"]=displayName.substring(0,80);
  record["balance_minor"]=balanceMinor;
  record["currency"]=currency.substring(0,8);
  record["balance_version"]=balanceVersion.substring(0,32);
  record["member_status"]=memberStatus.substring(0,16);
  record["account_status"]=accountStatus.substring(0,16);
  record["card_status"]=cardStatus.substring(0,16);
  time_t now=time(nullptr);
  unsigned long stamp=now>1700000000?(unsigned long)now:millis()/1000UL;
  record["synced_at"]=stamp;
  record["last_used_at"]=stamp;
  String encoded;serializeJson(record,encoded);
  prefs.putString(slotKey(target).c_str(),encoded);
}

inline bool loadByReference(Preferences& prefs, const String& reference, Snapshot& out) {
  if(reference.length()!=64) return false;
  for(uint8_t i=0;i<100;i++) {
    JsonDocument record;
    if(!readSlot(prefs,i,record)||String(record["card_ref"]|String(""))!=reference)continue;
    out.memberId=record["member_id"]|String("");
    out.displayName=record["display_name"]|String("");
    out.balanceMinor=record["balance_minor"]|0L;
    out.currency=record["currency"]|String("IDR");
    out.balanceVersion=record["balance_version"]|String("");
    out.memberStatus=record["member_status"]|String("unknown");
    out.accountStatus=record["account_status"]|String("unknown");
    out.cardStatus=record["card_status"]|String("unknown");
    out.syncedAt=record["synced_at"]|0UL;
    time_t now=time(nullptr);
    record["last_used_at"]=now>1700000000?(unsigned long)now:millis()/1000UL;
    String encoded;serializeJson(record,encoded);
    prefs.putString(slotKey(i).c_str(),encoded);
    return !out.memberId.isEmpty();
  }
  return false;
}

inline bool isFresh(const Snapshot& snapshot, unsigned long maxAgeSeconds=300) {
  time_t now=time(nullptr);
  if(now<1700000000 || snapshot.syncedAt<1700000000)return false;
  return (unsigned long)now>=snapshot.syncedAt && (unsigned long)now-snapshot.syncedAt<=maxAgeSeconds;
}

inline bool loadForCard(Preferences& prefs, const String& cardUid, Snapshot& out) {
  return loadByReference(prefs,cardReference(prefs,cardUid),out);
}

inline void saveForCard(Preferences& prefs, const String& cardUid,
                        const String& memberId, const String& displayName,
                        long balanceMinor, const String& currency,
                        const String& balanceVersion, const String& memberStatus="active",
                        const String& accountStatus="active", const String& cardStatus="active") {
  saveByReference(prefs,cardReference(prefs,cardUid),memberId,displayName,balanceMinor,currency,balanceVersion,memberStatus,accountStatus,cardStatus);
}
}
