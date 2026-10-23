# M-Group Rebuild — Baseline Audit (2026-10-23)

Status: initial repository/source audit; no runtime tests, firmware builds, VPS access, or production database inspection claimed.
Target branch: `rebuild/clean-foundation`
Baseline: `main`
Master contract: `docs/REBUILD_MASTER_SPEC.md` on this branch; latest decisions are recorded in Section 21, which supersedes the stale Section 20.

## Repository and branch state

- Existing repository `Wiladulh/M-Group` is retained.
- Created branch `rebuild/clean-foundation` from `main`; master specification copied into this branch and reconciled before implementation.
- The master specification was not found on `main` at the expected path; it existed on `docs/rebuild-master-spec`.
- Branch inventory returned multiple historical feature/fix branches, including several competing device-ID and device-key branches. They are not interchangeable sources of truth; use `main` as rebuild baseline and selectively port behavior only after review.
- Pull-request search returned open/previous work including #38 (device-key-only refactor), #37 (product images/Nasabah savings account), #36 (Origin protection), #35 (legacy admin-token test auth removal), #34 (session authentication), and earlier branches. Search metadata did not reliably expose all states, so verify current PR/run state directly before relying on it.

## Confirmed source findings on `main`

### API/backend

- `app/api/routes.py` still declares `device_id` on payment and vending request models and implements device registration/provisioning/heartbeat routes.
- The registration request still accepts `hardware_id`, `mac_address`, and `device_key`.
- `app/device/protocol.py` defines a `DeviceEvent` dataclass with `device_id`.
- `app/device/management.py` uses `device_registry.device_id` and returns device identifiers in management records.
- `app/vending/service.py` associates vending machines with a `device_id`.
- `app/payment/service.py` still accepts device identity in a payment path.
- These observations prove the latest “remove device_id permanently” contract is not yet implemented throughout the baseline.

### Database and backup/export

- Migrations under `app/migrations/` are the canonical migration location according to current packaging workflow, but at least one NFC-registration migration and transaction/export SQL still refer to `device_id`.
- `app/core/backup.py` includes device identity in Cashier, Vending, and payment export queries. Rebuild must remove the field from active schemas and exports without discarding transaction history or creating destructive automatic migration.
- Existing database migration code contains special-case schema alteration/rebuild logic. It requires migration-by-migration review and disposable database tests before any production use.

### WebUI and demo

- Production WebUI assets are served from `app/webui/index.html`, `app/webui/pages/`, and `app/webui/assets/`; the UI includes a Management M-Group shell and session-based admin login.
- Demo artifacts include `demo/demo2.html`, `demo/demo4.html`, and `demo/demo-new.html`. They are simulation artifacts, not proof of backend/API behavior. Compare all tabs and agreed workflows against production UI before claiming feature parity.
- The user-required product row fields are image/upload, name, price, stock, NFC promo and QRIS promo. Product images must remain limited to 2 MiB and both promo fields must remain 0% until formally enabled.
- Do not expose hardware model/family names or exact hardware type identifiers in user-facing UI, API error text, demo text, installer output, logs, workflow logs/artifacts, or operational documentation. Use neutral labels such as “Cashier”, “Vending”, or “Perangkat M-Group” where appropriate. Keep internal build target details only where technically necessary and avoid echoing them in published artifact names/output.

### Firmware

- Firmware exists separately under `esp32/cashier/` and `esp32/vending/`, with shared setup portal code under `esp32/common/`.
- Both firmware programs currently construct `DEVICE_ID` from the full network MAC, submit registration payloads with hardware/MAC metadata, and include the ID in heartbeat paths. The shared configuration portal also creates the ID from MAC and tells the operator that the ID is generated automatically.
- Serial logs currently echo raw registration/heartbeat response bodies. Replace this with sanitized status/error codes so unexpected API responses cannot leak identifiers, hardware details, or secrets.
- Firmware work must retain key-only authentication, secure NVS storage, bounded retries/idempotency, balance lookup, payment/deposit flows, vending catalogue/product images, dispense-result reporting, and recovery behavior. Compilation alone does not validate physical operation.

### Installer and GitHub Actions

- `installer/install.sh` supports system/user installs, distro package-manager bootstrapping, configurable paths, and service setup. Review it for safe upgrades, permissions, secret handling, rollback, and neutral operator output.
- `.github/workflows/test.yml` runs pytest, builds a wheel, and verifies packaged WebUI/migration resources.
- `.github/workflows/esp32-cashier.yml` and `.github/workflows/esp32-vending.yml` build separate firmware artifacts. Their current path filters include API/service/migration-related code paths in part, but must be checked against the full changed contract surface after rebuild.
- Workflow definitions were inspected, but current latest run/job status could not be independently retrieved using the connected GitHub actions functions available in this audit. Do not infer a pass/fail state; inspect live runs before merge.
- No test suite or firmware build was run during this baseline read-only inspection.

## Mandatory rebuild order

1. Reconcile the master specification (completed in Section 21 on the rebuild branch).
2. Inventory every `device_id` dependency across application, migrations/schema, API contracts, WebUI/demo, firmware, installer/config, tests, logs, reports, backup/restore, and docs. Distinguish only legitimate business `machine_id` usage.
3. Design a non-destructive schema/data migration for disposable test databases first; preserve transaction/audit relations without keeping a hidden hardware ID.
4. Implement backend/database/API and tests as one coherent contract.
5. Update WebUI and demo parity; preserve all agreed tabs and financial workflows.
6. Update both firmware programs and setup portal; sanitize serial output and operational artifacts.
7. Update installer, packaging, workflow path filters, documentation, backup/export, and release checks.
8. Run server tests/wheel checks and both firmware builds; then test migration/backup/restore on disposable databases and perform browser/fresh-install/hardware acceptance where available.
9. Review diff, verify latest CI and all acceptance criteria. No merge to `main` before these gates pass.

## Hardware confidentiality acceptance

- User-facing type labels are limited to generic product roles.
- Do not emit exact board/model/component names, hardware-family identifiers, or detailed pin/component mapping in operator UI, API errors, installer output, operational logs, or release artifacts.
- Raw device responses are not logged.
- Source/build internals may retain technical definitions necessary to compile firmware, but public output and routine operations must not reveal the confidential hardware type.
