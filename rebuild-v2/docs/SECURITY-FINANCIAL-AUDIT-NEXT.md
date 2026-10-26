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
2. **The v2 cashier API and firmware are not implemented yet.** The backend currently supports admin top-ups and vending purchases, but does not yet provide a secure cashier payment/top-up/member-balance workflow with cashier operator authorization. `rebuild-v2/firmware/README.md` `rebuild-v2/firmware/README.md` currently specifies the target contract but contains no firmware implementation. The existing `esp32/cashier` and `esp32/vending` sketches still call `/api/v1` routes and use the legacy request/response contract. Do not claim end-to-end v2 readiness until firmware is migrated and contract-tested, or firmware migration is explicitly separated from this release.
3. **Admin authorization remains a shared bearer token.** Define the admin identity/session model, role matrix, revocation, audit actor identity, and CSRF protections if browser sessions are introduced before production use.
4. **Operational recovery is not proven.** Run and record a backup/restore drill, SQLite integrity and foreign-key checks, ledger reconciliation on the restored copy, secret rotation/re-enrollment, and database-aware rollback rehearsal.
5. **Pending dispense recovery is only surfaced, not automated.** The reconciliation report lists pending purchases for manual review; define age thresholds, operator procedures, and safe handling of ambiguous physical outcomes. Never auto-refund an uncertain dispense without a documented decision rule.
6. **Legacy feature parity and cutover inventory remain open.** Compare the clean-room API, web UI, cashier workflow, vending workflow, and operational procedures against the legacy project. Document any intentionally excluded feature and migration/cutover plan before deciding the rebuild can replace the old system.

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
