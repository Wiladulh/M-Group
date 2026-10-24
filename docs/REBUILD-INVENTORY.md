# M-Group Rebuild Inventory

**Branch:** `rebuild/remove-device-id-dependencies`  
**Purpose:** Record the first source-level inventory before changing runtime contracts.  
**Status:** Initial inventory; not an exhaustive clean bill of health.  
**Main:** Do not merge or modify `main` as part of this rebuild.

## Confirmed findings

| Area / file | Observed state | Required action |
|---|---|---|
| `app/device/management.py` | `DeviceManagementService` still queries `device_registry`; list/get select `hardware_id` twice and use duplicate hardware-ID predicates. | Reconcile service with canonical schema and define the device-management source of truth; remove obsolete registry dependency if schema has retired it. |
| `app/core/db.py` | Migration runner contains special-case migration logic for vending promotion hardening. | Audit all migrations for repeatability, clean-install behavior, foreign-key safety, and preservation of transaction/ledger rows. Do not treat one special-case migration as proof the migration chain is safe. |
| `app/device/protocol.py` | Device event dataclass now uses `hardware_id`. | Verify whether device-event storage/table is part of the canonical architecture; remove dead code or align schema and tests explicitly. |
| `app/payment/service.py` | Payment path accepts `hardware_id`, but persisted payment transaction writes `NULL` for that field in the inspected insert. NFC payment requires a PIN; idempotency conflicts are checked. | Decide whether transaction-to-hardware attribution is required. Preserve PIN enforcement, idempotency, and atomic ledger updates while aligning schema and tests. Never trust a client-supplied identity as authentication. |
| `app/vending/service.py` | Machine operations use `hardware_id` in the inspected paths. | Audit every machine lookup, product, dispense, refund, and reconciliation path against the canonical identity model. |
| `app/core/backup.py` | Previous code-search results on the default branch showed backup SELECTs referencing `device_id`. Branch-specific status still requires a complete audit. | Inspect branch version of every backup/restore query and test a round trip with financial records. |
| `esp32/cashier/MGroupCashier.ino` | Registration derives `HARDWARE_ID` from MAC and sends it with device type and device key; requests send the device-key header. | Audit all request payloads and all firmware-to-server contracts, including retry/idempotency behavior. |
| `esp32/vending/MGroupVending.ino` | Registration derives `HARDWARE_ID` from MAC and sends it with device type and device key; requests send the device-key header. | Audit machine assignment, product mapping, dispensing confirmation, and transaction reconciliation against the API. |
| `esp32/vending/README.md` | Documentation still uses legacy “Device ID” terminology and describes a `device_id` machine registration field, while source uses `hardware_id`. | Rewrite the documentation to the approved identity/key model after the API contract is finalized. |
| `docs/API-MEMBER-BALANCE.md` | The inspected branch version documents a request body with only `card_uid`, and device-key authentication via header. | Keep aligned with actual route behavior and verify that identity is derived from authenticated key, not client payload. |
| `docs/REBUILD-READINESS.md` | Existing rebuild gate identifies schema drift, old identity assumptions, device-event assumptions, PIN-contract drift, and firmware-contract drift. | Use its exit gates as acceptance criteria; update it only when evidence changes. |

## Identity and authentication rules

1. `device_id` must not remain an active runtime, database, API, firmware, or UI contract.
2. `hardware_id` may identify the physical unit for routing/attribution, but it is not an authentication secret.
3. Device-key authentication must resolve the registered device and enforce active status and allowed device type on every protected device endpoint.
4. Any remaining legacy identity reference must be explicitly classified as a legacy migration input or historical explanation, not an active contract.
5. Do not silently add a replacement identity column or alias that recreates the old coupling.

## Required audit passes

- [ ] Enumerate all SQL migrations and map table/column creation, alteration, and removal.
- [ ] Search the target branch for `device_id`, `device_registry`, device-event table/index names, and device-key verification paths.
- [ ] Trace all device routes from HTTP handler to authentication, service, and database.
- [ ] Trace NFC payment, cashier deposit, vending purchase, dispense report, refund, and reconciliation end to end.
- [ ] Inspect backup and restore queries against every canonical transaction/ledger schema.
- [ ] Inspect WebUI device/machine management and product editing, including image upload size/type validation and 0% promotion display.
- [ ] Inspect tests and fixtures; update assertions to the intended contract instead of restoring legacy schema.
- [ ] Run fresh-install, repeated-migration, legacy-upgrade, SQLite integrity, API, transaction, WebUI, and firmware checks.
- [ ] Review all remaining legacy references before declaring the branch ready.

## Data integrity safeguards

- Never drop or recreate financial tables without a verified data-preserving migration and populated-fixture test.
- Verify foreign keys, unique idempotency keys, transaction atomicity, and backup/restore round trips.
- Test duplicate requests and lost HTTP responses for payment and vending; retries must not double-debit or dispense twice.
- Keep NFC PIN enforcement intact; do not weaken authorization to make tests pass.
- Firmware compilation is necessary but does not establish end-to-end integration.

## Next implementation order

1. Complete the branch-specific schema/migration inventory and choose the canonical device identity model.
2. Align device registration/authentication and management routes to that schema.
3. Align payment, deposit, vending, and transaction attribution while preserving ledger integrity.
4. Align both firmware targets and WebUI with the same contract.
5. Update tests, documentation, and backup/restore paths.
6. Run the full validation matrix and review all changes before considering a merge.

This document records confirmed observations from a first-pass source inspection. It does not claim that the checklist is complete or that the repository is release-ready.
