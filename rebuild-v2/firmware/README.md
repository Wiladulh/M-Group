# Clean-room v2 ESP32 firmware

This directory is the v2 firmware implementation. It targets only the /api/v2 contract and uses hardware_id generated from the ESP32 eFuse MAC. registry_id is assigned by the server after a provisioned Device Key is used for first-boot enrollment. No device_id alias is used.

## Environments

- pio run -e cashier: ESP32 DevKit, LCD 16x2 I2C, 4x4 keypad, PN532 I2C preferred with RC522 SPI fallback.
- pio run -e vending: ESP32-S3, SSD1306 OLED, UP/DOWN/SELECT buttons, PN532 I2C preferred with RC522 SPI fallback, five servo outputs, one shared IR break-beam sensor.

This source has NOT been compiled or hardware-tested yet. Do not flash production hardware until the requested full test phase passes and each pinout is confirmed against the actual board revision.

## First boot and local WebUI

1. Boot the device with no Wi-Fi credentials. The device creates MGroupV2-Setup-XXXX and prints the AP password and initial local WebUI PIN to Serial Monitor once. Never publish those values.
2. Connect to the setup AP and open http://192.168.4.1/, or use the DHCP IP shown on Serial Monitor once station Wi-Fi is connected.
3. Login with the local WebUI PIN. Set Wi-Fi, the server URL, Device Key from the v2 admin dashboard, and a trusted CA certificate when using HTTPS.
4. The device sends POST /api/v2/device/register with X-Device-Key, its generated hardware_id, and MAC address. The server binds that hardware identity to the provisioned registry row.
5. The WebUI is protected by a local PIN, has a short-lived HttpOnly cookie, rate-limits failed PIN attempts, and never renders the Device Key in status output. Rotate the local PIN after first login.

HTTP is only appropriate on a trusted isolated LAN. HTTPS is rejected unless a trusted CA certificate is configured; no insecure TLS fallback is used.

## Cashier workflow

- A: payment, then enter amount, tap member card, enter member PIN.
- B: top-up, then enter amount, operator PIN, tap member card, and member PIN.
- * removes the last digit; # confirms the current amount/PIN.
- NFC enrollment sessions created by the admin WebUI are polled from /api/v2/cashier/nfc-registration. The selected cashier advances the server-side session and submits card UID plus new PIN to the completion endpoint.
- Payment/top-up request_id and amount are persisted before submission. Raw card UID and PIN are never written to NVS or Serial. If a response is lost, the user must tap the card and re-enter the PIN to retry the exact request ID.

## Vending workflow

- UP/DOWN selects a fixed slot; SELECT begins a purchase only while a valid live server catalog is available.
- The PIN is entered through the three-button interface: UP/DOWN changes the current digit and SELECT accepts it. Six digits are required.
- The server verifies expected_amount_minor against its current catalog price before debiting. QRIS is rejected until a provider integration is implemented.
- The firmware persists the request ID and amount before purchase submission. After the server creates a pending purchase, the transaction ID and dispensing stage are persisted before the servo moves.
- The IR sensor must observe a blocked-then-clear transition within four seconds. A failed dispense is reported to the server for atomic refund and stock restoration.
- If power is lost while the stage is dispensing, the servo is NOT replayed automatically. The transaction remains pending for manual review because the physical outcome is ambiguous. If the result report is pending, the same report is retried without actuating the servo again.
- A cached catalog is display-only while offline; payment remains disabled. Invalid server payloads do not replace the last-known-good cache.

## Pin map

### Cashier ESP32 DevKit
- LCD + PN532 I2C: SDA 21, SCL 22; PN532 IRQ 39, reset 5.
- Keypad rows 32, 33, 25, 26; columns 13, 14, 16, 17.
- RC522 fallback: SCK 18, MISO 19, MOSI 23, SS 27, RST 4.

### Vending ESP32-S3
- OLED + PN532 I2C: SDA 8, SCL 9; PN532 IRQ 7, reset 10.
- UP/DOWN/SELECT: GPIO 4/5/6 to GND using INPUT_PULLUP.
- RC522 fallback: SCK 12, MISO 13, MOSI 11, SS 14, RST 15.
- Servo signal: slots 1–5 on GPIO 3, 16, 17, 18, 21.
- Shared IR sensor output: GPIO 1. Current code assumes HIGH means blocked; verify module polarity and output voltage before wiring. Never connect a 5 V output directly to an ESP32 GPIO.
- Use a correctly rated external servo supply with common ground. Do not power five servos from the ESP32 3.3 V pin.

## Security and recovery invariants

- Device keys, Wi-Fi passwords, PINs, and raw card UIDs are not logged.
- PIN and card UID are held in RAM only while completing a user operation.
- Stable request IDs survive retries/reboots; request IDs are not regenerated while an operation is unresolved.
- Physical dispensing is never repeated automatically after an ambiguous reboot.
- No firmware build or hardware test has been run as part of the implementation phase.
