# Phase 5 — Integration audit (NOT deployment-ready)

This package consolidates the *staging* PostgreSQL modules and provides offline
interface checks against the original `workspace_tables.py`. It is not an
integrated Flask replacement. No database credentials are included.

Run `python -m unittest -v test_integration_contracts.py` in this folder.

## Outstanding blockers

1. Build an orchestrated, idempotent provisioning flow that verifies the app user,
   creates schema, creates a dedicated per-user reader role, stores credentials
   encrypted, and recovers from partial failures without rotating passwords on
   every login.
2. Audit PostgreSQL privileges and role inheritance, especially `PUBLIC` grants,
   `public` auth tables, database CONNECT, functions, and default privileges.
3. Update `text_to_sql.py` prompts, `workspace_schema.py`, `workspace_db.py`,
   `sql_service.py` and route integration; preserve existing JSON response shapes.
4. Provide a safe primary-key creation/editing path: Phase 3 CREATE TABLE does not
   create a PK and update/delete require one.
5. Test against a disposable Neon branch using two users: deny cross-user reads,
   public/auth reads, writes, role impersonation, and dangerous functions.
6. Validate data migration from local SQL Server, if old rows are required.
7. Verify all UI actions and only then deploy and disable DEMO_MODE.

Do not copy these modules over production files, deploy, or turn off DEMO_MODE.
