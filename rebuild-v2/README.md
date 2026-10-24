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

Clean-room workspace created. Feature implementation and acceptance testing are not yet complete.
