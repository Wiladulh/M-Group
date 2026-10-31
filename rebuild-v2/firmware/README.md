# Clean-room v2 ESP32 firmware

This directory is the v2 firmware implementation. It targets only the /api/v2 contract and uses hardware_id generated from the ESP32 eFuse MAC. registry_id is assigned by the server after a provisioned Device Key is used for first-boot enrollment. No device_id alias is used.

## Environments

- pio run -e cashier: ESP32 DevKit, 0.96-inch SSD1306 OLED I2C, 4x4 keypad, and RC522 SPI only.
- pio run -e vending: ESP32-S3, SSD1306 OLED, UP/DOWN/SELECT buttons, PN532 I2C preferred with RC522 SPI fallback, five servo outputs, one shared IR break-beam sensor.

Firmware compilation is a required CI gate. Compilation does not replace physical acceptance testing; confirm the pinout against the actual board revision before flashing production hardware.

## First boot and local WebUI

1. Boot the device with no Wi-Fi credentials. The device creates MGroupV2-Setup-XXXX and prints the AP password and initial local WebUI PIN to Serial Monitor once. Never publish those values.
2. Connect to the setup AP and open http://192.168.4.1/, or use the DHCP IP shown on Serial Monitor once station Wi-Fi is connected.
3. Login with the local WebUI PIN. Set Wi-Fi, the server URL, Device Key from the v2 admin dashboard, and a trusted CA certificate when using HTTPS.
4. The device sends POST /api/v2/device/register with X-Device-Key, its generated hardware_id, and MAC address. The server binds that hardware identity to the provisioned registry row.
5. The WebUI is protected by a local PIN, has a short-lived HttpOnly cookie, rate-limits failed PIN attempts, and never renders the Device Key in status output. Rotate the local PIN after first login.

HTTP is only appropriate on a trusted isolated LAN. HTTPS is rejected unless a trusted CA certificate is configured; no insecure TLS fallback is used.

## Cashier workflow

- A: payment, enter amount, then tap the registered Member card. No PIN or top-up menu exists on Cashier.
- Top-up is performed only by Admin from the server WebUI.
- * removes the last digit; # confirms the current amount.
- NFC enrollment sessions created by the admin WebUI are polled from /api/v2/cashier/nfc-registration. The selected Cashier advances the server-side session and submits only the scanned card UID to the completion endpoint.
- Payment request_id and amount are persisted before submission. Raw card UID is never written to NVS or Serial. If a response is lost, the Member taps the card again to retry the exact request ID.

## Vending workflow

- UP/DOWN selects a fixed slot; SELECT begins a purchase only while a valid live server catalog is available.
- The registered Member card UID identifies the Member; no PIN entry is required.
- The server verifies expected_amount_minor against its current catalog price before debiting. QRIS is rejected until a provider integration is implemented.
- The firmware persists the request ID and amount before purchase submission. After the server creates a pending purchase, the transaction ID and dispensing stage are persisted before the servo moves.
- The IR sensor must observe a blocked-then-clear transition within four seconds. A failed dispense is reported to the server for atomic refund and stock restoration.
- If power is lost while the stage is dispensing, the servo is NOT replayed automatically. The transaction remains pending for manual review because the physical outcome is ambiguous. If the result report is pending, the same report is retried without actuating the servo again.
- A cached catalog is display-only while offline; payment remains disabled. Invalid server payloads do not replace the last-known-good cache.

## Pin map

### Cashier ESP32 DevKit
- SSD1306 OLED 0.96-inch I2C: SDA 21, SCL 22, address 0x3C.
- RC522 SPI only: SCK 18, MISO 19, MOSI 23, SS 27, RST 4.
- 4x4 keypad: rows 32, 33, 25, 26; columns 13, 14, 16, 17.

### Cashier flash layout

The Cashier target uses a dedicated 4 MiB single-factory-app partition table at `partitions/mgroup_cashier_4mb.csv`. The application partition is 0x3F0000 bytes and NVS is 0x5000 bytes. This target does not reserve a second OTA application slot; do not flash it to boards with less than 4 MiB flash.

### Vending ESP32-S3
- OLED + PN532 I2C: SDA 8, SCL 9; PN532 IRQ 7, reset 10.
- UP/DOWN/SELECT: GPIO 4/5/6 to GND using INPUT_PULLUP.
- RC522 fallback: SCK 12, MISO 13, MOSI 11, SS 14, RST 15.
- Servo signal: slots 1–5 on GPIO 3, 16, 17, 18, 21.
- Shared IR sensor output: GPIO 1. Current code assumes HIGH means blocked; verify module polarity and output voltage before wiring. Never connect a 5 V output directly to an ESP32 GPIO.
- Use a correctly rated external servo supply with common ground. Do not power five servos from the ESP32 3.3 V pin.

## Security and recovery invariants

- Device keys, Wi-Fi passwords, PINs, and raw card UIDs are not logged.
- Raw card UID is held in RAM only while completing a user operation.
- Stable request IDs survive retries/reboots; request IDs are not regenerated while an operation is unresolved.
- Physical dispensing is never repeated automatically after an ambiguous reboot.
- Firmware compilation is verified by the v2 CI build; physical NFC, OLED, keypad, and power-recovery acceptance still requires the actual Cashier hardware.

## Product image synchronization and vending flash layout

The v2 vending target now includes the LittleFS image cache and JPEG decoder. Product images are not served through the legacy v1 firmware path.

- Admin uploads accept PNG/JPEG/WebP up to 2 MiB; the server normalizes them to JPEG thumbnails sized for the 128x64 SSD1306 OLED and enforces a 64 KiB maximum per image.
- The v2 catalog returns the SHA-256 digest and device-scoped image URL. The vending board downloads with `X-Device-Key`, verifies the digest, writes a temporary file, and atomically swaps it into LittleFS. A failed transfer/hash check preserves the last valid image.
- The OLED renders the cached JPEG in monochrome. The local WebUI runtime status reports how many catalog images are cached.

The PlatformIO `vending` target is configured for the standard ESP32-S3-DevKitC-1-N8 profile (8 MiB flash). Partition table: `partitions/mgroup_vending_8mb.csv`.

| Partition | Offset | Size |
|---|---:|---:|
| NVS | 0x9000 | 20 KiB |
| OTA data | 0xE000 | 8 KiB |
| OTA app 0 | 0x10000 | 3 MiB |
| OTA app 1 | 0x310000 | 3 MiB |
| LittleFS | 0x610000 | 1.9375 MiB |

The partition table ends at 0x800000. Five 64 KiB images consume at most 320 KiB; LittleFS retains additional space for metadata and atomic replacement. This profile must only be flashed to an 8 MiB board. Confirm the module marking on production hardware; a 4 MiB or 32 MiB variant needs its matching partition configuration.

Source integration and partition arithmetic are not build evidence. Firmware compilation, final app-slot usage, OTA behavior, power-loss recovery, and OLED image rendering remain release-gate validation items.
