# PostgreSQL Phase 4 — restricted AI query prototype

**Staging code, not production-ready or wired to Flask. Do not disable DEMO_MODE.**

Adds per-user login-role provisioning and execution of read-only, limited SELECT queries as the restricted role. Includes Phase 1 AST guard. The PostgreSQL owner is used for trusted provisioning only, never for AI SQL execution.

## Critical remaining security work

- Test with a disposable Neon database/branch and a non-owner account. **No live database tests have been performed.**
- Verify database-level CONNECT grants, schema PUBLIC privileges, inherited roles, default privileges for all table creators, and function execution grants. PostgreSQL has broad PUBLIC privileges by default; this code is **not a complete isolation boundary without a permissions audit**.
- Provisioning returns a new password. Integrate with encrypted credential storage carefully; **reprovisioning rotates passwords**, so it must coordinate with credential updates and failure recovery.
- Integrate role creation and grants with Phase 2 schema provisioning and Phase 3 table creation, then verify role grants on newly created tables.
- Test forbidden cross-user/public queries, function execution, SQL parser bypasses, concurrent provisioning, transactions, and permission revocations.
- Update `text_to_sql.py` prompts to PostgreSQL and connect Flask routes only after tests.
- Groq free-tier usage, Neon limits, and Render free-instance sleep mean unlimited queries and always-on availability cannot be guaranteed.

## Offline checks

Install your project's dependencies, then from this folder run:

```powershell
python -m unittest -v test_postgres_restricted_query.py
```

**Never upload .env, reader passwords, or DATABASE_URL.**
