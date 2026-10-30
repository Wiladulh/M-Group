# Vending Member Cache and Limited Offline Payments

Status: accepted design for `rebuild/clean-room-v2`. This document records the implementation contract; it does not claim that firmware/API support is already implemented or tested.

## Goals

- Keep the Vending WebUI responsive when the network is slow by resolving recently/frequently used members from a local cache of at most 100 members per device.
- Permit limited offline purchases only through a separately enforced offline-risk budget and durable reconciliation.
- Keep the server as the authoritative member, balance, card, device, and ledger source.
- Require NFC card plus transaction PIN for every member payment, online or offline.
- Avoid retaining full NIK unless a documented use case requires it.

## Per-device member cache

Each Vending device maintains its own cache of up to 100 recently/frequently used members. Selection is local to each device and may differ between devices. The cache record should contain only:

- immutable server-issued member ID;
- card reference/token suitable for lookup (do not treat NFC UID alone as payment authorization);
- display name, only if needed by the WebUI;
- last-known balance, explicitly marked as a snapshot and never represented as authoritative;
- member/card status and server-issued status/version;
- server data version and last successful synchronization time.

Do not cache full NIK by default. Do not cache transaction PIN, plaintext credentials, or reusable payment secrets. Protect local storage and transport; avoid logging card references or personal data unnecessarily. A cache miss, malformed cache, invalid signature/version, or untrusted clock must not silently enable payment.

## Synchronization

- Initial provisioning and sync use authenticated device identity issued by the server; MAC address is metadata only, not the permanent device identity.
- Synchronize on connection/reconnection, at startup, after a completed transaction, and periodically with backoff. Use incremental versions/deltas where possible and a full refresh when version continuity cannot be established.
- Apply a sync update atomically; persist version/cursor only after the complete update is durable.
- Receive status revocations and card/member changes. Because an offline device cannot know a revocation that happened after its last sync, enforce freshness limits and offline-risk policy rather than claiming revocation is instantaneous.
- Never overwrite a newer server balance with an older cache snapshot. Reconciliation uses server ledger events and idempotency keys, not blind balance replacement.

## Payment authorization

### Online / slow network

1. Read NFC card and resolve the server-issued member/card reference from cache.
2. Require the member's transaction PIN in the WebUI for every payment. The PIN must be sent only over authenticated TLS to the server; never log or persist it on the ESP32.
3. The server validates active member/card, PIN verifier, device authorization, current authoritative balance, amount, and transaction idempotency; the server commits the debit atomically.
4. Dispense only after a valid server authorization/commit response. A timeout with an unknown outcome must be queried/reconciled by idempotency key; it must not be retried as a new debit or reported as successful without confirmation.

Cache accelerates lookup and UI, not the authoritative debit decision.

### Fully offline

Offline payment is allowed only after the complete offline authorization mechanism is implemented. A last-known balance alone is never sufficient. The server must pre-allocate a bounded offline spending allowance to a specific device/member (or an equivalent cryptographically enforced, non-reusable authorization). The same allowance must not be spendable by another device. Each offline debit atomically consumes that local allowance and is written to durable storage before dispense is initiated.

The design must define and enforce: per-member and per-device monetary ceilings; transaction count and per-transaction limits; cache/status freshness expiry; offline duration; replay protection; monotonic transaction sequence/unique IDs; secure PIN verification without storing plaintext PIN or a reusable credential; durable journal capacity and power-loss recovery; refund/failed-dispense handling; and server reconciliation/conflict rules. If any prerequisite is missing, expired, exhausted, or unverifiable, fail closed and reject payment while offline.

The server must reconcile each journal event idempotently, detect gaps/replays/conflicts, and report unresolved events for operator action. Never automatically refund or debit twice based only on a repeated upload. Offline risk limits must be configurable server-side and conservative by default.

## PIN security

- NFC UID alone never authorizes payment.
- Require transaction PIN for every Cashier/Vending payment.
- Store server-side PIN verifiers using an appropriate password-hashing scheme; never plaintext.
- Rate-limit attempts and apply temporary lockout/backoff.
- Offline PIN verification needs a separately reviewed design. Do not copy the server's password hash to the ESP32 and assume it is safe; do not enable offline payment until verification can be done securely with bounded attack resistance.

## Required integration before release

- Server API/schema for cache snapshots/deltas and version/revocation state.
- Device-authenticated sync, server-issued device ID/key, and per-device offline allowance/authorization.
- Mandatory PIN validation on Vending and Cashier payment paths.
- Durable Vending offline transaction journal and idempotent reconciliation.
- UI states distinguishing online authorization, limited offline authorization, pending/unknown outcome, and rejection.
- Admin visibility for cache freshness, offline budget, pending reconciliation, rejected/replayed events, and device status.
- Documentation and demo UI updated to match actual implementation.
- Comprehensive end-to-end tests are deferred until implementation is complete, per project direction. Do not claim production-ready or merge-ready before these tests pass.

## Acceptance criteria

1. Cache is bounded to 100 members per device and stores no full NIK by default and no PIN.
2. Cache data is versioned, authenticated, persisted atomically, and refreshed when connectivity returns.
3. Slow-network online purchases still require server PIN/balance authorization and idempotent transaction handling.
4. Offline purchases are impossible unless valid device-specific allowance, PIN verification, freshness, limits, and durable journal are all available.
5. The same offline allocation cannot be spent by multiple devices.
6. Power loss or retry cannot create duplicate debits or duplicate dispenses; ambiguous outcomes are reconciled.
7. Cache balance is always labelled last-known and is never treated as the authoritative server balance.
8. Member/card revocation, insufficient allowance, incorrect PIN, expired cache, journal failure, or integrity failure blocks offline payment.
9. Vending and Cashier both require NFC plus transaction PIN for member payments.


## Implementation status — 2026-10-30

Partially implemented in rebuild-v2 firmware:
- Shared `MGroupMemberCache.h` stores at most 100 snapshots per device in Preferences.
- Each snapshot is a single atomic NVS JSON record and contains a device-salted card reference, server member ID, display name, last-known balance, currency, server balance version, and local sync timestamp.
- Raw NFC UID, PIN, and NIK are not persisted in the cache.
- Cashier and Vending read a cached snapshot for display; stale/missing snapshots trigger an online balance lookup. The snapshot is explicitly labelled last-known.
- Online purchase/payment remains authorized by the server's current member/card status, PIN, account status, and ledger balance. Cache values never authorize an offline debit.
- Transaction responses now return authoritative `balance_after_minor`, `member_id`, and `balance_version` where applicable; vending dispense success/refund responses also return the post-dispense balance. Firmware updates the cache after the result is known.

Still outstanding:
- Authenticated server bulk snapshot/delta sync for the last 100 members on startup/reconnect and periodic refresh.
- A durable pending-refresh queue that can resume without retaining raw card UIDs; use a server-issued opaque member/card reference for this rather than persisting UID.
- Explicit stale/pending-sync status surfaced in a richer device UI.
- Full build, regression, power-loss, and hardware acceptance tests remain deferred.
- Offline payment remains disabled until the separately defined allowance, secure PIN, journal, and reconciliation mechanism is complete.
