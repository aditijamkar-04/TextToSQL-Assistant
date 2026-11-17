# Staging provisioning update (not production-ready)

Added `postgres_workspace_provisioning.py` as an **opt-in, unconnected** staging coordinator.

- Separate `postgres_workspace_credentials` table protects SQL Server credential records.
- Reuses the existing Fernet key and verifies active ordinary application users.
- Uses per-user PostgreSQL reader logins and keeps stored passwords stable on repeat calls.
- Checks reader login, access to own schema, inability to create tables or read `public.users`, and lack of access to other workspace schemas.
- Uses a session-level advisory lock around credential state transitions.

**Important limitations**

1. Run only against a disposable Neon migration-test branch with its own `DATABASE_URL`. `auth_db.py` resolves DATABASE_URL at import time; verify that both auth and owner connections point to the test branch.
2. Do not run `initialize_postgres_credentials_table()` against production without a migration review.
3. No Flask routes have been switched. Existing SQL Server paths remain active. The bundle is NOT deployment-ready.
4. Reader privilege verification is not a complete security audit. PostgreSQL PUBLIC grants, executable functions, role memberships, cross-user data access, and password recovery need live verification.
5. No live Neon or Groq credentials were provided to this sandbox, so database and end-to-end tests were not run here.
6. Do not disable `DEMO_MODE=1` on Render.
