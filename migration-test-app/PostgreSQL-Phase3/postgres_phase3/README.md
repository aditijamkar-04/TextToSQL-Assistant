# PostgreSQL Phase 3 — workspace table and record operations (staging)

This package adds `postgres_workspace_tables.py` as a **separate prototype**, not a drop-in replacement for `workspace_tables.py`. It has functions for validated CREATE TABLE, list tables, INSERT, SELECT up to 100 rows, UPDATE/DELETE by primary key, and primary-key discovery. Identifiers use psycopg SQL composition; values use bound parameters. The existing Flask frontend is not changed.

## Safety and prerequisites

- **Do not deploy, replace production modules, or disable DEMO_MODE.** This has only offline validation tests, no live Neon integration tests.
- The code requires `psycopg` and a trusted `DATABASE_URL`. It uses a database-owner connection for trusted CRUD operations only. **Never use it to execute AI-generated SQL.** The separate per-user restricted reader design from Phase 2 remains unfinished.
- Functions verify active ordinary users using `auth_db.verify_workspace_user`. Flask routes must also enforce session ownership and CSRF protection.
- A `workspace_N` schema must already exist. Table creation is serialized by PostgreSQL transaction advisory lock and capped at 20 tables.
- The existing UI does not create a primary key automatically. Tables without a primary key cannot be updated/deleted by this module; the table creation UX and PK selection require integration design.
- Old SQL Server data has **not** been migrated. There is no claim of live Neon compatibility or role-based isolation testing.
- Existing SQL Server types are mapped: `DATETIME2` -> `TIMESTAMP`, `NVARCHAR(n)` -> `VARCHAR(n)`, `BIT` -> `BOOLEAN`. Verify UI data semantics before integration.

## Offline tests

From this extracted folder, with your project `.venv` active:

```powershell
python -m unittest -v test_postgres_workspace_tables.py
```

## Remaining work

Implement per-user PostgreSQL restricted roles, secure credential lifecycle, read-only query execution, PostgreSQL SQL prompts, test on an isolated Neon branch/database, adapt return formats and Flask integration, then deploy only after security and end-to-end tests pass.
