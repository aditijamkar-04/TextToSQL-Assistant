"""Phase 3 PostgreSQL workspace CRUD implementation (staging module).

NOT wired to app.py. Trusted server-side use only, after authenticating the
caller and verifying user_id is an active ordinary user. DATABASE_URL must be
owner/admin connection; NEVER pass AI-generated SQL to this module.
"""
import os
import re

from psycopg import connect, sql

_IDENTIFIER = re.compile(r"^[A-Za-z][A-Za-z0-9_]{0,62}$")
_TYPES = {
    "INT": "INTEGER", "BIGINT": "BIGINT", "SMALLINT": "SMALLINT",
    "BIT": "BOOLEAN", "DATE": "DATE", "DATETIME2": "TIMESTAMP",
    "FLOAT": "DOUBLE PRECISION", "DECIMAL(10,2)": "DECIMAL(10,2)",
    "DECIMAL(18,2)": "DECIMAL(18,2)", "VARCHAR(50)": "VARCHAR(50)",
    "VARCHAR(100)": "VARCHAR(100)", "VARCHAR(255)": "VARCHAR(255)",
    "NVARCHAR(100)": "VARCHAR(100)", "NVARCHAR(255)": "VARCHAR(255)",
}
MAX_TABLES = 20
MAX_ROWS = 100


def _id(value):
    if not isinstance(value, str) or not _IDENTIFIER.fullmatch(value):
        raise ValueError("Invalid SQL identifier (maximum 63 characters).")
    return value


def _schema(user_id):
    if isinstance(user_id, bool):
        raise ValueError("Invalid user ID.")
    try:
        n = int(user_id)
    except (ValueError, TypeError) as exc:
        raise ValueError("Invalid user ID.") from exc
    if n <= 0 or str(n) != str(user_id).strip():
        raise ValueError("Invalid user ID.")
    return f"workspace_{n}"


def _authorize(user_id):
    # Prevent trusting a caller-supplied user ID without an active account check.
    from auth_db import verify_workspace_user
    verify_workspace_user(int(user_id))


def _connect():
    url = os.environ.get("DATABASE_URL", "").strip()

    if not url:
        raise RuntimeError("DATABASE_URL is missing.")

    conn = connect(url, connect_timeout=10)

    try:
        # Set a 10-second limit for SQL statements in this
        # transaction. Compatible with Neon transaction pooling.
        conn.execute("SET LOCAL statement_timeout = '10s'")
        return conn
    except Exception:
        conn.close()
        raise


def _table_exists(cur, schema, table):
    cur.execute("""SELECT EXISTS (
        SELECT 1 FROM information_schema.tables
        WHERE table_schema = %s AND table_name = %s AND table_type = 'BASE TABLE'
    )""", (schema, table))
    if not cur.fetchone()[0]:
        raise ValueError("Table not found in your workspace.")


def _columns(cur, schema, table):
    cur.execute("""SELECT column_name, data_type, is_generated, is_identity
        FROM information_schema.columns
        WHERE table_schema = %s AND table_name = %s
        ORDER BY ordinal_position""", (schema, table))
    return cur.fetchall()


def _pk(cur, schema, table):
    cur.execute("""SELECT a.attname FROM pg_catalog.pg_index i
        JOIN pg_catalog.pg_class t ON t.oid = i.indrelid
        JOIN pg_catalog.pg_namespace n ON n.oid = t.relnamespace
        JOIN pg_catalog.pg_attribute a ON a.attrelid = t.oid
            AND a.attnum = ANY(i.indkey)
        WHERE n.nspname = %s AND t.relname = %s AND i.indisprimary
        ORDER BY array_position(i.indkey::smallint[], a.attnum)""", (schema, table))
    return [row[0] for row in cur.fetchall()]




def build_create_table_sql(user_id, table_name, columns, primary_key=None):
    """Build safe CREATE TABLE SQL with one required primary key."""
    schema, table = _schema(user_id), _id(table_name)

    if not isinstance(columns, list) or not 1 <= len(columns) <= 50:
        raise ValueError("Provide between 1 and 50 columns.")

    if not isinstance(primary_key, str) or not primary_key.strip():
        raise ValueError("Select a primary-key column.")

    primary_key = _id(primary_key)
    seen = set()
    definitions = []
    column_names = []

    for col in columns:
        if not isinstance(col, dict) or set(col) != {"name", "type"}:
            raise ValueError("Invalid column definition.")

        name = _id(col["name"])

        if name.casefold() in seen:
            raise ValueError("Duplicate column name.")

        seen.add(name.casefold())
        column_names.append(name)

        datatype = col["type"]
        if (
            not isinstance(datatype, str)
            or datatype.strip().upper() not in _TYPES
        ):
            raise ValueError("Unsupported column type.")

        definitions.append(
            sql.SQL("{} {}").format(
                sql.Identifier(name),
                sql.SQL(_TYPES[datatype.strip().upper()])
            )
        )


        
        if primary_key is not None:
            if not isinstance(primary_key, str) or not primary_key.strip():
                raise ValueError("Select a valid primary key.")

            matching_columns = [
                col["name"]
                for col in columns
                if isinstance(col, dict)
                and isinstance(col.get("name"), str)
                and col["name"].casefold() == primary_key.casefold()
            ]

            if len(matching_columns) != 1:
                raise ValueError("Primary key must match one of the table columns.")

            definitions.append(
                sql.SQL("PRIMARY KEY ({})").format(
                    sql.Identifier(matching_columns[0])
                )
            )


        matching_columns = [
            name for name in column_names
            if name.casefold() == primary_key.casefold()
        ]

        if len(matching_columns) != 1:
            raise ValueError("Primary key must match one of the table columns.")

        primary_key = matching_columns[0]

        definitions.append(
            sql.SQL("PRIMARY KEY ({})").format(
                sql.Identifier(primary_key)
            )
        )   

    return sql.SQL("CREATE TABLE {}.{} ({})").format(
        sql.Identifier(schema),
        sql.Identifier(table),
        sql.SQL(", ").join(definitions)
    )



def create_workspace_table(user_id, table_name, columns, primary_key=None):
    schema = _schema(user_id)

    statement = build_create_table_sql(
        user_id, table_name, columns, primary_key
    )

    _authorize(user_id)

    with _connect() as conn, conn.cursor() as cur:
        cur.execute(
            "SELECT pg_advisory_xact_lock(%s, %s)",
            (720614, int(user_id))
        )

        cur.execute(
            "SELECT EXISTS(SELECT 1 FROM pg_namespace WHERE nspname=%s)",
            (schema,)
        )

        if not cur.fetchone()[0]:
            raise RuntimeError("Workspace schema has not been provisioned.")

        cur.execute(
            """SELECT COUNT(*)
               FROM information_schema.tables
               WHERE table_schema=%s AND table_type='BASE TABLE'""",
            (schema,)
        )

        if cur.fetchone()[0] >= MAX_TABLES:
            raise ValueError("Workspace table limit reached.")

        cur.execute(statement)

    return {
        "status": "success",
        "schema": schema,
        "table": table_name,
        "message": "Table created successfully."
    }


def list_workspace_tables(user_id):
    schema = _schema(user_id)
    _authorize(user_id)
    with _connect() as conn, conn.cursor() as cur:
        cur.execute("""SELECT c.table_name, c.column_name, c.data_type,
            c.character_maximum_length, c.numeric_precision, c.numeric_scale
            FROM information_schema.columns c
            JOIN information_schema.tables t ON t.table_schema=c.table_schema
                AND t.table_name=c.table_name
            WHERE c.table_schema=%s AND t.table_type='BASE TABLE'
            ORDER BY c.table_name, c.ordinal_position""", (schema,))
        result = {}
        for table, col, dtype, length, precision, scale in cur.fetchall():
            result.setdefault(table, {"name": table, "columns": []})["columns"].append(
                {"name": col, "type": (f"VARCHAR({length})" if dtype == "character varying" and length else
                    f"NUMERIC({precision},{scale})" if dtype == "numeric" and precision is not None and scale is not None else
                    dtype.upper())})
        return list(result.values())


def insert_workspace_record(user_id, table_name, values):
    schema, table = _schema(user_id), _id(table_name)
    if not isinstance(values, dict) or not 1 <= len(values) <= 50:
        raise ValueError("Provide between 1 and 50 column values.")
    names = [_id(k) for k in values]
    if len({k.casefold() for k in names}) != len(names):
        raise ValueError("Duplicate column names.")
    _authorize(user_id)
    with _connect() as conn, conn.cursor() as cur:
        _table_exists(cur, schema, table)
        allowed = {c[0] for c in _columns(cur, schema, table) if c[2] == 'NEVER' and c[3] == 'NO'}
        if not set(names) <= allowed:
            raise ValueError("Unknown or non-editable column.")
        cur.execute(sql.SQL("INSERT INTO {}.{} ({}) VALUES ({})").format(
            sql.Identifier(schema), sql.Identifier(table),
            sql.SQL(", ").join(map(sql.Identifier, names)),
            sql.SQL(", ").join([sql.Placeholder()] * len(names))), list(values.values()))
    return {"status": "success", "message": "Record inserted successfully.", "table": table}


def view_workspace_records(user_id, table_name):
    schema, table = _schema(user_id), _id(table_name)
    _authorize(user_id)
    with _connect() as conn, conn.cursor() as cur:
        _table_exists(cur, schema, table)
        cur.execute(sql.SQL("SELECT * FROM {}.{} LIMIT {}").format(
            sql.Identifier(schema), sql.Identifier(table), sql.Literal(MAX_ROWS)))
        columns = [c.name for c in cur.description]
        rows = [[str(v) if v is not None else None for v in row] for row in cur.fetchall()]
    return {"table": table, "columns": columns, "rows": rows, "count": len(rows)}


def get_workspace_record_keys(user_id, table_name):
    schema, table = _schema(user_id), _id(table_name)
    _authorize(user_id)
    with _connect() as conn, conn.cursor() as cur:
        _table_exists(cur, schema, table)
        return {"primary_keys": _pk(cur, schema, table)}


def modify_workspace_record(user_id, table_name, keys, values=None, delete=False):
    schema, table = _schema(user_id), _id(table_name)
    if not isinstance(keys, dict) or not keys:
        raise ValueError("Primary key values are required.")
    if not delete and (not isinstance(values, dict) or not 1 <= len(values) <= 50):
        raise ValueError("Provide fields to update.")
    _authorize(user_id)
    with _connect() as conn, conn.cursor() as cur:
        _table_exists(cur, schema, table)
        pk = _pk(cur, schema, table)
        if not pk:
            raise ValueError("This table has no primary key; editing is disabled.")
        if set(keys) != set(pk) or len(keys) != len(pk):
            raise ValueError("Incorrect primary key fields.")
        where = sql.SQL(" AND ").join(sql.SQL("{} = {}").format(
            sql.Identifier(k), sql.Placeholder()) for k in pk)
        if delete:
            stmt = sql.SQL("DELETE FROM {}.{} WHERE {}").format(
                sql.Identifier(schema), sql.Identifier(table), where)
            params = [keys[k] for k in pk]
        else:
            editable = {c[0] for c in _columns(cur, schema, table)
                        if c[2] == 'NEVER' and c[3] == 'NO'} - set(pk)
            if not set(values) <= editable or not all(_IDENTIFIER.fullmatch(k) for k in values):
                raise ValueError("Unknown or non-editable column.")
            assignments = sql.SQL(", ").join(sql.SQL("{} = {}").format(
                sql.Identifier(k), sql.Placeholder()) for k in values)
            stmt = sql.SQL("UPDATE {}.{} SET {} WHERE {}").format(
                sql.Identifier(schema), sql.Identifier(table), assignments, where)
            params = list(values.values()) + [keys[k] for k in pk]
        cur.execute(stmt, params)
        affected = cur.rowcount
        if affected != 1:
            raise ValueError("Expected exactly one matching record.")
    return {"status": "success", "message": "Record deleted successfully." if delete
            else "Record updated successfully.", "table": table}
