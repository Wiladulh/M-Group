# WebUI v2

This directory contains the active M-Group v2 WebUI: a cleaned page layout and CSS system with a v2 API client. The WebUI is served by the v2 backend on the same origin. Source wiring is not a substitute for browser and end-to-end acceptance testing.

- Main navigation retains dashboard, member, finance, payments, vending/inventory, cashier, devices, audit/backup, and settings.
- Pertamini and loan modules are deferred and absent from active navigation and runtime screens.
- Do not reintroduce old API endpoints, legacy identity fields, or mocked success responses.
- Active screens use versioned v2 API contracts with explicit loading, empty, success, and error states.
- Follow `../docs/WEBUI-SPEC.md` and `../docs/DOMAIN-CONTRACT.md`.

## Current v2 wiring

The WebUI is now wired to the v2 backend through `assets/js/api.js` and `assets/js/app.js`; it does not use legacy `/api/v1` calls.

- Member create/update uses `POST /api/v2/members` and `PATCH /api/v2/admin/members/{member_id}`. Member rows expose Edit, Daftar/Ganti NFC, Reset PIN, and Kartu actions.
- NFC registration requires an active Cashier registry selection. The server binds the registration session to that selected Cashier; the page polls session status and never displays raw card UID or member PIN.
- Product image upload uses the v2 admin endpoint; the server returns a bounded JPEG thumbnail digest, and the device downloads through the separate Device-Key authenticated v2 image route.

The client still requires final browser/API regression validation. Static HTML/demo previews are not proof of backend operation.
