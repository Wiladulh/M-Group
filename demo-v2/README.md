# M-Group WebUI Demo v2

This is a browser-only UX demo aligned to the current clean-room rebuild v2 contract. It is intentionally separate from the production WebUI and does not call the server or physical devices.

## Open

Open `index.html` in a browser, or serve this directory with any static HTTP server.

Demo login:
- Username: `admin`
- Password: `MGroupDemo!2026`

The demo keeps a tab-scoped session marker for up to eight hours. It does not persist the password or use an Admin API Token for login. Password changes are local simulations only.

## Rebuild v2 alignment

- Admin username/password login, single WebUI session, logout, and password change (current password + new password twice; 12-character minimum).
- Member IDs follow the server format `NTR-00001`, allocated sequentially in the demo.
- Member creation is separate from NFC enrollment. Each member row has Edit and Daftarkan NFC actions.
- NFC enrollment selects a Cashier, simulates the cashier-side card scan and PIN verification, and does not request a raw UID or PIN in the WebUI.
- Financial Core top-up uses the same conceptual fields as `TopUpRequest`: unique request reference, member ID, amount, and description. There is no extra source-of-funds selector.
- Member balance changes are demonstrated only through the top-up action; arbitrary manual ledger posting is hidden.
- Vending keeps exactly Product ID 1–5 per machine, with machine-scoped catalog and stock.
- Product image selection accepts PNG/JPEG/WEBP up to 2 MiB in the browser demo. Production uses the v2 upload endpoint and server-side content validation; firmware image synchronization is not simulated as real.
- NFC and QRIS promotions remain 0% and inactive.
- Pertamini remains a non-operational placeholder pending the agreed safety/operational contract.
- Cashier, Vending, device registry, payment history, audit, reporting, and settings screens use sample data only.

## Important limitation

All balances, transactions, statuses, NFC events, product edits, image previews, reports, and audit entries are local illustrative data. They are not persisted to the server, do not represent real money, and do not command a physical Cashier or Vending device. A successful action in this demo is never evidence that the production API/firmware flow has passed.

## Validation

- JavaScript syntax checked with the JavaScript parser.
- Static checks cover navigation/page IDs, Member ID format, fixed five Product IDs, demo-only labeling, and the absence of manual UID/PIN entry in the NFC flow.
- No browser end-to-end test or physical-device test is claimed.
