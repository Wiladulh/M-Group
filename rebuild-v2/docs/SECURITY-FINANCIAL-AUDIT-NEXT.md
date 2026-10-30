# Security and financial audit — remaining acceptance gates

Scope: source review of the clean-room v2 backend on `rebuild/clean-room-v2`. This is an engineering audit record, not a production-readiness approval.

## Controls now present

- Vending purchases and dispense-result transitions use `BEGIN IMMEDIATE` transactions. Request-scoped SQLite connections permit worker-thread handoff safely while each connection remains scoped to one request.
- Purchase request IDs are unique; replay checks compare the authenticated device, product, and card hash.
- Failed dispense restores member balance and product stock and appends compensating ledger entries atomically.
- Device-role checks reject cashier devices at vending purchase and dispense endpoints.
- Persisted PIN throttling tracks failures by device and card, applies a card-wide lockout, and rejects valid PINs while the lock is active.
- The finance reconciliation endpoint reports transaction debit/credit imbalances, account-to-ledger balance mismatches, and pending purchases requiring review.
- Regression tests verify account balances against ledger entries after top-up, purchase, and failed-dispense reversal. Concurrent duplicate purchase and concurrent failed-dispense reports are covered by regression tests; the latest Test and Rebuild v2 workflows passed on commit `728a1bcc32254607cb902fbf5c0f474fe6306334`.
- Product updates reject whitespace-only names and constrain slot IDs to 1–5. Promo columns are constrained to zero in the clean-install schema.

## Blocking findings before merge/release acceptance

1. **Concurrency behavior now has regression coverage, but production load testing remains open.** CI verifies concurrent duplicate purchase requests and concurrent failed-dispense reports create one purchase debit, one stock decrement, one refund, one stock restoration, and one pair of compensating ledger entries. Add stress tests under realistic request volume before production use.
2. **Cashier and Vending v2 firmware source exists, but integration validation remains blocked.** The v2 firmware implementation is in `rebuild-v2/firmware/src/common.cpp`, `cashier.cpp`, and `vending.cpp`; the legacy sketches under `esp32/` still use `/api/v1` and are a separate target. Source-level API paths/payloads have been compared, but neither v2 firmware target has been compiled or hardware-tested. Do not mix the legacy sketches with the v2 backend.
3. **Admin authorization remains a shared bearer token.** Define the admin identity/session model, role matrix, revocation, audit actor identity, and CSRF protections if browser sessions are introduced before production use.
4. **Post-transaction balance refresh and bounded cache are partially implemented, with sync gaps remaining.** Both v2 firmware targets store up to 100 atomic device-salted member snapshots, refresh stale/missing entries on card tap, and update balances from authoritative transaction/refund responses. Authenticated bulk/delta sync on startup/reconnect/periodic schedule and durable pending-refresh recovery remain incomplete. Online server authorization remains authoritative; offline purchases must stay disabled until a device/member-bound allowance, secure PIN verification, durable journal, and reconciliation are implemented.
5. **Operational recovery is not proven.** Run and record a backup/restore drill, SQLite integrity and foreign-key checks, ledger reconciliation on the restored copy, secret rotation/re-enrollment, and database-aware rollback rehearsal.
6. **Pending dispense recovery is only surfaced, not automated.** The reconciliation report lists pending purchases for manual review; define age thresholds, operator procedures, and safe handling of ambiguous physical outcomes. Never auto-refund an uncertain dispense without a documented decision rule.
7. **Legacy feature parity and cutover inventory remain open.** Compare the clean-room API, web UI, cashier workflow, vending workflow, and operational procedures against the legacy project. Document any intentionally excluded feature and migration/cutover plan before deciding the rebuild can replace the old system.

## Required regression cases

- Invalid PIN attempts reach the configured threshold; cooldown and successful reset behave as documented, including requests across different vending devices.
- Concurrent purchase replays with the same request ID produce one transaction, one debit, and one stock decrement.
- Concurrent failed dispense reports produce one refund, one stock restoration, and one pair of compensating ledger entries.
- Reusing a request ID for a different member/card/device/product/amount is rejected.
- Every transaction has equal debit and credit totals; member and system account balances reconcile to the documented ledger direction convention.
- Pending purchases are visible in reconciliation and remain pending until the originating vending device confirms the result.
- Unauthenticated and unauthorized requests fail closed; no device can report a dispense result for another device's transaction.
- Firmware request/response contracts match the v2 API and survive network timeout/reboot without repeating a physical dispense.

## Gate

Do not merge to `main`, deploy, or treat the rebuild as production-ready until the blocking findings are implemented, tested, and reviewed. Keep work isolated to `rebuild/clean-room-v2`.
