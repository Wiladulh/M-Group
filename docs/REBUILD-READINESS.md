# M-Group Rebuild Readiness

**Target branch:** `rebuild/clean-room-v2`  
**Main branch:** intentionally untouched; do not merge during the rebuild.  
**Status:** clean-room rebuild implementation in progress; not release-ready. Per current project instruction, defer builds/tests/Actions until all scoped feature implementation and integration work is complete.

## Why the current CI is red

Latest audited commit before this document: `a2b42e8ef75edfa5632676cde2206d9c0098b584`.

- Test workflow: failed at `pytest -q`: https://github.com/Wiladulh/M-Group/actions/runs/40109723851
- ESP32 Cashier build: passed: https://github.com/Wiladulh/M-Group/actions/runs/40109723969
- ESP32-S3 Vending build: passed: https://github.com/Wiladulh/M-Group/actions/runs/40109723871

Failure classes from the test log:

1. **Schema/application mismatch:** runtime routes and `DeviceManagementService` still query `device_registry`, while the canonical schema no longer creates it. This produces broad `no such table: device_registry` failures.
2. **Legacy identity contract in tests:** tests still insert/query `device_id` in vending machines, cashier deposits, and old device registration flows. Those assertions conflict with the agreed removal of `device_id`; do not restore the legacy column just to make these tests pass.
3. **Device-event assumptions:** some tests still expect the removed device-events table/index.
4. **PIN contract drift:** payment/vending unit tests call NFC payment paths without the PIN now required by the service. The rebuilt tests must state the intended PIN/authentication contract explicitly rather than weakening payment authorization to silence failures.
5. **Firmware contract drift:** several tests assert the old `DEVICE_ID`/device endpoint protocol, while firmware and server code are mid-transition.

The two firmware workflows passing proves the firmware builds compile; it does **not** prove the server, firmware protocol, or transaction flows integrate correctly.

## Non-negotiable rebuild decisions

- Keep work on `rebuild/clean-room-v2`; do not merge to `main` until all feature implementation is complete, the full test/release gates pass, and the repository owner explicitly approves.
- Remove `device_id` from active application contracts, schemas, firmware, test fixtures, examples, and documentation.
- Use the device key as the authentication secret. Do not treat a client-supplied identifier as authentication.
- If a stable physical identity is required for hardware routing, define one explicit canonical hardware identity and its lifecycle. Do not silently reintroduce `device_id` under another name or duplicate identity columns.
- Preserve financial ledger, payment transaction, vending transaction, idempotency, backup/restore, and audit integrity. Schema changes must be forward migrations and must not silently discard financial records.
- Product images are part of the vending product model/UI: editable product name, price, stock, image upload (max 2 MiB), NFC promotion and QRIS promotion fields. Promotions remain 0%/inactive until explicitly implemented.
- Do not claim readiness based only on compilation. Require schema, API, transaction, firmware-contract, backup/restore, and UI tests.

## Rebuild sequence and exit gates

### 1. Freeze and inventory
- Record current branch/commit and preserve the current state.
- Inventory all routes, services, migrations, firmware contracts, UI calls, and tests that reference `device_id`, `device_registry`, device events, and device-key authentication.
- Mark each reference as remove, replace with canonical hardware identity, or retain only as an explicit legacy-data migration input.

**Gate:** every occurrence has an owner and intended action; no ambiguous identity semantics remain.

### 2. Establish canonical schema and migration policy
- Define the canonical identity/authentication model before rewriting endpoints.
- Make fresh-install migrations deterministic and repeatable.
- Make legacy upgrades safe and idempotent; preserve ledger and transaction rows.
- Add tests for clean install, repeated migration, legacy upgrade, foreign keys, and SQLite integrity.

**Gate:** migration suite passes on a clean database and a populated legacy fixture.

### 3. Rebuild backend contracts
- Rebuild device-key authentication and registration/heartbeat only around the approved canonical identity.
- Align cashier deposit, NFC payment, vending purchase/dispense/reconciliation, and admin routes with the same contract.
- Preserve idempotency and transaction atomicity; require the intended PIN checks for NFC payments.
- Remove orphaned device-event and device-registry queries rather than hiding errors with broad exception handling.

**Gate:** API tests pass for allowed and denied authentication, duplicate requests, lost responses, insufficient funds, failed dispense/refund, and transaction reconciliation.

### 4. Rebuild firmware and WebUI together
- Keep cashier and vending firmware request headers/payloads aligned with the API contract.
- Update WebUI device/machine management and product editing to the canonical model.
- Support per-product image upload with a strict 2 MiB limit and safe file validation.
- Display NFC/QRIS promotion values as 0% until promotion execution is implemented.

**Gate:** contract tests cover both firmware targets and all product editing fields; image size/type rejection is tested.

### 5. Audit and release gate
- Run all unit/integration tests, static checks, both firmware builds, migration tests, and workflow checks.
- Search the entire active branch for prohibited `device_id` references; classify any remaining mentions as historical migration/test documentation only.
- Review changed files and data-loss risk; only then consider merge.

**Gate:** all required checks green, no unexplained failures, and explicit review of financial-data preservation.

## Immediate next work

Start with the canonical identity decision and schema inventory, then update backend, migrations, tests, firmware, and UI as one coherent change set. Do not patch the old tests by recreating the removed `device_id` column or restoring old authentication semantics.
