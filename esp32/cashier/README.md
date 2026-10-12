# NVM ESP32 Cashier — NFC + PIN + LCD + Keypad

## Cashier payment flow (CSH-04)

1. Petugas memasukkan nominal dengan keypad 4x4 (# konfirmasi, * hapus).
2. Pembeli menempelkan kartu NFC dan memasukkan PIN (ditampilkan sebagai *).
3. ESP32 mengirim credential, nominal, PIN, dan idempotency key ke `/api/v1/cashier/payments`.
4. Server memverifikasi device authorization, credential, PIN, dan saldo; server menjadi satu-satunya pihak yang mendebit Ledger.
5. ESP32 menampilkan hasil server. Saldo tidak disimpan atau dihitung sebagai sumber kebenaran lokal.

### Idempotency and uncertain outcomes

- Payment sequence is persisted in ESP32 NVS so an ordinary reboot does not reuse earlier idempotency keys.
- Before sending a payment, firmware stores only the pending credential, amount, and sequence in NVS. The member PIN is never persisted.
- On transport timeout or HTTP 5xx, firmware retries the exact request with the same idempotency key.
- If the outcome remains uncertain, the cashier blocks new payments and asks for the PIN again to retry the same transaction. This allows the server to return the original transaction if it was already processed.
- A definitive HTTP response clears the pending request. Do not erase the device NVS while a payment is pending; reconcile with the server first.

## CSH-06 operator and member feedback

- LCD shows reader readiness, card detection, payment progress, pending outcome, and payment result/error.
- Keypad input accepts digits, uses `*` to delete the last digit, and `#` to confirm. PIN characters are masked on LCD.
- Serial logs identify the reader, payment start, and input confirmation without logging the PIN.
- A buzzer is intentionally deferred. Validate display readability and keypad behavior on the physical hardware.

## CSH-05 network and error handling

- Wi-Fi reconnect attempts are bounded; the firmware remains responsive to later retries instead of waiting forever during startup or payment.
- HTTP connect/read timeouts are set for GET and POST requests. Registration polling is skipped while offline; heartbeat reports the offline state to Serial rather than attempting an HTTP request without Wi-Fi.
- NFC reader initialization failure is reported on Serial and LCD instead of silently ignoring payment attempts.
- Payment errors show distinct messages for invalid PIN/authorization, missing device/API, invalid request data, rate limiting, insufficient balance, and rejected transactions.
- Transport failures and HTTP 5xx keep the transaction pending; the firmware must reuse the same idempotency key and must not accept a new payment until the result is reconciled.
- Network recovery and the exact behavior of the physical reader still require on-device testing. Never treat a timeout as proof that a payment failed.

## CSH-03 NFC reader abstraction

Application code uses `NvmCardReader`, not concrete PN532/MFRC522 APIs.

- Tries PN532 over I2C first, then falls back to RC522 over SPI.
- Reports the active reader with `name()` and `type`.
- Supports UID lengths up to 10 bytes using `NVM_MAX_UID_LENGTH`.
- Physical card-present/removal behavior still requires testing on the selected reader.

## Hardware and wiring

- ESP32, LCD 16x2 I2C (default address 0x27), keypad matrix 4x4.
- LCD: SDA 21, SCL 22.
- PN532: SDA 21, SCL 22, IRQ 39, RESET 5.
- RC522: SCK 18, MISO 19, MOSI 23, SS/SDA 27, RST 4.
- Keypad rows: 32,33,25,26. Columns: 13,14,16,17.

GPIO39 is input-only and has no internal pull-up; ensure the PN532 board provides any required IRQ bias. Power reader modules at their supported voltage (RC522 is typically 3.3 V). Do not allow an LCD I2C backpack to pull ESP32 SDA/SCL directly to 5 V.

Libraries: LiquidCrystal_I2C, Keypad, Adafruit PN532, MFRC522.

## Server configuration

Set `WIFI_SSID`, `WIFI_PASSWORD`, `NVM_BASE_URL`, `DEVICE_ID`, and `NVM_DEVICE_KEY` in `NvmCashier.ino`.

- `NVM_BASE_URL` must be the NVM server's reachable LAN address, for example `http://192.168.1.10:8011`; replace the example IP and do not add a trailing slash.
- NVM defaults to `NVM_HOST=127.0.0.1`, which is loopback-only. For LAN device access, start the server with `NVM_HOST=0.0.0.0 NVM_PORT=8011` (or bind to the server's LAN interface) and allow TCP 8011 only from the trusted LAN in the firewall.
- Provision the device using the exact `DEVICE_ID` and paste the returned key into `NVM_DEVICE_KEY`. The key must be active in the server registry.
- Configure the operator top-up PIN through the authenticated NVM API/WebUI. Set the member PIN and ensure the NFC credential is active and linked to an active member with an active savings account.

The firmware persists top-up idempotency sequence and pending transaction metadata. If a request times out, it blocks new top-ups and asks the operator/member to retry the same transaction; PINs are never saved in NVS.


## CSH-07 offline integration test

Automated CI covers the server-side recovery case where a payment is committed but the response is lost: replaying the same idempotency key must return the original transaction, with one payment record and one ledger debit. A firmware contract test checks that a disconnected/ambiguous request stays pending in NVS and that the PIN is not persisted.

Physical offline test checklist (after flashing the built firmware):

1. Confirm the cashier is registered and can complete one normal NFC payment.
2. Disconnect Wi-Fi or stop the NVM server, then start a payment attempt. The LCD must not show success; an uncertain result must show `HASIL BELUM ADA` / `Ulangi PIN`.
3. Restore Wi-Fi/server. Enter the PIN to retry the pending payment. Do not clear NVS or start a different payment while pending.
4. Check server ledger and payment history: one original transaction/debit only. Repeat only with a new test credential/account or a safely funded test account.
5. Record LCD/Serial behavior and server transaction ID. CI cannot substitute for this physical network interruption test.

**CSH-07 status:** automated integration checks are added; mark full offline integration PASS only after GitHub CI is green and the physical interruption/recovery test has been completed.


## CSH-08 hardware validation

CSH-08 is a **physical-device validation** stage; CI can verify the pin-map and reader abstraction contracts, but cannot certify wiring or card behavior. Run this checklist on the actual ESP32 DevKit and the selected peripherals:

1. **Power and wiring:** common GND; ESP32 and RC522 at 3.3 V; LCD I2C pull-ups must not expose SDA/SCL to 5 V. Verify every pin against the table above before powering.
2. **Boot and Wi-Fi:** flash the successful `ESP32 Cashier Build` artifact, configure Wi-Fi/server/device key, restart, and confirm an IP plus a successful heartbeat in Serial.
3. **LCD:** confirm both rows are readable at boot, during keypad entry, while checking a card, during payment, and for success/error states.
4. **Keypad:** test every digit, `*` backspace, and `#` confirmation. Confirm PIN entry displays asterisks only. Do not use a real member PIN for screenshots/log capture.
5. **RC522:** tap a test card several times, remove it between taps, and confirm stable UID detection. If PN532 is connected instead, verify Serial reports `PN532`; the abstraction selects PN532 before falling back to RC522.
6. **Payment end-to-end:** use a test member, test NFC credential, known PIN, and safely funded test savings account. Confirm the server reports one transaction and one ledger debit, while the LCD reports the server result.
7. **Negative checks:** test unknown card, wrong PIN, insufficient test balance, reader disconnected at boot, and Wi-Fi unavailable. No unsuccessful or uncertain payment may be shown as successful.
8. **Reboot/pending safety:** if a payment is pending, reboot without erasing NVS and confirm the firmware continues to require reconciliation of that same transaction before allowing a new payment.

Record board model, reader model, LCD address, firmware commit, results, and any wiring changes. Never publish Wi-Fi credentials, device keys, PINs, or full sensitive logs.

**CSH-08 PASS criteria:** the above applicable checks pass on the physical device and the CI hardware-contract tests plus firmware build are green. Until then, hardware validation remains pending; do not proceed to vending integration.


## Installation and wiring tutorial

See [INSTALLATION_AND_WIRING.md](INSTALLATION_AND_WIRING.md) for the full step-by-step installation, pin mapping, power-safety notes, and physical test checklist.
