# Firmware v2

New cashier and vending firmware must target the v2 API contract only.

Device identity contract:
- `hardware_id`: stable physical identity generated on-device and normalized to the documented format.
- `registry_id`: server-side record identifier, received from provisioning when applicable.
- `device_key`: secret used for authenticated requests; never print it to serial logs.
- No `device_id` field or compatibility alias is permitted.

Firmware implementations will be added after the API contract and authentication flow are tested.
