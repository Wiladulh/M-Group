# Rebuild v2 — Accepted Baseline Lock

Baseline established from the accepted server/backend validation at commit
`fd309ca240fedcd3075855d336565f57b70e4098` (backend CI: 49 tests passed).

This document is a change-control contract for all subsequent work on
`rebuild/clean-room-v2`. It does not claim that unfinished items are complete.

## 1. Locked PASS behaviors

The following accepted behaviors must remain intact during future fixes:

- Admin WebUI authentication uses username and password, with a server-side
  session cookie; Admin API tokens are not used as the WebUI login mechanism.
- A logged-in Admin can interact throughout a valid session without repeated
  login for every action.
- Admin password change requires the current password and confirmation of the
  new password.
- Member identity and account are server-managed; Member IDs are generated
  by the server.
- Members do not log in to the Admin WebUI.
- Member transaction PINs are stored as hashes and are required for purchases
  from Cashier and Vending.
- NFC identifies the Member. Registering or replacing an NFC card must not
  silently clear or replace the Member transaction PIN.
- NFC enrollment is initiated and managed through the Admin WebUI and the
  selected registered Cashier, with bounded registration sessions.
- Top-up is Admin-only through the Server WebUI after cash is handed to the
  Admin. The Admin selects a Member and credits the entered amount.
- Cashier and Vending must not expose or perform top-up workflows. Top-up must
  not require Member PIN, operator PIN, NFC, Cashier, or Vending.
- Balance changes and their ledger entries remain atomic and idempotent.
- Logical device registry identity is distinct from hardware identity.
  Devices authenticate using server-issued Device Keys.
- Device management, including key rotation and hardware replacement, must
  preserve the logical registry identity rules.
- Vending has five product positions per registered machine.
- Product images are uploaded and validated on the server and delivered via
  authenticated device endpoints in the optimized device-compatible format.
- Transaction history, audit records, and ledger/reconciliation behavior
  remain available and consistent.
- Backup and restore integrity protections must not be weakened.

## 2. Change-control rules

1. A fix must be scoped to the failing or unfinished requirement. Do not
   refactor or redesign a locked PASS feature as incidental cleanup.
2. Any change touching a locked behavior must state the technical reason and
   identify affected contracts before implementation.
3. Add or update regression tests that prove the locked behavior still holds.
4. Run the directly affected tests and the complete backend test suite.
5. Do not mark a previously passing item as PASS based only on source inspection;
   require executable test evidence.
6. If a locked behavior must change because of a proven future technical
   constraint, document the reason, migration/compatibility impact, replacement
   behavior, and test evidence. Treat it as an explicit contract revision,
   not an ordinary bug fix.
7. Do not merge to `main`, deploy, or alter production data as part of this
   baseline lock.

## 3. Validation gate

The accepted backend baseline had 49 passing tests in GitHub Actions.
Every subsequent backend change must pass the full backend test suite.
Changes to firmware/API contracts must also pass the relevant firmware build
and cross-device contract checks before being accepted.

## 4. Scope distinction

This lock protects only behaviors that were already accepted as PASS.
It does not convert known gaps into completed work. Outstanding items such as
WebUI browser-level verification, operational restore rehearsal, and
documentation cleanup remain open until separately validated.

## 5. Baseline reference

- Repository: `Wiladulh/M-Group`
- Working branch: `rebuild/clean-room-v2`
- Baseline commit: `fd309ca240fedcd3075855d336565f57b70e4098`
- Backend CI run: https://github.com/Wiladulh/M-Group/actions/runs/41295005833
