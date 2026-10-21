# Vending transaction recovery and verification boundaries

## Transaction contract

- Every vending attempt uses a per-device idempotency key whose opaque nonce is generated locally and persisted in NVS: `<persisted-device-nonce>:<persistent-sequence>`.
- The complete create request (product, NFC credential, sequence, and servo channel) is persisted in NVS before the first HTTP request. If the response is lost or the device reboots, it retries with the same sequence/idempotency key; it must not create a fresh vend until the pending request resolves.
- The firmware stores the transaction ID and current phase in NVS before authorization and before servo actuation.
- If the authorization response is ambiguous, the device queries `GET /api/v1/vending/transactions/{transaction_id}` with `X-M-Group-Device-Key` before deciding what to do.
- The status endpoint only returns a transaction to the device registered to its machine. Missing/invalid device credentials are rejected.
- The server rejects reuse of an idempotency key for a different machine/product/credential/payment method/provider.
- Dispense reports and refunds are retryable. Server-side state transitions prevent concurrent duplicate stock decrements; refunds use a stable ledger idempotency key.
- If power is lost after the firmware persists the `dispensing` phase but before it can confirm the report, the firmware will not run the servo again. It reports the result as uncertain/failed and requests reconciliation/refund. This avoids double dispensing, but without a physical sensor it can conservatively refund a product that may already have fallen.

## IR product-drop validation

The five product slots share one output chute, so the firmware supports one IR break-beam pair across that chute. The receiver output connects to ESP32-S3 GPIO 1 by default (`PRODUCT_DROP_SENSOR_PIN`); connect sensor ground to ESP32 ground and power the module according to its datasheet. The receiver output must never exceed 3.3 V at the ESP32-S3 GPIO. If the selected receiver has inverted output polarity, change `PRODUCT_SENSOR_BLOCKED_LEVEL` in `esp32/vending/MGroupVending.ino` after confirming its actual behavior.

Before moving a servo, firmware requires the beam to be clear. It then opens the selected servo and monitors the beam for up to four seconds, requiring a blocked-then-clear passage. Only a detected passage is reported as successful dispensing. If no complete passage is detected, firmware reports failure so the server can reconcile/refund; it does not automatically actuate the servo again. The result is persisted before the server report, so report retries do not repeat physical dispensing.

A confirmed beam passage proves the product crossed the sensor point, not that the customer received it. Physical sensor polarity, placement, package sizes, and the four-second timeout must be verified on the real machine before production use.

## Catalog and promo

The product API exposes `price` / `base_price` as the configured price and sets `effective_price` to the same amount, `discount_amount` to `0`, and `promo_id` to `null`. Promotion rules may be stored for future development but are intentionally not applied to catalog prices or transactions yet. The admin inventory shows Promo NFC and Promo QRIS as `0%` and inactive. QRIS payments remain inactive until their provider integration is implemented.

## Device enrollment

The administrator generates a one-time Device Key from the authenticated dashboard. The ESP32 mini WebUI accepts Wi-Fi SSID/password, server URL, and that key only. Firmware enrolls with its device type, MAC address, and Device Key. The Device Key is the only device authentication credential; firmware and public API responses do not use or expose a Device ID. The server binds the MAC address to the provisioned key, checks the device type, and rejects keys that were not issued by the server.

## Verification levels

- Automated API tests verify contract, authorization, idempotency, stock/refund state, and transaction status recovery.
- Firmware CI/build verifies compilation only when the relevant toolchain job is present.
- Physical PASS requires a real device test covering response loss, reboot before/after servo actuation, low stock, server outage, and refund reconciliation. Without a sensor, product delivery remains unverified.
