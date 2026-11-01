# M-Group — Clean-room Rebuild v2

This directory is the new implementation boundary for M-Group. Everything outside `rebuild-v2/` is legacy/reference material and MUST NOT be imported, copied wholesale, or treated as runtime code for v2.

## Non-negotiable rules

1. No `device_id` field, variable, API property, database column, or firmware protocol field in the new implementation.
2. Use `registry_id` as the server-side registry record identifier and `hardware_id` as the stable physical-device identity. They are different concepts.
3. Fresh-install schema is the source of truth. No compatibility migrations for the legacy schema are included in v2.
4. New modules must have explicit contracts and tests before integration.
5. Keep the existing application and its workflows untouched while v2 is developed in parallel.
6. Never migrate or overwrite production data as part of local/CI tests.
7. No merge to `main` until the v2 acceptance checklist is complete and the owner approves it.

## Initial structure

- `docs/DOMAIN-CONTRACT.md` — vocabulary and invariants
- `docs/ARCHITECTURE.md` — boundaries and data flow
- `db/schema.sql` — clean-install schema
- `backend/` — new backend implementation
- `tests/` — v2-only tests
- `firmware/` — new device protocol and firmware contracts
- `webui/` — new web UI implementation
- `ops/` — deployment and environment templates

## Development order

1. Lock the domain contract and database schema.
2. Implement configuration, database access, and health endpoints.
3. Implement device registration/authentication using only `hardware_id`, `registry_id`, and device keys.
4. Implement transaction, member/NFC, vending, cashier, and financial ledger services with tests.
5. Implement WebUI against documented API contracts.
6. Implement firmware against the same protocol contract.
7. Add CI checks for Python, schema invariants, API contract, WebUI, and firmware.
8. Run clean-install and end-to-end acceptance tests before cutover.

## Status

The v2 source includes the Server WebUI username/password login with HttpOnly session cookies, password change, Member edit and NFC enrollment/replacement, Admin-only WebUI top-up, product image upload and device-authenticated image delivery, device management, ledger/audit views, and native backup/restore. Member transaction PINs are stored as salted PBKDF2 verifiers and are required by both Cashier and Vending payment routes. Top-up has no Cashier/Vending endpoint or device PIN flow. Cashier firmware uses ESP32, SSD1306 I2C OLED, RC522, and 4x4 keypad; Vending firmware uses its separately defined hardware profile and image cache.

Regression coverage includes Admin session controls, Member/NFC/PIN flows, Cashier and Vending payments, top-up idempotency, ledger reconciliation, image delivery, WebUI contracts, and card replacement. Additional tests now explicitly guard Member PIN preservation on NFC card replacement and the Admin-only top-up boundary.

**Validation is not yet release approval:** the latest source changes have not been confirmed by a completed CI run in this session. Both PlatformIO targets must compile, the full v2 Python test suite must pass, and WebUI/browser, installation, backup/restore, and physical-device acceptance must be recorded. Do not merge to `main` or deploy until those gates pass and the owner approves.

## Simplified actors and deferred features

Only two actor categories are supported: one Admin super-admin account for WebUI management, and Members as transaction clients with sequential server-generated `UID-00001` identifiers. Operator and auditor roles, operator PINs, and operator-to-cashier bindings are removed. Pertamini and loan features are deferred and excluded from active navigation and runtime scope.
