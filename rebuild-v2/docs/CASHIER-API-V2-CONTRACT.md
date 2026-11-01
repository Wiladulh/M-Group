# Cashier API v2 — contract and implementation gate

Status: Cashier v2 supports member NFC payment and NFC/PIN enrollment only. Member balance top-up is an administrator-only operation in the Server WebUI. There is no Cashier top-up API or Cashier top-up flow.

## Shared rules

- All device routes require `X-Device-Key`; the backend resolves the active device identity from the key.
- Cashier routes reject devices whose registered type is not `cashier`; Vending routes reject non-vending devices.
- Monetary values use positive integer `amount_minor` in IDR whole rupiah.
- Mutating requests require a stable `request_id`; same-key retries replay the original result and changed semantic requests conflict.
- Raw card UIDs, raw PINs, and PIN verifiers are never returned or written to audit metadata.
- PIN verifiers use salted PBKDF2. Five incorrect PIN attempts lock that card/device combination for five minutes.
- Financial changes, transaction records, ledger entries, stock changes and audit events commit atomically.

## Member transaction PIN

- Every Member must have an individual transaction PIN before using NFC payments.
- The PIN can be set optionally in the Server WebUI Member registration form/API, or during NFC card registration at the Cashier keypad.
- The NFC registration flow is: Admin starts a session; Cashier reads the new card; Member enters a 6–12 digit PIN; server stores only the salted verifier and binds the card.
- Replacing an NFC card requires a PIN to be set/confirmed in the same enrollment flow. A valid PIN must never be silently cleared.
- The same Member PIN is required for payments at Cashier and Vending.
- PIN is never stored in firmware preferences, local cache, request recovery state, logs, or API responses.

## Cashier payment

`POST /api/v2/cashier/payments`

Request:
```json
{"request_id":"cashier-payment-0001","card_uid":"04A1B2C3","pin":"123456","amount_minor":5000}
```

- Verify active member/card/account and the member transaction PIN before processing.
- Resolve the merchant/settlement account from server-side Cashier configuration. The client cannot choose the receiving account.
- Atomically debit the member account, credit the configured merchant account, and write the transaction, balanced ledger entries and audit event.
- Idempotent retries must not debit twice; PIN verification still applies to a retry.

## Vending payment

`POST /api/v2/vending/purchases`

Request:
```json
{"request_id":"vending-purchase-0001","card_uid":"04A1B2C3","pin":"123456","product_id":1,"payment_method":"nfc"}
```

- Verify the same Member transaction PIN before debiting the member balance or reserving stock.
- Vending hardware uses its existing UP/DOWN/SELECT buttons to enter a masked numeric PIN: UP/DOWN changes the current digit, SELECT adds it, and holding SELECT confirms after at least six digits.
- A wrong PIN must not debit the account or reduce stock.
- The existing dispense-result flow remains responsible for exactly-once refund when dispensing fails.

## Member balance top-up — Server WebUI only

- Member gives the money directly to Admin.
- Admin selects the Member in Server WebUI, enters the amount received, and submits the top-up.
- The authenticated Server API credits the member account and writes the corresponding system-account debit, transaction, balanced ledger entries and audit event atomically.
- Top-up does not require a member PIN, operator PIN, NFC tap, Cashier, or Vending.
- `POST /api/v2/finance/top-ups` is the only v2 top-up endpoint and requires an authenticated Admin session.
- `POST /api/v2/cashier/top-ups` is intentionally not implemented and must return 404/405.

## Required regression tests

- Member PIN set during member creation is stored only as a salted verifier.
- NFC registration requires and stores a member PIN; card replacement cannot leave the member without a PIN.
- Cashier and Vending reject missing/incorrect PINs without financial or stock mutation.
- Five failed PIN attempts cause a persisted five-minute lockout; a valid PIN clears the counter after lockout expires.
- Admin top-up is idempotent and creates balanced ledger entries; Cashier/Vending top-up endpoints do not exist.
- Raw PIN and PIN verifier never appear in API responses, logs, or audit metadata.

## Release gate

Do not mark Cashier or Vending v2 complete until the full backend test suite and both firmware builds pass. Physical acceptance must verify keypad PIN entry on Cashier, button-based PIN entry on Vending, RC522 card reads, NFC enrollment, payment, balance refresh, and failed-dispense refund behavior. Top-up acceptance is performed only through Server WebUI.
