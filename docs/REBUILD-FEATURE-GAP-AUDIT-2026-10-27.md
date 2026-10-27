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
**Implemented in source; validation pending.** The member WebUI selects an active cashier, sends its hardware identity to the start/replacement endpoint, and the server binds the five-minute session to that device's stored key fingerprint. The cashier still authenticates every polling/progress/completion call with its device key. The server rejects missing/unavailable cashier selection, and the existing completion path verifies the member PIN and duplicate card binding. Do not treat this as hardware-tested until the final acceptance phase.

### P1 — Local WebUI requirements vs actual firmware portal
**Implemented in source; validation pending.** The shared portal runs on port 80 after Wi-Fi connection (therefore reachable at the current DHCP address), retains the temporary 192.168.4.1 setup AP as a recovery path, requires a salted local PIN for both Cashier and Vending, warns about the initial PIN 19929900, and blocks saving while the default PIN remains. The status view includes connection/RSSI, server/TLS state, local time, catalog and image-cache status. Confirm the real DHCP address and PIN behavior on physical devices during acceptance testing.

### P1 — Secure device key lifecycle
**Implemented in source; validation pending.** Super-admin-only provisioning, one-time key display, rotation, and revocation are available. Rotation replaces the stored key digest; revocation disables/deletes the device record and writes an audit event. The WebUI hides device-management controls from non-super-admin roles. Provisioning collects type and installation location, and the generated device identity is bound through the server registry. Verify immediate key rejection after rotation/revocation during acceptance testing.

### P1 — Product image pipeline and catalog synchronization
**Implemented in source; validation pending.** Upload accepts source images up to 2 MiB, validates decoded image bytes and dimensions, optimizes a thumbnail to at most 64 KiB, and exposes SHA-256 versioned URLs. Vending firmware downloads only changed image hashes, verifies the downloaded digest, and uses temporary/backup file renames to preserve the last valid asset on failure. An OTA-compatible partition layout reserves LittleFS for five thumbnails. Confirm actual app-slot size, partition fit, image downloads, and power-loss recovery in the final firmware validation phase.

### P1 — XLSX report scope and period correctness
**Filters implemented in source; workbook validation pending.** Audit and export support ALL/CASHIER/VENDING/TOPUP, day/week/calendar-month/custom inclusive date range, payment method, device, member, status, and transaction ID. Report boundaries convert Asia/Jakarta local dates to UTC against UTC-stored timestamps, and export names include a unique suffix. Before release, reopen generated XLSX files and confirm workbook content, status visibility, and reconciliation columns. Native backup remains distinct from report export.

### P2 — Dashboard product sales and location
**Aggregation implemented in source; validation pending.** The dashboard API returns most-used vending with location and best-selling products grouped from completed vending transactions, including product name, units sold, revenue, machine/location, and image URL/hash where available. Confirm the selected analytics period and ensure pending/failed/cancelled transactions do not enter rankings during the final validation phase.

### P2 — Member Registry and top-up UX
**Implemented in source; validation pending.** Normal top-up/debit is available in Financial Core with an idempotency key and ledger write; audited top-up correction remains a separate super-admin operation. Member tables show NIK and NFC credential status without an intermediate cashier column. Verify financial balances against the ledger and review reference/note behavior during the final financial audit.

### P2 — Transactions search and cross-links
**Search filters implemented in source; validation pending.** Audit report and XLSX export now share period/date-range, source/type, payment method, device, member ID, status, and transaction-ID filters. Status options distinguish completed, pending, authorized, failed, cancelled, refunding, refunded, and created. Cross-links to ledger records remain limited by the available transaction schema; verify reconciliation references during final audit.

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

- The server/WebUI accepts source images up to 2 MiB, optimizes thumbnails to at most 64 KiB, and provides SHA-256 versioned URLs. The vending firmware now downloads changed assets only, verifies SHA-256, and uses temporary-file/backup renames for replacement; failed downloads retain the previous asset. An OTA-compatible partition layout reserves LittleFS for the five thumbnails. These source changes are not yet built or tested, and firmware size/partition fit and image-cache behavior must be confirmed in the final firmware validation phase.
- Finish the remaining source-level integration review and implementation items before any test/build run. Physical NFC, DHCP/LAN portal, transaction recovery, key revocation, and image sync still require their later acceptance tests.
