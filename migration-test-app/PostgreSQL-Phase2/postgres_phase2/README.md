# PostgreSQL Phase 2 — safe workspace foundation

This is an **isolated development package**, not a finished deployment or a replacement for `workspace_db.py`.

## Contents
- `postgres_workspace_core.py`: schema-name validation, transaction-scoped PostgreSQL advisory lock, owner-side schema creation, and metadata discovery.
- `test_postgres_workspace_core.py`: offline tests for schema validation and refusal to use a shared reader role.

## Critical security limitation
A single PostgreSQL reader role granted SELECT on every `workspace_N` schema **cannot enforce user isolation**. `search_path`, application-level SQL validation, and `SET ROLE` without suitable privileges are **not** sufficient. Do not create a global reader with access to all schemas. The final design needs distinct restricted per-user execution roles (or a separately reviewed isolation mechanism), no `public`/auth table access, default-privilege handling, and a read-only transaction for AI queries.

`provision_schema()` is owner-only and deliberately does not grant query privileges. It must be called only after the application has verified the user is active and non-admin.

## How to run tests (no database needed)
From the extracted folder, with your project's environment active:

```powershell
python -m unittest -v test_postgres_workspace_core.py
```

## Not yet implemented
- Per-user PostgreSQL role lifecycle and credential storage
- Restricted SELECT execution with statement timeout, schema enforcement, and row limits
- PostgreSQL table/record CRUD and SQL generation prompt conversion
- Flask integration, migration of old SQL Server data, and live Neon integration tests

Keep `DEMO_MODE=1` and do not copy these files over existing modules or deploy them. Never include DATABASE_URL or API keys in an uploaded ZIP.
