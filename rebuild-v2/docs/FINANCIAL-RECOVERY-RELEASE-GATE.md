# M-Group v2 — Financial Recovery and Release Gate

This runbook is an acceptance checklist, not evidence that a backup or restore has already been tested. Do not use production data for CI tests.

## Financial invariants

- Every successful top-up has one member credit and one system debit for the same positive amount.
- Every purchase has one member debit and one system credit for the same amount.
- A purchase remains `pending` until the originating vending device confirms the physical dispense; it becomes `succeeded` only after success confirmation.
- A failed dispense reverses the account balance and product stock exactly once. Repeated dispense-result requests must not create extra ledger entries or extra stock.
- Pending purchases without a dispense result require operational monitoring/reconciliation; do not silently classify them as completed.
- For every transaction, total debits equal total credits.
- For every account, the stored balance reconciles with its ledger under the chosen direction convention.
- Request IDs are unique and retries with different payloads must fail with an idempotency conflict.
- Any reconciliation exception must be investigated; do not repair balances by editing rows manually without a documented adjustment transaction and audit event.

## Backup procedure — before production use

1. Stop writes or use SQLite's online backup API to obtain a transactionally consistent database snapshot. Do not copy a live SQLite database file with an ordinary file copy unless writes are quiesced and WAL state is handled.
2. Store the snapshot encrypted, restrict access, and record the UTC timestamp, application commit, schema version, file size, and SHA-256 checksum.
3. Keep a second copy in a separate failure domain. Never store backup encryption keys beside the backup.
4. Define and approve retention, access, and deletion policies before enabling real member balances.
5. Back up required uploaded product images and deployment configuration separately. Never include plaintext secrets in the backup manifest.

## Restore drill — required before release

1. Restore a copy into an isolated environment; never overwrite the active database during a drill.
2. Verify checksum and SQLite integrity with PRAGMA integrity_check and foreign keys with PRAGMA foreign_key_check.
3. Start the exact application commit against the restored copy and verify readiness.
4. Run ledger reconciliation: per-transaction debit total equals credit total; account balances reconcile; no duplicate request IDs; failed-dispense reversals and stock changes are idempotent.
5. Exercise a test top-up, purchase, retry, failed dispense, and repeated refund using synthetic records only.
6. Record duration, observed data-loss window, errors, application commit, schema, responsible Admin, and pass/fail. Repeat after schema or backup-process changes.

## Deployment and recovery gates

- [ ] Backup restore drill passed and evidence is attached to the release.
- [ ] Ledger reconciliation test passed on a clean database and a restored database.
- [ ] Admin token is high entropy, stored only in secret management, and rotated through a documented procedure.
- [ ] Device-key pepper is non-empty, stable across restarts, stored as a secret, and rotation has a migration/re-enrollment plan.
- [ ] Rollback procedure accounts for database/schema compatibility; application rollback alone is not assumed safe.
- [ ] Production cutover and any merge to main are explicitly approved by the repository owner.

## Current limitations

The checklist above is a required procedure. It does not claim that backup/restore, secret rotation, disaster recovery, role-based admin access, or production deployment have been implemented or verified. The current backend uses a single shared admin bearer token; it does not yet provide granular admin roles or session lifecycle management.
