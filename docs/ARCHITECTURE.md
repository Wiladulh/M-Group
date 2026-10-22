M-Group is a portable Linux application. Domains: core/runtime, identity, financial ledger, NFC payment, loans, vending, device protocol, API, WebUI, installer and CI/CD. Production instance data remains outside the source repository.


## Device authentication and public API contract

- The server-generated Device Key is the sole device authentication credential. Firmware registers, heartbeats, reads its Vending catalog, and completes Cashier NFC work through key-authenticated endpoints; no public route requires a Device ID.
- Database primary/foreign keys remain implementation details only. Device lists, dashboards, transaction reports, audit responses, and NFC session responses must not serialize those internal keys.
- Admin WebUI device management targets a provisioned device through its non-secret key hint. A hint collision is rejected as ambiguous rather than choosing a device arbitrarily.
- Legacy endpoints that accepted a caller-supplied Device ID for provisioning, heartbeat, device events, or Cashier NFC work are removed. Rotate/revoke access by changing the stored key hash/status through the authenticated admin workflow; a disabled device key must be rejected immediately.
