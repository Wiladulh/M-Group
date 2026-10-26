# Firmware v2

New cashier and vending firmware must target the v2 API contract only.

Device identity contract:
- `hardware_id`: stable physical identity generated on-device and normalized to the documented format.
- `registry_id`: server-side record identifier, received from provisioning when applicable.
- `device_key`: secret used for authenticated requests; never print it to serial logs.
- No `device_id` field or compatibility alias is permitted.

V2 backend endpoints currently include `POST /api/v2/cashier/payments`, `POST /api/v2/cashier/top-ups`, `POST /api/v2/devices/member-balance`, `GET /api/v2/device/products`, `POST /api/v2/vending/purchases`, and `POST /api/v2/vending/transactions/{transaction_id}/dispense-result`.

Firmware implementation remains an open release blocker. Port the existing cashier and vending state machines to these v2 routes, persist the same `request_id` across retries/reboots, and do not clear pending NVS transaction state until the server response is reconciled. Never persist PINs or print device keys.
