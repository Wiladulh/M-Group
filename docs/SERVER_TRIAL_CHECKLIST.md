# M-Group Server Trial Checklist

This checklist is for a **controlled server/API trial** from the audit branch. It is not a declaration of production readiness. Do not use it against a database that contains valuable or production data.

## Before starting

- [ ] Use a disposable test machine or a separate database path; do not point the trial at the active PMOS UF02 production database.
- [ ] Take a native backup and verify the backup file is copied off the test machine.
- [ ] Set a unique, strong admin token in the instance configuration. Do not reuse a sample/test token.
- [ ] Keep the API port private to the LAN or localhost. For remote access, use TLS and an authenticated reverse proxy/Cloudflare Access; do not expose the application port directly to the Internet.
- [ ] Ensure the service account owns the config, data, database, lock, and log paths it needs. Keep secrets and database files inaccessible to other users.

## Validate server startup and API

- [ ] Start the server using the package/service procedure for the target OS and confirm the process remains running.
- [ ] Request `GET /api/v1/health` and `GET /api/v1/system`; confirm healthy responses.
- [ ] Confirm protected admin endpoints reject requests with no token and accept the configured token.
- [ ] Confirm device endpoints reject missing/incorrect device keys.
- [ ] Open the WebUI and confirm the dashboard, members, finance, devices, vending, and audit views load without browser console errors.
- [ ] Exercise only disposable test records: member/account creation, cashier deposit with idempotency key, vending purchase, dispense failure/refund, and audit reporting.
- [ ] Retry a transaction with the same idempotency key and confirm it does not double-charge; reuse that key with conflicting transaction data and confirm it is rejected.

## Backup and restore

- [ ] Create a native backup of the disposable database.
- [ ] Restore it to the disposable instance and verify expected records, `PRAGMA integrity_check` = `ok`, and no foreign-key violations.
- [ ] With a test request/managed database connection held open, initiate restore and verify restore waits until that connection closes.
- [ ] Try a deliberately invalid archive only on the disposable instance; verify restore fails and the live database remains intact.
- [ ] Confirm backup/restore does not run while valuable production traffic is using the database.

## Upgrade, restart, and rollback

- [ ] Test installation and upgrade on a clean disposable image of the actual target OS/init system.
- [ ] Restart the service and confirm it recovers with the same configuration and database.
- [ ] Verify the service runs as the intended non-root account and can read config, write data/database/lock files, and write logs.
- [ ] Simulate a failed upgrade only on the disposable image and verify documented rollback restores the previous package and database snapshot.
- [ ] Rehearse migration from a **copy** of each supported legacy schema. Compare row counts and key identities/relationships before and after migration; run SQLite integrity and foreign-key checks.

## Exit criteria

The server is ready for a limited user trial only after startup, authentication, WebUI, representative API transactions, backup/restore, and service restart pass on the target test machine. Keep the PR unmerged until the owner reviews the results. Hardware acceptance for Cashier/Vending (NFC, Wi-Fi recovery, physical dispensing, and power-loss recovery) remains a separate test.
