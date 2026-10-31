# M-Group v2 Architecture

## Runtime boundaries

```text
Hardware (Cashier / Vending)
        |
        | HTTPS + device-key authentication
        v
API layer
        |
        +--> Device registry and authentication
        +--> Member / NFC / PIN service
        +--> Payment and transaction service
        +--> Vending/catalog/inventory service
        +--> Financial ledger and reporting
        |
        v
Relational database (canonical v2 schema)

WebUI ------ HTTPS API ------> API layer
Ops/CI ----- migrations/tests -> isolated test database
```

## Current package layout

- `backend/mgroup_backend`: active FastAPI runtime, configuration, SQLite access, authentication, and v2 routes.
- `db/schema.sql`: canonical clean-install schema.
- `tests`: API, schema, identity, and WebUI contract tests.
- `webui`: same-origin Admin client using the v2 cookie-session API.
- `firmware`: Cashier and Vending device protocol and firmware.
- `ops`: dedicated v2 installation and operations scripts.

There is one human administrator identity (Admin super-admin) and Member client identities. Devices authenticate independently using Device Keys; they are not human accounts.

## Dependency rules

1. API routes call domain services; domain services do not import route handlers.
2. Financial ledger is the authoritative record of money movement.
3. Device authentication is centralized; business services receive a verified device context.
4. Database access is injected/owned by service boundaries; no module silently initializes a production database.
5. Firmware and WebUI rely on versioned API contracts, not backend implementation details.
6. Tests use temporary or dedicated test databases only.
7. Legacy root-level code is not imported by v2 packages.

## Delivery gates

- Gate A: domain contract and schema reviewed.
- Gate B: clean-install database and health endpoint pass.
- Gate C: device registration/authentication contract tests pass.
- Gate D: member/NFC/PIN, payments, vending, ledger, and cashier flows pass.
- Gate E: WebUI and firmware build against the v2 API.
- Gate F: security, recovery, backup/restore, and end-to-end acceptance pass.
- Gate G: deployment rehearsal and owner sign-off.
