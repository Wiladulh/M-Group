# WebUI v2

This directory contains a cleaned copy of the legacy WebUI's HTML page layout and CSS visual system. The previous `app.js` implementation was **not** retained: it was coupled to legacy API assumptions and has been replaced with a minimal v2 bootstrap. The UI is not production-ready and does not claim that login, NFC, finance, inventory, or device actions are live.

- Main navigation retains dashboard, member, finance, payments, vending/inventory, cashier, devices, audit/backup, and settings.
- A dedicated Pertamini section is present as a non-operational placeholder until the approved Pertamini agreement/specification is recovered and transcribed.
- Do not reintroduce old API endpoints, legacy identity fields, or mocked success responses.
- Build each screen against versioned v2 API contracts with explicit loading, empty, success, and error states.
- Follow `../docs/WEBUI-SPEC.md` and `../docs/DOMAIN-CONTRACT.md`.
