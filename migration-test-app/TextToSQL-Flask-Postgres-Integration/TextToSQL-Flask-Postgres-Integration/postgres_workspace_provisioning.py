"""Staging-only PostgreSQL provisioning coordinator.

Use ONLY with a disposable Neon migration-test database. This module does not
change Flask routes or production. A separate credential table avoids replacing
SQL Server logins. Callers must derive user_id from the authenticated session.
"""
import secrets

import psycopg
from psycopg import sql

from auth_db import get_auth_connection, verify_workspace_user
from postgres_restricted_query import names, _owner_url, _reader_dsn, provision_reader
from workspace_credentials import get_cipher


def _encrypt(password):
    return get_cipher().encrypt(password.encode('utf-8')).decode('utf-8')


def _decrypt(token):
    return get_cipher().decrypt(token.encode('utf-8')).decode('utf-8')


def initialize_postgres_credentials_table():
    """Run against the isolated staging auth database, not production."""
    with get_auth_connection() as conn:
        conn.execute('''CREATE TABLE IF NOT EXISTS postgres_workspace_credentials (
            user_id INTEGER PRIMARY KEY REFERENCES users(user_id) ON DELETE CASCADE,
            reader_role TEXT NOT NULL UNIQUE,
            encrypted_password TEXT NOT NULL,
            provisioning_status TEXT NOT NULL DEFAULT 'pending'
                CHECK (provisioning_status IN ('pending','ready','failed')),
            created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP
        )''')


def _get_record(user_id):
    with get_auth_connection() as conn:
        return conn.execute('''SELECT reader_role, encrypted_password, provisioning_status
            FROM postgres_workspace_credentials WHERE user_id = ?''', (user_id,)).fetchone()


def _verify_reader(user_id, password):
    schema, role = names(user_id)

    with psycopg.connect(
        _reader_dsn(role, password),
        connect_timeout=10
    ) as conn:
        with conn.cursor() as cur:
            # Verify the restricted login and permissions.
            cur.execute(
                """
                SELECT
                    current_user,
                    has_schema_privilege(
                        current_user, %s, 'USAGE'
                    ),
                    has_schema_privilege(
                        current_user, %s, 'CREATE'
                    ),
                    has_table_privilege(
                        current_user, 'public.users', 'SELECT'
                    )
                """,
                (schema, schema)
            )

            actual, can_use, can_create, can_read_users = cur.fetchone()

            if (
                actual != role
                or not can_use
                or can_create
                or can_read_users
            ):
                raise PermissionError(
                    "Reader privilege verification failed"
                )

            # Ensure the reader cannot access another workspace.
            cur.execute(
                """
                SELECT nspname
                FROM pg_namespace
                WHERE left(nspname, 10) = 'workspace_'
                  AND nspname <> %s
                  AND has_schema_privilege(
                      current_user, oid, 'USAGE'
                  )
                LIMIT 1
                """,
                (schema,)
            )

            if cur.fetchone() is not None:
                raise PermissionError(
                    "Reader can access another workspace"
                )

def provision_postgres_workspace(user_id):
    """Idempotent provisioning with stable encrypted credentials.

    The owner-level advisory lock serializes this coordinator across workers.
    Pending/failed records reuse the SAME password on retries. An existing
    ready record is verified, not re-provisioned or rotated.
    """
    schema, role = names(user_id)
    user_id = int(user_id)
    verify_workspace_user(user_id)
    with psycopg.connect(_owner_url(), connect_timeout=10) as owner:
        with owner.cursor() as cur:
            cur.execute('SELECT pg_advisory_lock(%s, %s)', (720615, user_id))
            verify_workspace_user(user_id)
            record = _get_record(user_id)
            if record is None:
                password = secrets.token_urlsafe(40)
                with get_auth_connection() as auth:
                    auth.execute('''INSERT INTO postgres_workspace_credentials
                        (user_id, reader_role, encrypted_password, provisioning_status)
                        VALUES (?, ?, ?, 'pending')''', (user_id, role, _encrypt(password)))
                status = 'pending'
            else:
                if record['reader_role'] != role:
                    raise RuntimeError('Stored reader role does not match user')
                password = _decrypt(record['encrypted_password'])
                status = record['provisioning_status']
            if status == 'ready':
                _verify_reader(user_id, password)
                return {'schema': schema, 'role': role, 'status': 'ready'}
            try:
                cur.execute(sql.SQL('CREATE SCHEMA IF NOT EXISTS {}').format(sql.Identifier(schema)))
                # Commit schema creation before provision_reader opens its own connection.
                # Session-level lock is held separately below, not transaction-level.
                owner.commit()
                provision_reader(user_id, password=password)
                _verify_reader(user_id, password)
            except Exception:
                with get_auth_connection() as auth:
                    auth.execute('''UPDATE postgres_workspace_credentials
                        SET provisioning_status = 'failed' WHERE user_id = ?''', (user_id,))
                raise
            with get_auth_connection() as auth:
                auth.execute('''UPDATE postgres_workspace_credentials
                    SET provisioning_status = 'ready' WHERE user_id = ?''', (user_id,))
            return {'schema': schema, 'role': role, 'status': 'ready'}


def get_postgres_reader_password(user_id):
    """Server-only; never expose password to client, templates, logs or session."""
    _, role = names(user_id)
    verify_workspace_user(int(user_id))
    record = _get_record(int(user_id))
    if not record or record['reader_role'] != role or record['provisioning_status'] != 'ready':
        raise PermissionError('PostgreSQL workspace is not ready')
    return _decrypt(record['encrypted_password'])
