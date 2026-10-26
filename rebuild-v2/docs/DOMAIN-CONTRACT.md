# M-Group v2 Domain Contract

## Identity vocabulary

- **hardware_id**: stable identifier derived by firmware from the physical unit (for example, a normalized MAC-derived identifier). It identifies the device itself.
- **registry_id**: server-generated opaque identifier for one registry record. It identifies the database record, not the physical unit.
- **device_key**: secret credential used by a device to authenticate to the backend. Store only a verifier/hash server-side; never log or return the secret after provisioning.
- **member_id**: server-side identifier for a member/account.
- **transaction_id**: server-side identifier for a financial or purchase transaction.
- **request_id**: correlation/idempotency identifier for one client request.

The string `device_id` is prohibited in all v2 runtime contracts, schema, tests, firmware protocol, and documentation, except this explicit prohibition and a one-time audit that checks for forbidden legacy references.

## Device registry invariants

1. A physical device has one canonical `hardware_id`.
2. A registry row has one server-generated `registry_id`.
3. `hardware_id` is unique when present; a provisioned-but-not-yet-bound registry row may have no `hardware_id`.
4. Device authentication uses a device key, not a client-supplied registry record ID.
5. Device type and lifecycle status are validated against enumerated values.
6. Revoked/disabled devices cannot create purchases or financial mutations.
7. Device registration and provisioning events are auditable.
8. The backend derives the authenticated `hardware_id` from the credential lookup. It must not trust an arbitrary hardware identity in a payment request body.

## Money and transaction invariants

1. Store monetary values as integer minor units (for IDR, whole rupiah integer values are used).
2. Every mutation that changes balances must be represented by a durable ledger/transaction record.
3. Idempotency keys are scoped and unique; retries must not create duplicate charges or ledger entries.
4. A payment must atomically validate authorization, balance, and transaction state before committing.
5. Failed/declined transactions must not partially mutate balances.
6. Transaction records retain the authenticated hardware identity when a device initiates the transaction.
7. Financial corrections use explicit reversal/adjustment entries; historical rows are not silently rewritten.
8. A vending purchase remains `pending` after debit/stock reservation until the originating vending device confirms dispense success; only then becomes `succeeded`. A failed dispense becomes `reversed` exactly once.

## Security invariants

- Do not store raw device keys, member PINs, or other authentication secrets.
- Enforce member PIN verification wherever the product policy requires it; tests must reflect the policy rather than weaken it.
- Validate all request bodies at API boundaries.
- Use parameterized SQL and explicit transaction boundaries.
- Never include secrets in API responses, logs, error messages, or CI artifacts.

## API contract invariants

- JSON property names use the canonical vocabulary above.
- API responses use stable, documented error codes.
- Device-originated transactions derive identity from authenticated request context.
- Schema and API contract tests must fail if the prohibited legacy field appears in a v2 runtime contract.

## Data migration

V2 starts with a clean schema and does not attempt an implicit conversion of the legacy database. Any future production-data migration must be a separate, reviewed, backed-up, rehearsed, and explicitly approved project.
