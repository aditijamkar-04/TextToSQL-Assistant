# Phase 6 — PostgreSQL prompt integration (staging only)

This phase adds a PostgreSQL-specific prompt builder and offline tests. It fixes the
previous T-SQL prompt's `TOP`, `dbo`, and SQL Server-only examples without modifying
the working Flask application. The prompt is NOT a security boundary.

Run from this directory:

    python -m unittest -v test_postgres_prompt.py

## How to integrate AFTER secure workspace roles and execution are verified

In `text_to_sql.py`, import `build_sql_prompt` from this module, then replace only
the `prompt = f"""..."""` assignment within `generate_sql` with:

    prompt = build_sql_prompt(question, user_id, database_schema)

Do NOT apply this replacement to `explain_sql`. Update its SQL Server-specific
wording and hard-coded `dbo` examples separately. Preserve its output contract.

## Blocking issues before deployment

- Phase 4 reader provisioning rotates passwords on repeated calls; implement
  idempotent provisioning and encrypted credential persistence first.
- Audit PostgreSQL PUBLIC/default grants, auth-table access, role membership,
  and function execution using two real disposable test users.
- Phase 3 CREATE TABLE lacks primary keys; update/delete require keys.
- SQL execution needs actual per-user reader credentials and verified session.
- Wire PostgreSQL schema discovery, provisioning, CRUD and query execution to
  Flask routes while preserving their existing response shapes.
- Test with a disposable Neon branch; do not turn off DEMO_MODE on production.

No credentials or database URLs are included.
