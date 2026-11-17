# Text-to-SQL Assistant — All-in-One Migration Workspace

This archive contains your original Flask project and all PostgreSQL staging modules from Phases 1–8 in ONE place. It is a **development/staging package, NOT a completed deployable migration**.

## What is included
- Original Flask routes, templates, authentication, feedback, and Groq client.
- PostgreSQL schema foundation, CRUD prototype, prompt, query guard, restricted executor, and AI service.
- Offline contract tests and the project requirements.

## IMPORTANT current limitations
- `app.py` still calls the original SQL Server services. The PostgreSQL modules have not been wired into Flask.
- PostgreSQL per-user reader credentials are not yet stored and provisioned atomically. Provisioning may rotate passwords; do not run it on production.
- PostgreSQL table CRUD has not been end-to-end tested with the existing frontend; primary key handling needs attention.
- Database-owner URL MUST NEVER execute AI-generated SQL.
- No live Neon tests were performed by this bundle creator. Your earlier manual security checks do not replace application end-to-end tests.

## Safe local setup
1. Extract to a **new folder**. Do not overwrite the original project.
2. Use your existing Python virtual environment and install `requirements.txt` dependencies as appropriate.
3. Run `python test_migration_staging.py` and `python test_postgres_ai_service.py` in the extracted folder.
4. Do not set `DEMO_MODE=0` on Render, copy staging modules into production, or commit `.env`.

## Remaining work before deployment
1. Secure, idempotent per-user reader-role provisioning and encrypted credentials.
2. Connect the PostgreSQL backend to existing Flask routes without changing their response contracts.
3. Fix/test table CRUD and primary keys; test two isolated user accounts and deny privilege escalation.
4. End-to-end test all UI, auth, feedback, AI, and DB paths on a disposable Neon branch.
5. Deploy after tests pass and only then disable Demo Mode.

No API keys, database passwords, or .env are included.
