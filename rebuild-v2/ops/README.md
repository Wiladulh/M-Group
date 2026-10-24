# Operations v2

This directory will contain environment examples, deployment configuration, backup/restore procedures, health checks, and release checklists.

Rules:
- Do not commit secrets or production data.
- CI and local development must use isolated databases.
- Backup/restore must be rehearsed before cutover.
- No deployment or production database mutation occurs automatically from a code merge.
