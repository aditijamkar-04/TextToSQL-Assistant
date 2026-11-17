"""Staging-only per-user PostgreSQL reader provisioning and SELECT execution.

Never use the owner DATABASE_URL to execute generated SQL. Not wired to Flask.
Requires Phase 1 postgres_query_guard.py and an isolated test database.
"""
import os
import secrets
from urllib.parse import urlsplit, urlunsplit, quote

import psycopg
from psycopg import sql

from postgres_query_guard import validate_workspace_select

MAX_ROWS = 100


def names(user_id):
    if isinstance(user_id, bool):
        raise ValueError("Invalid user ID")
    try:
        n = int(user_id)
    except (TypeError, ValueError) as exc:
        raise ValueError("Invalid user ID") from exc
    if n <= 0 or str(user_id).strip() != str(n):
        raise ValueError("Invalid user ID")
    return f"workspace_{n}", f"workspace_reader_{n}"


def _owner_url():
    url = os.getenv("DATABASE_URL", "").strip()
    if not url:
        raise RuntimeError("DATABASE_URL is required")
    return url


def _reader_dsn(role, password):
    """Use owner URL only as endpoint template; replace owner credentials.

    Do not print or log returned DSN. Database URL must use postgres:// or
    postgresql:// syntax and a URL-encoded host/database.
    """
    parts = urlsplit(_owner_url())
    if parts.scheme not in ("postgres", "postgresql") or not parts.hostname:
        raise RuntimeError("Invalid PostgreSQL DATABASE_URL")
    host = parts.hostname
    if ':' in host:
        host = f'[{host}]'
    port = f':{parts.port}' if parts.port else ''
    netloc = f'{quote(role, safe="")}:{quote(password, safe="")}@{host}{port}'
    return urlunsplit((parts.scheme, netloc, parts.path, parts.query, ''))


def provision_reader(user_id, *, password=None):
    """Owner-only; return NEW password for encrypted server-side storage.

    Requires verified app-user authorization by caller. Existing role password
    is rotated when called again; caller MUST atomically coordinate its
    credential storage and status, or users can lose access. Do not call on
    every request. No auth-table writes are made here.
    """
    schema, role = names(user_id)
    password = password or secrets.token_urlsafe(40)
    if not isinstance(password, str) or len(password) < 32:
        raise ValueError("Reader password must be at least 32 characters")
    with psycopg.connect(_owner_url(), connect_timeout=10) as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT pg_advisory_xact_lock(%s, %s)", (720614, int(user_id)))
            cur.execute("SELECT 1 FROM pg_namespace WHERE nspname = %s", (schema,))
            if cur.fetchone() is None:
                raise RuntimeError("Workspace schema must be provisioned first")
            cur.execute("SELECT 1 FROM pg_roles WHERE rolname = %s", (role,))
            if cur.fetchone() is None:
                cur.execute(
                    sql.SQL(
                        "CREATE ROLE {} LOGIN NOINHERIT NOSUPERUSER "
                        "NOCREATEDB NOCREATEROLE NOREPLICATION PASSWORD {}"
                    ).format(
                        sql.Identifier(role),
                        sql.Literal(password),
                    )
                )
            else:
                cur.execute(
                    sql.SQL(
                        "ALTER ROLE {} WITH LOGIN NOINHERIT PASSWORD {}"
                    ).format(
                        sql.Identifier(role),
                        sql.Literal(password),
                    )
                )
            # Explicit grants only on the one workspace schema.
            # WARNING: PUBLIC grants cannot be revoked for just one role.
            # A separate privilege audit is required before deployment.
            cur.execute(sql.SQL("REVOKE ALL ON SCHEMA public FROM {}").format(sql.Identifier(role)))
            cur.execute(sql.SQL("GRANT USAGE ON SCHEMA {} TO {}").format(sql.Identifier(schema), sql.Identifier(role)))
            cur.execute(sql.SQL("GRANT SELECT ON ALL TABLES IN SCHEMA {} TO {}").format(sql.Identifier(schema), sql.Identifier(role)))
            # Default privileges are tied to the current owner/creator role.
            cur.execute(sql.SQL("ALTER DEFAULT PRIVILEGES IN SCHEMA {} GRANT SELECT ON TABLES TO {}").format(sql.Identifier(schema), sql.Identifier(role)))
    return {"schema": schema, "role": role, "password": password}


def execute_restricted_select(query, user_id, password):
    """Connect as this user's restricted role; never as the owner.

    Password must be fetched from server-side encrypted credentials after
    verifying the session user and ready provisioning status.
    """
    schema, role = names(user_id)
    if not isinstance(password, str) or not password:
        raise ValueError("Reader credentials unavailable")
    safe_sql = validate_workspace_select(query, schema)
    # Do not allow calling arbitrary PostgreSQL functions, even from SELECT.
    # PostgreSQL grants EXECUTE on functions to PUBLIC by default.
    import sqlglot
    from sqlglot import exp
    ast = sqlglot.parse_one(safe_sql, read="postgres")
    allowed = {"COUNT", "SUM", "AVG", "MIN", "MAX"}
    for node in ast.walk():
        if isinstance(node, exp.Func):
            name = node.sql_name().upper()
            if name not in allowed:
                raise ValueError(f"SQL function is not permitted: {name}")
    dsn = _reader_dsn(role, password)
    with psycopg.connect(dsn, connect_timeout=10) as conn:
        with conn.cursor() as cur:
            cur.execute("SET TRANSACTION READ ONLY")
            cur.execute("SET LOCAL statement_timeout = '10s'")
            cur.execute("SET LOCAL lock_timeout = '3s'")
            cur.execute("SET LOCAL search_path = pg_catalog")
            cur.execute("SELECT current_user")
            if cur.fetchone()[0] != role:
                raise RuntimeError("Reader role identity verification failed")
            cur.execute(safe_sql)
            if cur.description is None:
                raise ValueError("Query returned no result set")
            columns = [c.name for c in cur.description]
            rows = cur.fetchmany(MAX_ROWS)
            return {"columns": columns, "rows": [list(r) for r in rows], "row_limit": MAX_ROWS}
