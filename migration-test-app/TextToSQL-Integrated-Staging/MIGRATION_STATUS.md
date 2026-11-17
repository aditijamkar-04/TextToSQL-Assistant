# Text-to-SQL Assistant — Integrated staging bundle

This bundle combines your **original uploaded project** with the PostgreSQL
staging modules from phases 2–6. It is **not deployment-ready**. No existing
Flask route has been silently switched to PostgreSQL, and production Render
remains unchanged.

## What is now together
- Original Flask UI, auth, Groq client, and SQL Server modules, unchanged.
- PostgreSQL schema foundation, table CRUD prototype, SQL prompt, AST guard,
  and restricted query prototype.
- `test_migration_staging.py` checks syntax and API signatures offline.

## Run the safe offline checks
In a NEW folder, extract the ZIP, activate your project's virtualenv and run:

```powershell
python -m unittest -v test_migration_staging.py
```

## Blockers before wiring routes or enabling Demo Mode off
1. Implement **idempotent, app-user-verified provisioning** and encrypted
   storage of dedicated PostgreSQL reader credentials. The existing staging
   `provision_reader()` rotates passwords when re-invoked, so do not call it
   from a login route as-is.
2. Ensure PostgreSQL reader roles are isolated in a real **login connection**,
   with no inherited/public/auth privileges, role escalation, or unsafe
   executable functions. `SET ROLE` from the owner is not sufficient proof.
3. Map `workspace_tables.py` CRUD response shapes and primary-key creation
   to the existing Data Sources frontend; test against two disposable users.
4. Replace the original SQL Server prompt/metadata/execution path behind an
   opt-in PostgreSQL backend, then test registration, sign-in, table operations,
   query history, explanation, charts, feedback, and admin routes.
5. Confirm free-tier capacity and safe resource limits; then deploy to Render.

**Never place your `.env` or database/API credentials in a ZIP or Git.**
**Do not overwrite your live project with this bundle or set DEMO_MODE=0.**
