# M-Group — Device-Key-Only Database Migration Design

Status: design gate; not production-executable. Date: 2026-10-23.
Branch: `rebuild/clean-foundation`.
Related: `docs/REBUILD_MASTER_SPEC.md` Section 21 and `docs/REBUILD_BASELINE_AUDIT.md`.

## Goal

Remove `device_id` as an active identity field from API contracts, schema, application services, WebUI, firmware, logs, exports, and docs, while preserving transaction history, ledger correctness, auditability, and business `machine_id` relationships.

This document is a design and acceptance checklist, not a migration script. Do not apply it to a production VPS until the disposable-database gates below pass.

## Identity model

- A device proves possession of a server-issued device key sent over the authenticated transport.
- Persist only a one-way key hash, status/revocation metadata, server-assigned authorization scope/type, and timestamps in the credential registry. Never store or log the raw key.
- Authentication resolves the submitted key hash to one active credential record; authorization type/scope is read from that record. Clients do not send a device identity to authorize themselves.
- A business `machine_id` remains only where a vending machine is a business entity. It is not a device credential and is never a substitute for key validation.
- For event/audit attribution, use an internal credential-record primary key where attribution is needed. Do not expose a hardware-derived ID, MAC address, or legacy ID in API responses, logs, exports, or operator UI.
- Key revocation must immediately prevent further authenticated actions. Credential rotation must not rewrite historical financial transactions.

## Target data ownership

- Financial ledger remains authoritative for balances.
- Transactions retain their own immutable transaction IDs, amount/status/timestamps, account/member references, idempotency keys, payment/provider references, and business `machine_id` where applicable.
- Cashier deposits must not require a hardware ID to exist. Attribution may reference the credential record used when the transaction was accepted; if an old transaction cannot be mapped reliably, retain the transaction with a nullable/explicitly unavailable attribution state rather than guessing.
- NFC registration sessions associate with the authenticated credential record, not a client-supplied device ID.
- Device event history, if retained, attributes to a credential record. Do not keep a legacy ID in a renamed or hidden column.
- Audit events retain their own audit ID, event type, entity type/entity ID, detail, and timestamp. Sanitize detail payloads to prevent secrets and hardware identifiers leaking.

## Migration strategy (SQLite)

1. **Inventory exact live schemas** from the current migration sequence and supported upgrade paths. Do not infer the live schema solely from the latest SQL file.
2. **Build a disposable copy** from (a) an empty database and (b) representative legacy databases created from supported migration checkpoints. Record row counts, schema, foreign keys, indexes, and financial invariants.
3. **Create a versioned migration** that creates replacement tables without the forbidden column, copies data explicitly column-by-column, validates copied counts and required fields, recreates indexes/triggers, and swaps tables in a transaction where SQLite permits it. Handle foreign-key dependencies and table rebuild ordering explicitly.
4. **Preserve business links** such as `machine_id`, `transaction_id`, `member_id`, `account_id`, `credential_id`, payment provider references, and idempotency keys. Never translate a device ID into a machine ID unless an unambiguous, validated business mapping exists.
5. **Credential mapping:** map old registry rows to new credential rows only when their existing key hashes and authorization metadata are valid. Preserve revocation/status. Do not generate credentials from MAC addresses or old IDs. Do not log raw keys.
6. **Unmappable legacy rows:** preserve financial/audit rows without a guessed credential relation; record a migration summary count, not the sensitive legacy values. If a required relationship cannot be preserved safely, fail the migration before swapping tables.
7. **Validate before commit/swap:** SQLite integrity check is `ok`; foreign-key check is empty; all expected tables/indexes exist; forbidden columns and active SQL references are absent; row counts reconcile; ledger balances and transaction totals match pre-migration values; idempotency uniqueness remains intact.
8. **Rollback/backup:** create a verified pre-migration backup, test restoring it into a separate database, and retain an operator-controlled rollback plan. Never auto-delete or overwrite a production backup. No automatic migration on the active VPS until explicit acceptance.
9. **Repeatability:** migration version tracking prevents a successful migration from being applied twice. Interrupted migration must leave the old database usable or fail closed with clear recovery instructions.

## Cross-component implementation order

1. Introduce the server-side credential authentication primitive and tests, without yet removing schema fields used by old paths.
2. Move protected endpoint authorization to credential-derived type/scope; remove request-supplied identity from the request models and URLs.
3. Refactor payment, cashier deposit, NFC registration, device events, vending services, and admin routes to accept an authenticated credential context rather than `device_id`.
4. Make vending firmware identify its business machine only through a server-authorized configuration/association; do not use a machine ID as proof of identity.
5. Update migrations and every SQL read/write/export/backup/restore query in one coordinated change.
6. Update WebUI tables, API docs, demo payloads, firmware provisioning/heartbeat/balance lookup, and installer instructions.
7. Remove MAC-derived identity generation and stop printing raw API response bodies to serial output. User-facing output uses generic product roles only; do not publish exact hardware type/model/component details.
8. Remove stale tests/docs/examples and add a repository-wide forbidden-reference check with an explicit allowlist for historical migration commentary only. No active schema, contract, code, UI, firmware, export, installer or routine operational output may use `device_id`.

## Acceptance gates

### Database
- Fresh install and every supported legacy upgrade path migrate successfully on disposable databases.
- No active table has a `device_id` column and no active index, trigger, view, query, or migration path depends on it.
- Integrity check passes; foreign-key check returns no rows.
- Row counts and all financial totals reconcile; account balances match the ledger.
- Backup/restore round-trip passes and restored DB is usable.
- Production data has not been touched during development verification.

### API and security
- Missing/invalid/revoked key is rejected.
- Client-supplied identity cannot elevate authorization or select another device scope.
- Credential type/scope comes from the server-side validated credential.
- Logs and error responses do not expose raw keys, MACs, old identifiers, or hardware details.

### Features
- Cashier deposit with operator PIN and member PIN; read-only balance lookup; withdrawal with ledger/authorization; NFC registration and transaction idempotency.
- Vending product image upload (2 MiB max), name, price, stock, slot, NFC promo 0%, QRIS promo 0%, purchase, dispense result, reconciliation/refund.
- Midtrans QRIS server-side configuration with separate sandbox/production settings; no secrets committed.
- Reports, backup/restore, audit and 12-month retention/archive-before-purge preserved.
- Firmware builds, server tests, packaging checks, installer/fresh install, and workflow path filters all verified.

### Hardware confidentiality
- No exact hardware model/type/family or component map in user-facing UI, API errors, serial output, installer output, routine logs, public workflow output/artifacts, demo text, or operator documentation.
- Firmware build internals may retain definitions required for compilation, but must not echo those details into operational output.

## Explicit non-goals

- No destructive production migration or live VPS changes during design/CI.
- No deletion of transaction history to simplify the schema.
- No use of MAC address, serial number, or a client-generated identifier as an authentication substitute.
- No merge to `main` until all required gates are evidenced as passing.


## Implementation progress note (2026-10-24)

- Device registration must not accept or validate `hardware_id` or `mac_address`; activation is based on the pre-provisioned server-issued key only.
- The active implementation still contains legacy registry identifiers and vending associations. Those remain implementation work, not accepted exceptions.
- No runtime tests or firmware builds are run during the code-change phase, per project instruction.


## Implementation progress note (2026-10-24, continued)

- ESP32 registration and heartbeat now send device type plus the server-issued key only. Cashier NFC registration and balance lookup have key-only request paths; cashier payment requests no longer include a device identifier.
- Vending setup no longer derives its business machine ID from MAC. Setup accepts the configured Machine ID; the server binds the first valid vending key to that machine and enforces that binding for vending transactions.
- Added migrations to remove the vending-machine device association and the device registry hardware/MAC columns.
- Remaining before the no-device_id acceptance gate: remove the legacy device_id primary key and all active dependent references in registry/events/rate limits/NFC registration/cashier deposits, update WebUI and administrative APIs, remove compatibility endpoints, and align test contracts. No tests/builds/workflows have been run.