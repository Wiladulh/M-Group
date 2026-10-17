# Cashier firmware build plan

## Goal
Build the M-Group Cashier firmware in small, testable steps without expanding scope unnecessarily. Keep the existing NFC/keypad/LCD payment and deposit flows working.

## Agreed behavior

### 1. On-device configuration UI
- The ESP32 hosts a lightweight local Web UI; it is separate from the M-Group server Web UI.
- Configure primary Wi-Fi and multiple fallback SSIDs, including priority/order. Support SSID scan, save, reconnect, and status.
- Configure the M-Group server base URL and device name/ID without reflashing.
- Persist settings in ESP32 NVS; survive reboot.
- Show DHCP IP on LCD/Serial so an operator can open the UI from a browser. Support mDNS where available, but do not depend on it.
- If all configured networks fail, enable a temporary recovery AP/configuration mode. No permanently open AP in normal operation.
- Provide local admin authentication. Never reveal stored Wi-Fi passwords or device keys in the UI/logs.
- Test new settings before committing them; preserve/restore last known-good settings on failure.
- Keep configuration reset separate from transaction state. Never erase pending payment/deposit metadata or server-side records during network reset.

### 2. Server contract and transaction safety
- Server remains authoritative for membership, authorization, balances, ledger, transaction records and reports.
- Preserve existing API paths/contracts and device authorization unless a separately tested server change is required.
- Do not accept a transaction as successful until the server confirms it.
- On ambiguous timeout/5xx, preserve pending transaction identity and retry using the same idempotency key. Never create a second transaction by retrying or printing.
- A changed server URL must not bypass device authorization or TLS certificate validation. For local HTTP deployment, clearly document trusted-LAN assumptions.

### 3. Optional Bluetooth receipt printer
- Printer support is optional; no printer must be required for payment or boot.
- UI provides scan, select, connect/pair where supported, status, test print, reconnect and clear selection/pairing where supported.
- Print only after server-confirmed transaction success. Reprint uses the existing transaction/receipt data and must never submit a new payment.
- Report unsupported printer/protocol, pairing and connection errors clearly; these are not automatically firmware defects.
- Keep printer code behind a separate interface so printer failure cannot block a transaction.

### 4. Hardware baseline
- ESP32 DevKit / ESP-WROOM-32.
- LCD 16x2 I2C: SDA 21, SCL 22 (default address 0x27).
- PN532 I2C: SDA 21, SCL 22, IRQ 39, RESET 5; RC522 SPI fallback: SCK 18, MISO 19, MOSI 23, SS 27, RST 4.
- Keypad 4x4 rows 32, 33, 25, 26; columns 13, 14, 16, 17.
- GPIO39 is input-only. Confirm module voltage and I2C pull-ups before powering hardware.
- Printer is Bluetooth-only and optional; no printer hardware is required to build/test the base cashier.

## Implementation sequence
1. Baseline: build current firmware and keep CI plus transaction/idempotency contract tests green.
2. Configuration storage: replace compile-time-only Wi-Fi/server settings with validated NVS-backed settings, with safe defaults and migration behavior.
3. Network recovery: primary/fallback SSIDs, bounded reconnect, DHCP status, recovery AP, and tests.
4. Configuration UI: authenticated local pages for Wi-Fi/server/device status and safe apply/reset; test invalid settings and rollback.
5. Printer: optional Bluetooth adapter and UI controls; test unavailable/unsupported printer and ensure payment remains usable.
6. Physical validation: flash artifact; verify LCD, keypad, NFC reader, Wi-Fi failover, config access, server connection, normal/failed/uncertain payments, and printer if available.

## Build/test gates
- Every step must compile in the existing PlatformIO esp32dev environment and keep relevant GitHub Actions green.
- Add automated tests for configuration validation/persistence behavior, fallback/recovery behavior where testable, and transaction idempotency safety.
- Hardware-only behavior must be labelled pending until tested on the actual board; CI cannot certify wiring, Wi-Fi RF behavior, Bluetooth pairing or a specific printer model.
- Never commit live Wi-Fi passwords, device keys, PINs, or production data.
- Keep changes limited to this scope. Do not refactor unrelated server/UI components as part of the cashier build.

## Current status
Requirements are recorded. Configuration Web UI and printer support are not yet implemented. Start with Step 1: inspect the current firmware and CI baseline, then implement the smallest safe change set.
