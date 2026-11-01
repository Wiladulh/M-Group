# V2 Test Policy

All tests in this directory belong to the clean-room implementation.

1. Use temporary SQLite databases or dedicated disposable test services.
2. Never read or mutate production data.
3. Add a clean-install schema test that asserts canonical tables/columns and rejects the legacy `device_id` identifier.
4. Add contract tests for device provisioning, registration, authentication, member PIN, payment idempotency, vending inventory, and ledger consistency.
5. Keep security requirements in force; do not loosen production validation merely to make a test pass.
6. CI must run v2 tests independently of legacy test workflows.

7. V2 startup initialization may create missing canonical schema objects but must not silently migrate, delete, or rewrite existing records. Schema transitions require explicit reviewed migrations.
8. Run the browser E2E suite against a disposable server/database in CI; contract-string tests are not a substitute for browser behavior.
9. Run a documented isolated restore drill before release; automated backup round-trip tests do not replace operational recovery evidence.
