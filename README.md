# M-Group

Modular membership, financial ledger, payment, cashier and vending platform.

This repository contains the server API, WebUI, database migrations, ESP32 cashier and vending firmware, installer, documentation, and automated tests.

## Minimum system requirements

M-Group targets lightweight Linux systems and is designed to run with:

- 2 CPU cores minimum
- 315 MB RAM minimum
- Python 3.10 or newer
- SQLite3
- POSIX shell for the installer

The application does not require a specific Linux distribution, hostname, IP address, username, home directory, init system, or hardware platform.

## Source and build

GitHub is the source of truth. GitHub Actions builds and tests the project.

The installer is distribution/init-system agnostic. Systemd, OpenRC, or another service manager may be configured separately; the application itself does not depend on one.

Production databases, credentials, secrets, instance configuration and test data must not be committed.


## Transaction and audit model

Operational transactions are separated by source:

- **CASHIER**: savings deposits and cashier NFC payments.
- **VENDING**: vending purchases, dispense results and refunds.
- The server is the source of truth; ESP32 is not the primary transaction archive.
- Operational transaction retention is **12 months** on the server, with backup/archive before purge.
- Audit reports support **day, week and month** filters and can be restricted to Cashier or Vending.
- Cashier savings deposits require an explicitly configured operator PIN (set during system installation or from the admin WebUI) plus the member NFC PIN. There is no shared default operator PIN.
- Native M-Group backup archives contain a database dump, manifest and checksum and may include an Excel-compatible export.
- XLSX export is intended for audit/reporting and preserves stable transaction columns.
- Excel import is validation-gated and is not the primary recovery format; native M-Group backup is the authoritative restore format.
