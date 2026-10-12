# Vending transaction recovery and verification boundaries

## Transaction contract

- Every vending attempt uses a device-scoped idempotency key: `<device-id>:<persistent-sequence>`.
- The firmware stores the transaction ID and current phase in NVS before authorization and before servo actuation.
- If the authorization response is ambiguous, the device queries `GET /api/v1/vending/transactions/{transaction_id}` with `X-NVM-Device-Key` before deciding what to do.
- The status endpoint only returns a transaction to the device registered to its machine. Missing/invalid device credentials are rejected.
- The server rejects reuse of an idempotency key for a different machine/product/credential/payment method/provider.
- Dispense reports and refunds are retryable. Server-side state transitions prevent concurrent duplicate stock decrements; refunds use a stable ledger idempotency key.
- If power is lost after the firmware persists the `dispensing` phase but before it can confirm the report, the firmware will not run the servo again. It reports the result as uncertain/failed and requests reconciliation/refund. This avoids double dispensing, but without a physical sensor it can conservatively refund a product that may already have fallen.

## What a successful dispense means

The current hardware has no product-drop sensor. A successful firmware report means the configured servo movement sequence completed; it does **not** prove that a product physically reached the customer. API consumers and audit views must not present this as sensor-confirmed delivery. Adding a suitable drop sensor is a separate hardware revision.

## Catalog and promo

The product API keeps `price` / `base_price` as the configured base price and exposes `effective_price`, `discount_amount`, and `promo_id` for the NFC/local path currently used by firmware. The device refreshes its catalog periodically and after a completed vend. QRIS remains inactive until its provider integration is implemented.

## Device enrollment

Manual provisioning remains the official installation procedure for this release. An administrator provisions a device through the authenticated provisioning endpoint and places the returned device key into protected device configuration. The public handshake endpoint is not automatic enrollment: firmware must not self-authorize or activate itself merely by presenting a MAC address. Automatic enrollment would require a separate secure commissioning flow.

## Verification levels

- Automated API tests verify contract, authorization, idempotency, stock/refund state, and transaction status recovery.
- Firmware CI/build verifies compilation only when the relevant toolchain job is present.
- Physical PASS requires a real device test covering response loss, reboot before/after servo actuation, low stock, server outage, and refund reconciliation. Without a sensor, product delivery remains unverified.
