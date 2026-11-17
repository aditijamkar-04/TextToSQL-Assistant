"""Read-only preflight for a DISPOSABLE Neon test branch.

Run with DATABASE_URL set to the disposable branch's owner URL.
Does not create users, roles, schemas or change permissions.
Do not run against production without understanding the exposure report.
"""
import os
import sys


def main():
    url = os.environ.get('DATABASE_URL', '').strip()
    if not url:
        print('ERROR: DATABASE_URL is not set. Use a disposable Neon test branch.')
        return 2
    try:
        import psycopg
    except ImportError:
        print('ERROR: pip install psycopg[binary]')
        return 2
    with psycopg.connect(url, connect_timeout=10) as conn:
        with conn.cursor() as cur:
            cur.execute('SELECT current_database(), current_user, current_setting(%s)', ('server_version',))
            db, role, version = cur.fetchone()
            print(f'Database: {db}; connected role: {role}; PostgreSQL: {version}')
            cur.execute('''SELECT n.nspname FROM pg_namespace n
                WHERE n.nspname LIKE 'workspace\\_%' ESCAPE '\\'
                ORDER BY n.nspname LIMIT 30''')
            print('Existing workspace schemas:', ', '.join(r[0] for r in cur.fetchall()) or '(none)')
            cur.execute('''SELECT n.nspname,
                has_schema_privilege('public', n.oid, 'USAGE')
                FROM pg_namespace n WHERE n.nspname IN ('public')''')
            for schema, exposed in cur.fetchall():
                print(f'Schema {schema}: PUBLIC USAGE={exposed}')
            cur.execute('''SELECT table_schema, table_name,
                has_table_privilege('public', format('%I.%I', table_schema, table_name), 'SELECT')
                FROM information_schema.tables
                WHERE table_schema='public' AND table_type='BASE TABLE'
                ORDER BY table_name''')
            for schema, table, readable in cur.fetchall():
                print(f'Public schema table {table}: PUBLIC SELECT={readable}')
            cur.execute('''SELECT rolname, rolcanlogin, rolsuper, rolcreaterole
                FROM pg_roles WHERE rolname LIKE 'workspace_reader_%' ORDER BY rolname LIMIT 30''')
            for name, login, superuser, create_role in cur.fetchall():
                print(f'Reader role {name}: login={login}, superuser={superuser}, create_role={create_role}')
    print('Preflight finished. This is NOT a substitute for testing two restricted reader accounts.')
    return 0


if __name__ == '__main__':
    try:
        sys.exit(main())
    except Exception as exc:
        print(f'ERROR: {type(exc).__name__}: {exc.__class__.__name__} (details omitted to protect credentials)')
        sys.exit(1)
