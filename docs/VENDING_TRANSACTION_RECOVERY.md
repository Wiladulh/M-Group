# Vending transaction recovery and verification boundaries

## Transaction contract

- Every vending attempt uses a device-scoped idempotency key: `<device-id>:<persistent-sequence>`.
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

The product API keeps `price` / `base_price` as the configured base price and exposes `effective_price`, `discount_amount`, and `promo_id` for the NFC/local path currently used by firmware. The device refreshes its catalog periodically and after a completed vend. QRIS remains inactive until its provider integration is implemented.

## Device enrollment

Manual provisioning remains the official flow. An administrator provisions a device through the authenticated dashboard/API using the exact Device ID and device type, then enters the returned one-time key into the firmware mini WebUI. On first boot (or when setup mode is deliberately triggered), firmware starts a temporary password-protected setup AP and a local WebUI for SSID, server URL, Device ID, and key. The key is stored in ESP32 NVS and is never rendered back into the page. Firmware then authenticates using the existing device key header and heartbeat endpoint. This is configuration, not self-enrollment: the portal does not create a server registry entry, generate a server key, or activate pending devices. The public handshake endpoint is not automatic enrollment.

## Verification levels

- Automated API tests verify contract, authorization, idempotency, stock/refund state, and transaction status recovery.
- Firmware CI/build verifies compilation only when the relevant toolchain job is present.
- Physical PASS requires a real device test covering response loss, reboot before/after servo actuation, low stock, server outage, and refund reconciliation. Without a sensor, product delivery remains unverified.
