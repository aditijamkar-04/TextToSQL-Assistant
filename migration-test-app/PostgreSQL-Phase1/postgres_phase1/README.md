# PostgreSQL migration — phase 1 (isolated, not deployed)

This folder contains an initial PostgreSQL SELECT validator. It does **not**
replace the existing SQL Server application and is **not ready for production**.

## Confirmed from the uploaded project
- `auth_db.py` supports Neon PostgreSQL for account and feedback data.
- `groq_client.py` and `text_to_sql.py` use Groq for SQL and explanations.
- `workspace_db.py`, `workspace_provisioning.py`, `workspace_tables.py`,
  `workspace_schema.py`, and `sql_service.py` depend on SQL Server.
- Disabling `DEMO_MODE` now would activate SQL Server-dependent routes.

## Implementation sequence
1. Create a separate, restricted PostgreSQL query role; explicitly revoke
   `public` schema access and restrict schema grants to a user's workspace.
   A shared read-only role with grants to all users' schemas is **not** isolated.
2. Port provisioning and credential storage, with transactional advisory locks.
3. Port all table and record CRUD operations, including PK discovery and
   concurrency controls.
4. Port schema discovery and SQL generation prompts to PostgreSQL.
5. Connect the SQL guard and query executor to a role that has **only** the
   current user's permissions; apply statement timeout and row cap.
6. Run negative tests for cross-user access, `public.users`, write attempts,
   function misuse, simultaneous provisioning, and role impersonation.
7. Only after successful integration tests, deploy and disable `DEMO_MODE`.

## Caveats
The validator is an initial defense-in-depth layer, not a complete security
boundary. PostgreSQL permission enforcement is mandatory. The validator
currently rejects CTEs; it is not yet integrated with Flask.

No secrets, environment files, or credentials are included.
