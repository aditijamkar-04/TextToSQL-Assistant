
import os
import secrets
import sys
from urllib.parse import urlsplit

from dotenv import load_dotenv

load_dotenv(
    r"D:\Projects\Py_SQL_Projects\TextToSQL-Assistant\.env",
    override=True,
)

test = os.getenv("MIGRATION_TEST_DATABASE_URL", "")
prod = os.getenv("DATABASE_URL", "")

if not test or not prod:
    sys.exit("STOP: Both database URLs must be configured")

th = urlsplit(test).hostname
ph = urlsplit(prod).hostname

if not th or th == ph or not th.startswith("ep-late-breeze-b4js7ehb"):
    sys.exit("STOP: Unexpected staging endpoint")

os.environ["DATABASE_URL"] = test
os.environ["WORKSPACE_BACKEND"] = "postgres"
os.environ["POSTGRES_STAGING_READY"] = "1"
os.environ["DEMO_MODE"] = "1"

import psycopg
from psycopg import sql
from postgres_workspace_provisioning import (
    provision_postgres_workspace,
    get_postgres_reader_password,
)
from postgres_restricted_query import (
    _reader_dsn,
    names,
    execute_restricted_select,
)
from postgres_workspace_tables import (
    insert_workspace_record,
    view_workspace_records,
    modify_workspace_record,
    get_workspace_record_keys,
    list_workspace_tables,
)

user_id = 26
schema, role = names(user_id)
table = "staging_check_" + secrets.token_hex(4)
created = False

password = get_postgres_reader_password(user_id)
if not password:
    sys.exit("STOP: Reader credentials unavailable")

print("Testing staging user 26.")

try:
    with psycopg.connect(test, connect_timeout=10) as owner:
        with owner.cursor() as cur:
            cur.execute(
                sql.SQL(
                    "CREATE TABLE {}.{} "
                    "(id INTEGER PRIMARY KEY, label VARCHAR(100))"
                ).format(
                    sql.Identifier(schema),
                    sql.Identifier(table),
                )
            )
    created = True
    print("PASS: Test table created")

    insert_workspace_record(
        user_id, table, {"id": 1, "label": "first"}
    )

    assert view_workspace_records(user_id, table)["rows"] == [
        ["1", "first"]
    ]

    assert get_workspace_record_keys(
        user_id, table
    )["primary_keys"] == ["id"]

    assert any(
        t["name"] == table
        for t in list_workspace_tables(user_id)
    )

    print("PASS: Insert, read, list, and primary key")

    modify_workspace_record(
        user_id,
        table,
        {"id": 1},
        {"label": "updated"},
    )

    assert view_workspace_records(user_id, table)["rows"] == [
        ["1", "updated"]
    ]

    print("PASS: Update")

    result = execute_restricted_select(
        f'SELECT id, label FROM "{schema}"."{table}"',
        user_id,
        password,
    )

    assert result["rows"] == [[1, "updated"]]
    print("PASS: Restricted SELECT")

    with psycopg.connect(
        _reader_dsn(role, password),
        connect_timeout=10,
    ) as reader:
        with reader.cursor() as cur:
            for privilege in ("INSERT", "UPDATE", "DELETE"):
                cur.execute(
                    "SELECT has_table_privilege("
                    "current_user, %s, %s)",
                    (f"{schema}.{table}", privilege),
                )
                assert cur.fetchone()[0] is False

    print("PASS: Reader has no write privileges")

    try:
        execute_restricted_select(
            f'DELETE FROM "{schema}"."{table}"',
            user_id,
            password,
        )
    except (ValueError, PermissionError):
        print("PASS: Generated SQL write blocked")
    else:
        raise AssertionError("Generated SQL write accepted")

    modify_workspace_record(
        user_id, table, {"id": 1}, delete=True
    )

    assert view_workspace_records(user_id, table)["rows"] == []
    print("PASS: Delete")

    provision_postgres_workspace(user_id)

    assert get_postgres_reader_password(user_id) == password
    print("PASS: Password unchanged after retry")

    print("ALL STAGING DATABASE CHECKS PASSED")

finally:
    if created:
        with psycopg.connect(test, connect_timeout=10) as owner:
            with owner.cursor() as cur:
                cur.execute(
                    sql.SQL(
                        "DROP TABLE IF EXISTS {}.{}"
                    ).format(
                        sql.Identifier(schema),
                        sql.Identifier(table),
                    )
                )
        print("Cleanup: Test table removed")
