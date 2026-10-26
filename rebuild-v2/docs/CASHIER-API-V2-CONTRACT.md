# Cashier API v2 — contract and implementation gate

Status: design contract for the next implementation slice. These routes are proposed v2 contracts; they are not implemented until matching backend tests pass.

## Shared rules

- All routes require `X-Device-Key`; backend resolves authenticated `hardware_id` and `registry_id` from the key.
- A cashier route rejects a device whose registered `device_type` is not `cashier`.
- Never accept `device_id`, an arbitrary account ID, or a client-supplied hardware identity as authorization.
- Monetary values use positive integer `amount_minor` in IDR whole rupiah.
- Mutating requests require a stable `request_id` (8–128 characters). Same key and same semantic request replays the original result; same key with changed member, amount, device, or operation returns `409 IDEMPOTENCY_CONFLICT`.
- Card UIDs and PINs are never written to logs, audit detail, transaction metadata, or responses. Store only the peppered card hash and a salted PIN verifier.
- Balance changes, transaction record, ledger entries, stock changes (where applicable), and audit event commit atomically.
- Responses use `transaction_id`, `request_id`, `status`, and `idempotent_replay`; no v1 compatibility aliases.

## Read-only member balance

`POST /api/v2/devices/member-balance`

Request:
```json
{"card_uid":"04A1B2C3"}
```

Response:
```json
{"member_id":"NTR-00001","display_name":"Member","balance_minor":25000,"currency":"IDR"}
```

- Valid only for an active, authenticated cashier or vending device and active member/card/account.
- Card UID alone is not payment authorization.
- Must not create a transaction, debit, credit, or ledger entry.
- Unknown or inactive card returns a stable authorization error without revealing whether a card UID is enrolled.

## Cashier payment

`POST /api/v2/cashier/payments`

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

Request:
```json
{"request_id":"cashier-topup-0001","card_uid":"04A1B2C3","operator_pin":"••••","member_pin":"123456","amount_minor":10000}
```

- Require an active cashier device and an enrolled operator identity/PIN bound to that device; do not accept a caller-chosen operator identity.
- Verify both operator PIN and member PIN, with throttling and audit of the outcome but never the secret values.
- Atomically credit the member account and the backing system account, create balanced ledger entries, transaction, and audit event.
- Replays return the original transaction. Reusing the request ID with a changed amount/card/device returns a conflict.
- The API must not be implemented until the operator-to-device binding and secure operator enrollment/reset process exist.

## Required schema work before implementation

1. Add an operator credential verifier and status lifecycle to the existing cashier/operator model.
2. Define an explicit, auditable cashier-device-to-operator binding and merchant/settlement account assignment. Do not infer either from display names or client payloads.
3. Add appropriate uniqueness and foreign-key constraints, including idempotency scope.
4. Keep card hashes peppered; keep PINs as salted slow hashes; keep raw secrets out of audit and transaction metadata.
5. Add migration tests for clean install and upgrade from the previous v2 schema.

## Required tests

- Wrong device type, missing/invalid/revoked device key, inactive member/card/account, invalid PIN, lockout, and expired operator authorization.
- Successful payment has exactly one member debit and one merchant credit; repeated request has no additional ledger entries.
- Successful top-up has exactly one member credit and one system-account debit; repeated request has no additional entries.
- Request ID reused with a changed amount, card, device, or operation is rejected.
- Concurrent duplicate requests create one transaction and one financial mutation.
- Balance lookup is read-only and does not expose raw card UID, PIN, or card enrollment status.
- Audit events identify the authenticated device and server-resolved operator/settlement account without recording secrets.

## Release gate

Do not switch the existing cashier firmware to v2 until these contracts are implemented, documented in OpenAPI, covered by tests, and the firmware request/recovery behavior is tested against them. Vending v2 and cashier v2 may be delivered as separate milestones, but the overall rebuild must not be described as end-to-end complete while the cashier path is missing.
