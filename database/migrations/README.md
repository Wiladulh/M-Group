# Legacy migration snapshot

The installer and runtime migration runner use **only** `app/migrations/*.sql`, in filename order, through `app/core/db.py`.

This directory is a historical/legacy snapshot retained for reference. Do not apply these files independently, and do not treat this directory as the current schema source of truth. New migrations belong in `app/migrations/` and must be covered by migration/idempotency tests.

The legacy files are intentionally retained to avoid deleting repository history or accidentally removing material used by older deployments. They are not packaged as the runtime migration set.
