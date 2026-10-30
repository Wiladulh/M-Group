# Post-Transaction Balance Refresh Requirement

Applies to both Vending and Cashier on branch `rebuild/clean-room-v2`.

After every transaction attempt that may have changed a member's funds (successful debit, deposit/top-up, refund, reversal, offline debit upload, or an outcome that is uncertain), the device must make a best-effort attempt to refresh that member's balance and relevant account/card version from the server.

## Required behavior

1. The server's committed ledger result is authoritative. Use the transaction response/version where possible, then fetch or sync the latest member balance after the transaction.
2. Persist the new balance snapshot and server version atomically. Never overwrite a newer version with an older response.
3. Trigger refresh after success, and also after failure/timeout if the server may have committed the transaction. For unknown outcomes, query by the same idempotency/transaction ID before treating it as failed or starting another transaction.
4. If the server is unreachable, mark the cache as stale/pending refresh; do not claim it is current. Queue a retry with bounded exponential backoff and retry on reconnection. A queued refresh must not duplicate the financial transaction.
5. For an offline transaction, update the local provisional balance and offline allowance immediately from the durable journal; reconcile with the server when connected, then replace the provisional snapshot only with a confirmed newer server version.
6. Refresh is a background/cache-maintenance operation and must not cause duplicate debit, deposit, dispense, or refund. Financial actions remain idempotent and ledger-backed.
7. Vending and Cashier UI should show balance freshness or a pending-sync indicator when the latest refresh cannot be confirmed.

## Acceptance criteria

- Both device types attempt a member-balance refresh after each transaction that could affect the balance.
- Successful online transaction responses update the cache from authoritative server data without an unnecessary second request when the response already contains a confirmed balance/version.
- Timeout/uncertain outcomes are reconciled using the original transaction ID/idempotency key.
- Network loss leaves an explicit stale/pending state and schedules retries; it never silently labels the cached balance as current.
- Sync retries cannot replay financial side effects.
- Offline transactions update provisional local accounting durably and reconcile idempotently after reconnection.

This document is a design requirement only. It does not assert that firmware, API, or UI implementation is already complete; comprehensive testing remains deferred until the implementation phase is finished.

## Implementation status — 2026-10-30

Partially implemented in rebuild-v2:
- Cashier and Vending cache the last 100 member balance snapshots using salted card references; raw UID and PIN are not persisted.
- The v2 balance lookup returns the server account update timestamp as `balance_version`.
- Cashier payment/top-up and Vending purchase/dispense-result responses include the authoritative post-transaction balance and version, including idempotent replay paths.
- Firmware writes a single snapshot record atomically after a confirmed transaction. It performs a best-effort balance lookup for insufficient-balance and uncertain outcomes, and refreshes missing/stale cache entries when the member taps again.
- Financial debits remain server-authoritative. The cache is a lookup/display aid only.

Remaining:
- Background retry queue and authenticated bulk sync on startup/reconnection/periodic schedule are not complete.
- A transaction result that remains unknown while offline is retained under the original idempotency key; the device must not create a new financial request. The member re-taps to resume and refresh the snapshot.
- Build and end-to-end validation are not yet run.
