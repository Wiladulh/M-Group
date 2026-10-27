# Rebuild Feature Gap Audit — 2026-10-27

Branch: `rebuild/clean-room-v2`
Repository: `Wiladulh/M-Group`
Scope: review against the M-GROUP WebUI V2 / device-local WebUI specification supplied on 2026-10-27.

## Evidence reviewed
- `app/api/routes.py` (current rebuild branch)
- `app/webui/index.html`, `app/webui/assets/js/app.js`, `app/webui/pages/audit.html`
- `esp32/cashier/README.md`, `esp32/vending/README.md`
- `README.md`, `docs/WEBUI-CORRECTIONS.md`

This is a source-level gap audit, not a claim that the complete test suite or physical hardware passed. Previously passing checks should not be rerun unless a relevant code change invalidates them.

## Already evidenced in source (do not re-implement blindly)
- Admin login/session checks and same-origin protection exist.
- Server-issued device keys use a cryptographically random token; the server stores a SHA-256 digest and returns the key once on the provisioning path.
- Device heartbeat authenticates by key and checks device type/status.
- NFC card registration/revocation endpoints exist; duplicate/invalid binding handling is delegated to the member service.
- Cashier payment firmware documents PIN masking, idempotency keys, persisted pending transaction state, and no persistence of member PIN.
- Vending/cashier firmware documents a local setup portal and stores the device key in ESP32 NVS.
- Dashboard API already returns most-used vending based on completed vending transactions for a relative period.
- Native backup/restore and XLSX-related functionality are documented and exposed in the audit UI.

## Gaps or items requiring focused verification / implementation

### P1 — Member-bound NFC registration via selected cashier
The current WebUI member table renders “Daftar/Ganti NFC”, while the API exposes direct member NFC-card registration. The supplied workflow requires selecting an available cashier and conducting a time-limited server-controlled session on that specific terminal, including scan → PIN → Enter → server result. The routes contain registration request models, but the visible UI/API path must be traced end-to-end before this can be marked complete. Do not treat direct UID entry as equivalent. Ensure registration sessions bind immutable member ID + authenticated cashier identity, expire, reject replay, and never log UID/PIN secrets unnecessarily.

### P1 — Local WebUI requirements vs actual firmware portal
The README describes a setup portal at 192.168.4.1 on a temporary access point, not proof of a configuration portal reachable via the device's current DHCP address. The specification explicitly requires WebUI access on the DHCP LAN address, a local WebUI PIN (default 19929900 with forced-change warning/flow), persistent PIN changes, connection status, and Asia/Jakarta time synchronization. Inspect firmware implementation before asserting these are met. If the current setup AP is the only UI, implement the LAN portal and protect it without exposing device credentials.

### P1 — Secure device key lifecycle
Provisioning generates one-time keys, but verify there are admin UI controls and server APIs for revoke/rotate, and that revocation immediately blocks device operations. Do not re-display stored key material. Provisioning must collect device type and location without requiring a manually typed device name; machine location metadata and device registry location need a coherent mapping.

### P1 — Product image pipeline and catalog synchronization
The reviewed API source imports image-related libraries only indirectly/not visibly in the inspected paths; focused search found no clear image upload/compression or catalog version/hash implementation. Verify product image upload enforces 2 MiB at both request and decoded image levels, validates actual image bytes, resizes/compresses safely, preserves old image on failure, and provides stable asset hash/version. Firmware must fetch only changed assets and atomically retain the last valid catalog. If firmware cannot support images yet, document that as a concrete remaining requirement rather than a completed feature.

### P1 — XLSX report scope and period correctness
The current audit UI exposes source (ALL/CASHIER/VENDING), period (day/week/month), payment method, and a single date. The supplied specification additionally requires top-up-only reports, all-transaction report, selected device/all devices, last 7 days, one-month definition, and manual inclusive start/end date range in Asia/Jakarta. Verify exported content is a genuine XLSX workbook, correct statuses and ledger references are included, failed/cancelled rows are separated from successful revenue, and filenames follow the agreed collision-safe sequence pattern. Native backup remains distinct from report export.

### P2 — Dashboard product sales and location
The API already computes most-used vending from completed transactions, but the visible return fields should be verified for machine location and the UI's selected period. The reviewed dashboard response did not show an explicit best-selling product aggregation in the inspected section. Add a production aggregation based on completed sale line items/quantities, with product name, units, revenue, period, and optional image; exclude pending/failed/cancelled transactions. Avoid deriving rankings from static demo data.

### P2 — Member Registry and top-up UX
The current production member table contains “Koreksi Top Up” and the API supports audited corrections. That is not the same as an ordinary “Tambah Saldo” control; preserve correction/reversal controls if financially necessary, but ensure normal top-up exists only in Financial Core and is idempotent. Confirm the current UI does not show a cashier column between NIK and credentials. Reference/note should be optional; do not remove meaningful financial approval controls without checking policy.

### P2 — Transactions search and cross-links
Verify the transaction screen supports period, member, device, type, status, and transaction-ID filters; distinguishes pending/failed/cancelled/refunded from completed; and links related ledger records where supported. Dashboard recent rows alone do not satisfy the full transaction history requirement.

### P2 — Timezone and financial invariants
The README says audit supports day/week/month, but timezone and boundary semantics need explicit validation. Use Asia/Jakarta for report boundaries, UTC storage for timestamps, and one documented meaning for “1 month”. Check ledger balance remains authoritative and top-up/debit/stock updates are atomic/idempotent. Do not rerun unrelated previously passing CI jobs; run affected tests after changes.

## Suggested implementation sequence
1. Trace the current cashier-bound NFC registration endpoints, UI handlers, schema, and firmware protocol; close the end-to-end workflow.
2. Inspect local portal source for DHCP LAN access, local PIN, persistence, and NTP/timezone; implement missing requirements per firmware capabilities.
3. Complete server-side product image upload/optimization and catalog version/hash, then device differential/atomic sync where supported.
4. Extend report filters and workbook generation to match report types, date ranges, timezone, filenames, and revenue status rules.
5. Add/verify best-selling product aggregation and expose machine location in most-used vending.
6. Audit transaction filters, member/top-up UX, key revocation/rotation, and backup restore safeguards.
7. Run only relevant tests for changed components; run the final full suite once the rebuild is ready. Physical NFC/keypad/DHCP/network interruption tests remain explicitly pending until performed on real devices.

## Release gate
Do not merge while any P1 is unresolved, any financial invariant lacks test evidence, any report export has not been reopened/validated as XLSX, or any physical-device behavior is described as passed without real-device evidence.

## Implementation progress on 2026-10-28 (source changes only; no tests/build run)

- Added the admin role migration and server-side role-aware account lifecycle: super-admin account creation/status changes/password reset, session revocation on disable/reset, active-account session validation, and a read-only auditor guard.
- Restricted high-impact operations to super admins, including device provisioning/rotation/revocation, member NFC/PIN and top-up corrections, direct financial credit/debit, vending/product/promotion configuration, payment administration, and backup/export-import recovery actions. Device revocation now writes an audit event.
- Added a super-admin UI flow to reset another admin's password; account password changes now require at least 12 characters.
- NFC registration/replacement now requires choosing an active cashier in the WebUI and binds the server session to that cashier's key fingerprint. The server rejects missing/unavailable cashier selection; the five-minute expiry and cashier-side device-key authentication remain in place.
- The shared ESP32 device portal now requires the local PIN for both cashier and vending, exposes the PIN-change form for both, and blocks saving while the default PIN is active. The DHCP LAN WebUI remains available after Wi-Fi configuration; the setup AP remains the recovery path.
- Audit XLSX filenames include a unique suffix to avoid concurrent exports overwriting each other. Device pre-registration status is now accepted by device management.
- These changes have **not** been built or tested, per the project owner's instruction to defer testing until implementation is complete.

## Remaining implementation gap before the final test phase

- The server/WebUI product image upload path validates and optimizes images and provides SHA-256 versioned URLs, and the vending firmware caches the catalog JSON by hash. However, the current vending firmware does not yet download and atomically cache the image assets themselves. This remains open and must not be marked complete.
- Finish the remaining source-level integration review and implementation items before any test/build run. Physical NFC, DHCP/LAN portal, transaction recovery, key revocation, and image sync still require their later acceptance tests.
