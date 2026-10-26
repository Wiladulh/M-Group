# Security and financial audit — next gates

Scope: source review of the clean-room v2 backend at the time of this commit. This is a review record, not a production-readiness approval.

## Confirmed strengths

- Vending purchase and dispense-result transitions use `BEGIN IMMEDIATE` transactions.
- Purchase request IDs are unique and replay checks compare device, product, and card hash.
- Failed dispense restores the member balance and product stock and records compensating ledger entries in the same database transaction.
- Device role checks reject cashier devices at vending purchase and dispense endpoints.
- Product updates normalize whitespace-only names and constrain slot IDs to 1–5.
- NFC and QRIS promo columns are constrained to zero in the clean-install schema.

## Blocking findings to close before acceptance

1. **PIN throttling / lockout is not implemented in the purchase path.** Each request verifies the PIN but there is no persisted per-member/card/device failure counter, cooldown, or security event for repeated failures. Add a concurrency-safe persisted policy and tests for threshold, cooldown expiry, successful reset, and concurrent requests.
2. **Admin authorization is a single bearer token in this v2 snapshot.** `require_admin` compares a configured token; there are no granular roles or session lifecycle in this module. Before production, define the admin identity/session model, role matrix, revocation, audit actor identity, and CSRF protections for browser sessions.
3. **Ledger integrity is not independently asserted by the API tests.** Existing tests check balance and stock after refund, but do not verify balanced debit/credit sums, exact ledger row counts, or behavior under concurrent duplicate dispense reports. Add invariants and concurrency tests.
4. **Operational recovery remains unproven.** Clean-install schema tests do not demonstrate backup restoration, crash recovery, secret rotation, deployment rollback, or reconciliation of ambiguous physical dispense outcomes. Add repeatable acceptance procedures and evidence.

## Required regression cases

- More than the allowed number of invalid PIN attempts must be throttled without charging or decrementing stock; a valid PIN must not bypass an active lock.
- Concurrent purchase replays with the same request ID produce one debit, one stock decrement, and one transaction.
- Concurrent failed dispense reports produce one refund, one stock restoration, and one pair of compensating ledger entries.
- Reusing a request ID for a different member/card/device/product/amount is rejected.
- For every financial transaction, ledger debits equal credits and compensating entries are unique and auditable.
- Admin permissions are tested per operation; unauthenticated and unauthorized requests fail closed.

## Gate

Do not merge to `main`, deploy, or treat the rebuild as production-ready until the blocking findings are implemented, tested, and reviewed. Keep all work isolated to `rebuild/clean-room-v2`.
