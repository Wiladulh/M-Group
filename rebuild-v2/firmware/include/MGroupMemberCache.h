#pragma once
#include <Arduino.h>
#include <Preferences.h>
#include <time.h>
#include <mbedtls/sha256.h>

// Last-known balance cache only. It never authorizes offline payments.
// Raw NFC UIDs, PINs, and full NIK values are never persisted.
namespace MGroupMemberCache {
struct Snapshot {
  String memberId;
  String displayName;
  String currency;
  String balanceVersion;
  long balanceMinor = 0;
  unsigned long syncedAt = 0;
};

inline String cardReference(const String& cardUid) {
  uint8_t digest[32];
  mbedtls_sha256((const unsigned char*)cardUid.c_str(), cardUid.length(), digest, 0);
  char hex[65];
  for (int i=0;i<32;i++) snprintf(hex+i*2,3,"%02x",digest[i]);
  hex[64]='\0';
  return String(hex);
}

inline String keyFor(uint8_t slot, const char* suffix) {
  char key[8];
  snprintf(key,sizeof(key),"m%02u%s",slot,suffix);
  return String(key);
}

inline void saveByReference(Preferences& prefs, const String& reference,
                            const String& memberId, const String& displayName,
                            long balanceMinor, const String& currency,
                            const String& balanceVersion) {
  if(reference.length()!=64 || memberId.isEmpty() || balanceMinor<0) return;
  int target=-1;
  unsigned long oldest=ULONG_MAX;
  uint8_t oldestSlot=0;
  for(uint8_t i=0;i<100;i++) {
    String hash=prefs.getString(keyFor(i,"h").c_str(),"");
    if(hash==reference) { target=i; break; }
    if(hash.isEmpty() && target<0) target=i;
    unsigned long at=prefs.getULong(keyFor(i,"at").c_str(),0);
    if(at<oldest) { oldest=at; oldestSlot=i; }
  }
  if(target<0) target=oldestSlot;
  prefs.putString(keyFor(target,"h").c_str(),reference);
  prefs.putString(keyFor(target,"id").c_str(),memberId);
  prefs.putString(keyFor(target,"nm").c_str(),displayName.substring(0,80));
  prefs.putLong(keyFor(target,"bal").c_str(),balanceMinor);
  prefs.putString(keyFor(target,"cur").c_str(),currency.substring(0,8));
  prefs.putString(keyFor(target,"ver").c_str(),balanceVersion.substring(0,32));
  time_t now=time(nullptr);
  prefs.putULong(keyFor(target,"at").c_str(),now>1700000000?(unsigned long)now:millis()/1000UL);
}

inline bool loadByReference(Preferences& prefs, const String& reference, Snapshot& out) {
  if(reference.length()!=64) return false;
  for(uint8_t i=0;i<100;i++) {
    if(prefs.getString(keyFor(i,"h").c_str(),"")!=reference) continue;
    out.memberId=prefs.getString(keyFor(i,"id").c_str(),"");
    out.displayName=prefs.getString(keyFor(i,"nm").c_str(),"");
    out.balanceMinor=prefs.getLong(keyFor(i,"bal").c_str(),0);
    out.currency=prefs.getString(keyFor(i,"cur").c_str(),"IDR");
    out.balanceVersion=prefs.getString(keyFor(i,"ver").c_str(),"");
    out.syncedAt=prefs.getULong(keyFor(i,"at").c_str(),0);
    return !out.memberId.isEmpty();
  }
  return false;
}

inline bool loadForCard(Preferences& prefs, const String& cardUid, Snapshot& out) {
  return loadByReference(prefs,cardReference(cardUid),out);
}

inline void saveForCard(Preferences& prefs, const String& cardUid,
                        const String& memberId, const String& displayName,
                        long balanceMinor, const String& currency,
                        const String& balanceVersion) {
  saveByReference(prefs,cardReference(cardUid),memberId,displayName,balanceMinor,currency,balanceVersion);
}
}
