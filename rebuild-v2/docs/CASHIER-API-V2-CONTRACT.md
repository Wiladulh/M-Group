# Cashier API v2 — contract and implementation gate

Status: Cashier v2 supports member NFC payment and NFC enrollment only. Member balance top-up is an administrator-only operation in the Server WebUI. There is no Cashier top-up API or Cashier top-up flow.

## Shared rules

- All device routes require `X-Device-Key`; the backend resolves the active device identity from the key.
- A Cashier route rejects devices whose registered type is not `cashier`.
- Monetary values use positive integer `amount_minor` in whole Indonesian rupiah.
- Mutating requests require a stable `request_id` (8–128 characters). Same-key retries replay the original result; changed semantic requests return `409 IDEMPOTENCY_CONFLICT`.
- Card UIDs are pepper-hashed. PIN values and PIN verifiers are never returned or written to audit details, transaction metadata, or logs.
- Financial balance changes, transaction records, ledger entries, and audit events commit atomically.

## Read-only member balance

`POST /api/v2/devices/member-balance`

Request:
```json
{"card_uid":"04A1B2C3"}
```

- Valid for active authenticated Cashier and Vending devices.
- Card UID alone is not payment authorization.
- The endpoint does not create transactions or ledger entries.

## Cashier payment

`POST /api/v2/cashier/payments`

Request:
```json
{"request_id":"cashier-payment-0001","card_uid":"04A1B2C3","pin":"123456","amount_minor":5000}
```

- Every member retains an individual transaction PIN.
- Verify the member's PIN and active NFC card before payment, using persisted failed-attempt throttling and lockout.
- Resolve the merchant/settlement account from server-side Cashier configuration. The client cannot choose the receiving account.
- Atomically debit the member account, credit the configured merchant account, and write the transaction, balanced ledger entries, and audit event.
- An idempotent retry must never debit twice.
- Member PIN is required for Cashier payment. It is not a top-up PIN.

## Member PIN and NFC enrollment

- A member PIN may be set during member creation or during NFC registration.
- NFC registration asks the member to enter their transaction PIN on the Cashier keypad; the server stores only a salted PIN verifier.
- Replacing/re-enrolling a card must leave the member with a valid transaction PIN. The member PIN is not removed.
- The same member transaction PIN is used for Cashier and Vending NFC payments.
- Admin may reset a member transaction PIN through the authenticated Server WebUI.

## Member balance top-up — Server WebUI only

- The member gives the money directly to the Admin.
- Admin selects the member in Server WebUI, enters the amount received, and submits the top-up.
- The server credits the member account and writes the corresponding system-account debit, transaction, balanced ledger entries, and audit event atomically.
- Top-up requires Admin WebUI authentication only. It does not require a member PIN, operator PIN, NFC tap, Cashier, or Vending.
- `POST /api/v2/finance/top-ups` is the only v2 top-up endpoint and requires an authenticated admin session.
- `POST /api/v2/cashier/top-ups` is intentionally not implemented and must return 404.

## Required regression tests

- Member PIN is accepted for Cashier and Vending payments; wrong PIN is rejected and lockout is persisted.
- Cashier cannot initiate top-up; the obsolete Cashier top-up route returns 404 and creates no transaction or ledger entry.
- Admin top-up credits the selected member exactly once, with a matching system-account debit and balanced ledger.
- Top-up retries are idempotent; changed request payloads conflict.
- PIN values, raw card UIDs, and PIN verifiers never appear in responses, logs, or audit metadata.

## Release gate

Do not mark the Cashier build complete until the firmware build and the full v2 backend test suite pass. Physical acceptance must verify RC522 card reads, member PIN entry, payment, balance refresh, and NFC enrollment. Top-up acceptance is performed only through the Server WebUI.
