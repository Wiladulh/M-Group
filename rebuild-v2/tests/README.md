# V2 Test Policy

All tests in this directory belong to the clean-room implementation.

1. Use temporary SQLite databases or dedicated disposable test services.
2. Never read or mutate production data.
3. Add a clean-install schema test that asserts canonical tables/columns and rejects the legacy `device_id` identifier.
4. Add contract tests for device provisioning, registration, authentication, member PIN, payment idempotency, vending inventory, and ledger consistency.
5. Keep security requirements in force; do not loosen production validation merely to make a test pass.
6. CI must run v2 tests independently of legacy test workflows.
