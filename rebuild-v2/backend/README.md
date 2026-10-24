# Backend v2

This is the isolated backend implementation for the clean-room rebuild.

- Do not import code from `../../app` or any legacy root package.
- Keep route handlers thin and validate request/response schemas explicitly.
- Keep business rules in domain services.
- Use `../db/schema.sql` as the canonical schema for fresh test databases.
- Add unit, integration, and contract tests before connecting new services to the WebUI or firmware.

Implementation has not started; this file marks the intended boundary.
