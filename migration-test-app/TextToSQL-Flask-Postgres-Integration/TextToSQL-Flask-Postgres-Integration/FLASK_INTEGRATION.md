# Flask + PostgreSQL staging integration

This is an opt-in integration candidate, **not a deployable production release**. The default `WORKSPACE_BACKEND=sqlserver` keeps the original behavior.

## Changed
- `app.py` dispatches registration provisioning, login/readiness, CRUD routes, and `/ask` to PostgreSQL when `WORKSPACE_BACKEND=postgres`.
- `/explain-query` validates the supplied PostgreSQL SELECT and asks Groq to explain it; this is not yet bound to the last executed SQL in history.
- The existing frontend routes and JSON payloads remain unchanged.
- No production or local databases were contacted while building this ZIP.

## Before any database-connected staging test
1. Use ONLY the disposable Neon migration-test branch and verify both `DATABASE_URL` and auth point to it. Keep credentials in `.env` outside the ZIP.
2. Set `WORKSPACE_BACKEND=postgres`, `POSTGRES_STAGING_READY=1`, `DEMO_MODE=1` initially; explicitly initialize the PostgreSQL credential table with `initialize_postgres_credentials_table()` only after verifying the database target.
3. Run the unit tests. Live security testing of dedicated login isolation, privilege grants, auth data access, function execution, role escalation and two-user CRUD is still required.
4. The PostgreSQL backend is **not** ready for `DEMO_MODE=0` or Render.

Known gap: credential coordinator has not yet been tested against Neon under concurrent registration; schema/table creation is owner-mediated and requires privilege review. No automated deployment switch has been made.
