# NVM ESP32-S3 Vending — RC522 / PN532 Auto Detect

Vending supports both RC522 and PN532. Startup probes PN532 first, then falls back to RC522 automatically.

## Libraries

Install from Arduino Library Manager:
- Adafruit PN532
- MFRC522
- Adafruit GFX Library
- Adafruit SSD1306
- ESP32Servo

## Default reader wiring

PN532 I2C:
- SDA GPIO 8
- SCL GPIO 9
- IRQ GPIO 7
- RESET GPIO 10

RC522 SPI:
- SCK GPIO 12
- MISO GPIO 13
- MOSI GPIO 11
- SS GPIO 14
- RST GPIO 15

Change constants in NvmVending.ino for the actual ESP32-S3 board and wiring.

The UID is converted to nfc-<lowercase hexadecimal UID>. The NVM server remains authoritative for credential, account, balance, stock, transaction, and refund state.


## Server configuration

Set `WIFI_SSID`, `WIFI_PASSWORD`, `NVM_BASE_URL`, `DEVICE_ID`, and `NVM_DEVICE_KEY` in `NvmVending.ino`.

- `NVM_BASE_URL` must be the NVM server's reachable LAN address, for example `http://192.168.1.10:8011`; replace the example IP and do not add a trailing slash.
- NVM defaults to `NVM_HOST=127.0.0.1`, which is loopback-only. For LAN device access, start the server with `NVM_HOST=0.0.0.0 NVM_PORT=8011` (or bind to the server's LAN interface) and allow TCP 8011 only from the trusted LAN in the firewall.
- Provision `DEVICE_ID` with type `esp32-s3-vending` and use the returned device key. Register a vending machine in NVM with its `device_id` pointing to this device; the machine ID may be different from the device ID.
- The product API returns `enabled` as a JSON boolean. The firmware uses product ID, name, price, stock, enabled state, and servo channel from that response.

Firmware CI validates compilation only; NFC reads, Wi-Fi reachability, servo behavior, dispensing feedback, and real transaction reconciliation still require physical-device tests.
