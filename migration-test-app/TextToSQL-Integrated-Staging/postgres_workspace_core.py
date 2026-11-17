"""PostgreSQL workspace foundation. Not a drop-in replacement for SQL Server modules.

Required env: DATABASE_URL (trusted owner), WORKSPACE_READER_URL (non-owner login).
Run SQL in setup_reader.sql as the owner before enabling any user queries.
"""
import os
import re
from contextlib import contextmanager


SCHEMA_PATTERN = re.compile(r'^workspace_[1-9][0-9]*$')


def workspace_schema(user_id):
    if isinstance(user_id, bool):
        raise ValueError('Invalid user ID')
    try:
        number = int(user_id)
    except (TypeError, ValueError) as exc:
        raise ValueError('Invalid user ID') from exc
    if number <= 0 or str(user_id).strip() != str(number):
        raise ValueError('Invalid user ID')
    return f'workspace_{number}'


def _url(name):
    value = os.getenv(name, '').strip()
    if not value:
        raise RuntimeError(f'{name} is not configured')
    return value


def provision_schema(user_id):
    """Owner-only schema provisioning; does not grant access to public tables.

    Call only after independently verifying an active, ordinary app user.
    Advisory lock serializes concurrent requests for this same user.
    """
    import psycopg
    from psycopg import sql
    schema = workspace_schema(user_id)
    with psycopg.connect(_url('DATABASE_URL')) as conn:
        with conn.cursor() as cur:
            cur.execute('SELECT pg_advisory_xact_lock(%s, %s)', (720613, int(user_id)))
            cur.execute(sql.SQL('CREATE SCHEMA IF NOT EXISTS {}').format(sql.Identifier(schema)))
            # No reader grants here: privilege assignment is an explicit administrative action.
    return schema


def grant_reader_schema(user_id):
    """Owner-only; grants SELECT on existing and future workspace tables.

    The reader role can see ALL workspace schemas granted to it; therefore it
    MUST NOT be used for per-user AI queries. Kept deliberately unavailable.
    """
    raise RuntimeError('Shared reader roles cannot isolate individual user schemas; use a per-user restricted role')


def get_schema_columns(user_id):
    """Owner-side metadata discovery, scoped by exact schema name."""
    import psycopg
    schema = workspace_schema(user_id)
    with psycopg.connect(_url('DATABASE_URL')) as conn:
        with conn.cursor() as cur:
            cur.execute('''
                SELECT table_name, column_name, data_type, character_maximum_length
                FROM information_schema.columns
                WHERE table_schema = %s
                ORDER BY table_name, ordinal_position
            ''', (schema,))
            return cur.fetchall()
