# Cashier API v2 — contract and implementation gate

Status: read-only member-balance lookup, authenticated vending product catalog, cashier payment, and cashier top-up routes are now implemented in the v2 backend. The cashier routes bind only the settlement account to the authenticated device, validate member PINs with persisted lockout, and use atomic ledger transactions. The added cashier regression tests and full validation matrix still need to be run after the rebuild work is complete.

## Shared rules

- All routes require `X-Device-Key`; backend resolves authenticated `hardware_id` and `registry_id` from the key.
- A cashier route rejects a device whose registered `device_type` is not `cashier`.
- Never accept `device_id`, an arbitrary account ID, or a client-supplied hardware identity as authorization.
- Monetary values use positive integer `amount_minor` in IDR whole rupiah.
- Mutating requests require a stable `request_id` (8–128 characters). Same key and same semantic request replays the original result; same key with changed member, amount, device, or operation returns `409 IDEMPOTENCY_CONFLICT`.
- Card UIDs and PINs are never written to logs, audit detail, transaction metadata, or responses. Store only the peppered card hash and a salted PIN verifier.
- Balance changes, transaction record, ledger entries, stock changes (where applicable), and audit event commit atomically.
- Responses use `transaction_id`, `request_id`, `status`, and `idempotent_replay`; no v1 compatibility aliases.

## Authenticated vending product catalog

`GET /api/v2/device/products`

- Requires a valid active vending device key and returns only that device's five product slots.
- Cashier devices and unauthenticated requests are rejected. Product reads do not require an admin bearer token.
- Regression tests cover the returned catalog, device ownership, missing credentials, and wrong device type.

## Authenticated vending product images

`GET /api/v2/device/products/{product_id}/image`

- Requires the active vending device's `X-Device-Key`; the server resolves the owning registry and serves only that registry's Product ID 1–5 image.
- The catalog includes `image_sha256` and a device-scoped `image_url`. No admin bearer token or legacy `/api/v1` endpoint is used by firmware.
- Admin uploads use `POST /api/v2/admin/vending/devices/{registry_id}/products/{product_id}/image`, accept PNG/JPEG/WebP source files up to 2 MiB, and normalize them to JPEG thumbnails no larger than 64 KiB.
- The SHA-256 is computed over the exact JPEG bytes returned to the device. Vending downloads only changed hashes, verifies the bytes before writing, writes a temporary LittleFS file, and swaps it atomically while preserving the previous valid image on failure.
- The v2 Vending OLED decodes the cached JPEG and renders it in monochrome. A missing/invalid image never blocks catalog use or a purchase.

## Read-only member balance

`POST /api/v2/devices/member-balance`

Request:
```json
{"card_uid":"04A1B2C3"}
```

Response:
```json
{"member_id":"UID-00001","display_name":"Member","balance_minor":25000,"currency":"IDR"}
```

- Valid only for an active, authenticated cashier or vending device and active member/card/account.
- Card UID alone is not payment authorization.
- Must not create a transaction, debit, credit, or ledger entry. Regression tests verify the endpoint leaves transaction and ledger counts unchanged.
- Unknown or inactive card returns a stable authorization error without revealing whether a card UID is enrolled.

## Cashier payment

`POST /api/v2/cashier/payments`

Implementation status: implemented in `rebuild-v2/backend/mgroup_backend/main.py`; regression coverage has been added but not yet run in the final full-suite pass.

Request:
```json
{"request_id":"cashier-payment-0001","card_uid":"04A1B2C3","pin":"123456","amount_minor":5000}
```

- Verify member/card status and PIN with the same persisted throttling policy used by vending purchases.
- Resolve the receiving merchant/settlement account from trusted server-side configuration associated with the authenticated cashier device. Never accept the receiving account from the client.
- Atomically debit the member account and credit the configured merchant account; create one balanced transaction and audit event.
- Return the balance after the committed transaction. Insufficient balance returns `409 INSUFFICIENT_BALANCE`.
- Idempotent retries must not debit twice, even if the first HTTP response is lost.

## Cashier top-up

`POST /api/v2/cashier/top-ups`

Implementation status: implemented in `rebuild-v2/backend/mgroup_backend/main.py`; regression coverage has been added but not yet run in the final full-suite pass.

Request:
```json
{"request_id":"cashier-topup-0001","card_uid":"04A1B2C3","member_pin":"123456","amount_minor":10000}
```

- Require an active, authenticated Cashier device.
- Verify the Member PIN with persisted throttling. No operator identity or PIN exists.
- Atomically credit the member account and the backing system account, create balanced ledger entries, transaction, and audit event.
- Replays return the original transaction. Reusing the request ID with a changed amount/card/device returns a conflict.
- The API uses only the server-side settlement-account assignment. Remaining release work is to connect the firmware/UI and run the final integration suite.

## Implementation controls and remaining gaps

1. Cashier device-to-settlement-account binding is stored server-side; admin endpoints provision merchant settlement accounts and configure the cashier binding.
2. Member PINs use salted PBKDF2 verifiers. Persisted failed-attempt counters apply a five-minute lock after five failures.
3. Payment and top-up transactions write transaction rows, balanced ledger entries, balance changes, and audit events atomically; request IDs are scoped globally and conflicting payloads return `409`.
4. Card UIDs are pepper-hashed before lookup and are not stored in transaction metadata or audit detail. PIN values are never written to logs or transaction metadata.
5. Remaining: connect v2 firmware and WebUI, and complete clean-install/upgrade and end-to-end validation before release.

## Required tests

- Wrong device type, missing/invalid/revoked device key, inactive member/card/account, invalid PIN, lockout, and invalid member PIN lockout.
- Successful payment has exactly one member debit and one merchant credit; repeated request has no additional ledger entries.
- Successful top-up has exactly one member credit and one system-account debit; repeated request has no additional entries.
- Request ID reused with a changed amount, card, device, or operation is rejected.
- Concurrent duplicate requests create one transaction and one financial mutation.
- Balance lookup is read-only and does not expose raw card UID, PIN, or card enrollment status.
- Audit events identify the authenticated device and server-resolved settlement account without recording secrets.

## Release gate

Do not switch the existing cashier firmware to v2 until these contracts are implemented, documented in OpenAPI, covered by tests, and the firmware request/recovery behavior is tested against them. Vending v2 and cashier v2 may be delivered as separate milestones, but the overall rebuild must not be described as end-to-end complete while the cashier path is missing.
