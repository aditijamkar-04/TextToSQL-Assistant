
import re

from workspace_service import get_workspace_schema
from db import get_connection
from workspace_credentials import get_workspace_credentials
from workspace_service import get_workspace_login
from auth_db import verify_workspace_user



IDENTIFIER_PATTERN = re.compile(r"^[A-Za-z][A-Za-z0-9_]{0,127}$")

ALLOWED_TYPES = {
        # Integer
        "INT",
        "TINYINT",
        "BIGINT",
        "SMALLINT",

        # Numeric
        "NUMERIC(4)",
        "NUMERIC(5,2)",
        "NUMERIC(4,2)",
        "NUMERIC(6,2)",
        "NUMERIC(10,2)",
        "NUMERIC(18,2)",
        "NUMERIC(18,4)",

        # Other numeric
        "FLOAT",
        "REAL",

        # Money
        "MONEY",
        "SMALLMONEY",

        # Decimal
        "DECIMAL(4)",
        "DECIMAL(4,2)",
        "DECIMAL(6,2)",
        "DECIMAL(5,2)",
        "DECIMAL(10,2)",
        "DECIMAL(18,2)",
        "DECIMAL(18,4)",

        # Text
        "CHAR(10)",
        "VARCHAR(10)",
        "VARCHAR(50)",
        "VARCHAR(100)",
        "VARCHAR(255)",

        # Unicode text
        "NCHAR(10)",
        "NVARCHAR(10)",
        "NVARCHAR(50)",
        "NVARCHAR(100)",
        "NVARCHAR(255)",

        # Date and time
        "DATE",
        "TIME",
        "DATETIME",
        "SMALLDATETIME",
        "DATETIME2",
        "DATETIMEOFFSET",

        # Other
        "BIT",
        "UNIQUEIDENTIFIER",
        "BINARY(16)",
        "VARBINARY(10)"
}


def validate_identifier(value):
    if not isinstance(value, str):
        raise ValueError("Identifier must be a string.")

    if not IDENTIFIER_PATTERN.fullmatch(value):
        raise ValueError(
            "Invalid table or column name. "
            "Use letters, numbers, and underscores."
        )

    return f"[{value}]"


def build_create_table_sql(user_id, table_name, columns):
    """
    Build a CREATE TABLE statement restricted to
    the authenticated user's private schema.

    This function generates SQL but does not execute it.
    """
    if (
        not isinstance(user_id, int)
        or isinstance(user_id, bool)
        or user_id <= 0
    ):
        raise ValueError("Invalid user ID.")

    quoted_table = validate_identifier(table_name)

    if not isinstance(columns, list) or not (1 <= len(columns) <= 50):
        raise ValueError("Provide between 1 and 50 columns.")

    schema_name = get_workspace_schema(user_id)
    quoted_schema = validate_identifier(schema_name)

    definitions = []
    used_names = set()

    for column in columns:
        if not isinstance(column, dict):
            raise ValueError("Invalid column definition.")

        if set(column) != {"name", "type"}:
            raise ValueError(
                "Each column must contain only name and type."
            )

        column_name = column["name"]
        quoted_column = validate_identifier(column_name)

        normalized_name = column_name.casefold()

        if normalized_name in used_names:
            raise ValueError("Duplicate column name.")

        used_names.add(normalized_name)

        data_type = column["type"]

        if not isinstance(data_type, str):
            raise ValueError("Invalid column data type.")

        data_type = data_type.strip().upper()

        if data_type not in ALLOWED_TYPES:
            raise ValueError(
                f"Unsupported data type: {data_type}"
            )

        definitions.append(
            f"    {quoted_column} {data_type}"
        )

    column_sql = ",\n".join(definitions)

    return (
        f"CREATE TABLE {quoted_schema}.{quoted_table} (\n"
        f"{column_sql}\n"
        f")"
    )




def create_workspace_table(user_id, table_name, columns):
    """
    Create a validated table in a user's private workspace.

    This function must only be called by trusted server-side
    code after verifying the authenticated user's identity.
    """

    # Validate all inputs and generate SQL.
    sql = build_create_table_sql(
        user_id=user_id,
        table_name=table_name,
        columns=columns,
    )

    # Verify that the account exists, is active,
    # and belongs to an ordinary user.
    verify_workspace_user(user_id)

    # Verify that the user's private workspace is ready.
    credentials = get_workspace_credentials(user_id)

    if not credentials or not credentials.get("login"):
        raise RuntimeError(
            "User workspace credentials are not ready."
        )

    expected_login = get_workspace_login(user_id)

    if credentials["login"] != expected_login:
        raise RuntimeError(
            "Workspace login mismatch."
        )

    # Open the privileged connection only after verification.
    connection = get_connection()
    connection.timeout = 10

    if connection.autocommit:
        connection.close()
        raise RuntimeError(
            "Table creation requires transactional execution."
        )

    try:
        # Lock this workspace before checking its table count.
        lock_workspace_table_creation(
            connection,
            user_id,
        )

        # Count tables while holding the transaction lock.
        table_count = count_workspace_tables(
            connection,
            user_id,
        )

        if table_count >= MAX_WORKSPACE_TABLES:
            raise ValueError(
                f"Workspace table limit reached. "
                f"Maximum allowed: {MAX_WORKSPACE_TABLES}."
            )

        cursor = connection.cursor()



        # Execute only the SQL produced by our validator.
        cursor.execute(sql)

        connection.commit()
        cursor.close()

        return {
            "status": "success",
            "schema": get_workspace_schema(user_id),
            "table": table_name,
            "message": "Table created successfully.",
        }

    except Exception:
        connection.rollback()
        raise

    finally:
        connection.close()


MAX_WORKSPACE_TABLES = 20


def count_workspace_tables(connection, user_id):
    """
    Count tables in the specified user's private schema.
    Uses the existing server-side connection.
    """
    schema_name = get_workspace_schema(user_id)

    cursor = connection.cursor()
    cursor.execute(
        """
        SELECT COUNT(*)
        FROM sys.tables AS t
        INNER JOIN sys.schemas AS s
            ON t.schema_id = s.schema_id
        WHERE s.name = ?
        """,
        (schema_name,),
    )

    return int(cursor.fetchone()[0])

def lock_workspace_table_creation(connection, user_id):
    """
    Acquire a transaction-scoped SQL Server application lock
    for table creation in one user's workspace.
    """
    if (
        not isinstance(user_id, int)
        or isinstance(user_id, bool)
        or user_id <= 0
    ):
        raise ValueError("Invalid user ID.")

    cursor = connection.cursor()



    cursor.execute(
        """
        DECLARE @result INT;

        EXEC @result = sys.sp_getapplock
            @Resource = ?,
            @LockMode = 'Exclusive',
            @LockOwner = 'Transaction',
            @LockTimeout = 10000;

        SELECT @result;
        """,
        (f"workspace_table_creation_{user_id}",),
    )

    result = cursor.fetchone()

    if result is None or result[0] is None or result[0] < 0:
        raise RuntimeError(
            "Could not acquire workspace table creation lock."
        )

    # Close the lock cursor after reading its result.
    cursor.close()


def list_workspace_tables(user_id):
    """List tables and columns from the signed-in user's private schema."""

    if (
        not isinstance(user_id, int)
        or isinstance(user_id, bool)
        or user_id <= 0
    ):
        raise ValueError("Invalid user ID.")

    verify_workspace_user(user_id)

    schema_name = get_workspace_schema(user_id)
    connection = get_connection()

    try:
        cursor = connection.cursor()
        cursor.execute(
            """
            SELECT
                t.name AS table_name,
                c.name AS column_name,
                ty.name AS data_type,
                c.max_length,
                c.precision,
                c.scale
            FROM sys.tables AS t
            INNER JOIN sys.schemas AS s
                ON t.schema_id = s.schema_id
            INNER JOIN sys.columns AS c
                ON c.object_id = t.object_id
            INNER JOIN sys.types AS ty
                ON c.user_type_id = ty.user_type_id
            WHERE s.name = ?
            ORDER BY t.name, c.column_id
            """,
            (schema_name,),
        )

        tables = {}

        for row in cursor.fetchall():
            name = row.table_name

            if name not in tables:
                tables[name] = {
                    "name": name,
                    "columns": [],
                }

            data_type = row.data_type.upper()

            if data_type in ("VARCHAR", "CHAR", "NVARCHAR", "NCHAR"):
                length = row.max_length

                if length == -1:
                    data_type += "(MAX)"
                else:
                    if data_type.startswith("N"):
                        length //= 2
                    data_type += f"({length})"

            elif data_type in ("DECIMAL", "NUMERIC"):
                data_type += f"({row.precision},{row.scale})"

            tables[name]["columns"].append({
                "name": row.column_name,
                "type": data_type,
            })

        return list(tables.values())

    finally:
        connection.rollback()
        connection.close()



def insert_workspace_record(user_id, table_name, values):
    """
    Insert one record into a table belonging to the
    authenticated user's private SQL Server workspace.
    """

    if (
        not isinstance(user_id, int)
        or isinstance(user_id, bool)
        or user_id <= 0
    ):
        raise ValueError("Invalid user ID.")

    verify_workspace_user(user_id)

    quoted_table = validate_identifier(table_name)

    if not isinstance(values, dict) or not values:
        raise ValueError("Provide at least one column value.")

    if len(values) > 50:
        raise ValueError("Too many column values.")

    schema_name = get_workspace_schema(user_id)
    quoted_schema = validate_identifier(schema_name)

    connection = get_connection()
    connection.timeout = 10

    if connection.autocommit:
        connection.close()
        raise RuntimeError("Insert requires a transaction.")

    try:
        cursor = connection.cursor()

        # Check the actual table and columns in this user's schema.
        cursor.execute(
            """
            SELECT c.name, c.is_identity, c.is_computed,
                   ty.name AS data_type
            FROM sys.tables AS t
            JOIN sys.schemas AS s
                ON s.schema_id = t.schema_id
            JOIN sys.columns AS c
                ON c.object_id = t.object_id
            JOIN sys.types AS ty
                ON ty.user_type_id = c.user_type_id
            WHERE s.name = ?
              AND t.name = ?
            ORDER BY c.column_id
            """,
            (schema_name, table_name),
        )

        metadata = cursor.fetchall()

        if not metadata:
            raise ValueError("Table not found in your workspace.")

        available = {
            row.name.casefold(): row
            for row in metadata
        }

        quoted_columns = []
        parameters = []
        used_names = set()

        for column_name, value in values.items():
            quoted_column = validate_identifier(column_name)
            normalized = column_name.casefold()

            if normalized in used_names:
                raise ValueError("Duplicate column name.")

            used_names.add(normalized)

            column = available.get(normalized)

            if column is None:
                raise ValueError(
                    f"Column '{column_name}' does not exist."
                )

            if column.is_identity or column.is_computed:
                raise ValueError(
                    f"Column '{column_name}' cannot be inserted manually."
                )

            if isinstance(value, (dict, list)):
                raise ValueError("Invalid column value.")

            if value is not None and not isinstance(
                value, (str, int, float, bool)
            ):
                raise ValueError("Invalid column value.")

            quoted_columns.append(
                validate_identifier(column.name)
            )
            parameters.append(value)

        column_sql = ", ".join(quoted_columns)
        placeholders = ", ".join(
            "?" for _ in parameters
        )

        sql = (
            f"INSERT INTO {quoted_schema}.{quoted_table} "
            f"({column_sql}) VALUES ({placeholders})"
        )

        # Values are parameterized, never concatenated into SQL.
        cursor.execute(sql, tuple(parameters))

        connection.commit()

        return {
            "status": "success",
            "message": "Record inserted successfully.",
            "table": table_name,
        }

    except Exception:
        connection.rollback()
        raise

    finally:
        connection.close()


def view_workspace_records(user_id, table_name):
    """
    Read up to 100 records from a table belonging
    to the authenticated user's private workspace.
    """

    if (
        not isinstance(user_id, int)
        or isinstance(user_id, bool)
        or user_id <= 0
    ):
        raise ValueError("Invalid user ID.")

    verify_workspace_user(user_id)

    quoted_table = validate_identifier(table_name)
    schema_name = get_workspace_schema(user_id)
    quoted_schema = validate_identifier(schema_name)

    connection = get_connection()
    connection.timeout = 10

    try:
        cursor = connection.cursor()

        # Verify the table belongs to this user's schema.
        cursor.execute(
            """
            SELECT COUNT(*)
            FROM sys.tables AS t
            JOIN sys.schemas AS s
                ON t.schema_id = s.schema_id
            WHERE s.name = ?
              AND t.name = ?
            """,
            (schema_name, table_name),
        )

        if cursor.fetchone()[0] == 0:
            raise ValueError("Table not found in your workspace.")

        # Read-only query with a fixed maximum row count.
        cursor.execute(
            f"SELECT TOP (100) * "
            f"FROM {quoted_schema}.{quoted_table}"
        )

        columns = [
            description[0]
            for description in cursor.description
        ]

        rows = []

        for record in cursor.fetchall():
            rows.append([
                str(value) if value is not None else None
                for value in record
            ])

        return {
            "table": table_name,
            "columns": columns,
            "rows": rows,
            "count": len(rows),
        }

    finally:
        connection.rollback()
        connection.close()


def _get_primary_key(cursor, schema, table):
    cursor.execute("""
        SELECT c.name
        FROM sys.indexes i
        JOIN sys.index_columns ic
          ON i.object_id = ic.object_id
         AND i.index_id = ic.index_id
        JOIN sys.columns c
          ON c.object_id = ic.object_id
         AND c.column_id = ic.column_id
        JOIN sys.tables t ON t.object_id = i.object_id
        JOIN sys.schemas s ON s.schema_id = t.schema_id
        WHERE s.name = ?
          AND t.name = ?
          AND i.is_primary_key = 1
        ORDER BY ic.key_ordinal
    """, (schema, table))
    return [row[0] for row in cursor.fetchall()]


def _get_editable_columns(cursor, schema, table):
    cursor.execute("""
        SELECT c.name
        FROM sys.columns c
        JOIN sys.tables t ON t.object_id = c.object_id
        JOIN sys.schemas s ON s.schema_id = t.schema_id
        WHERE s.name = ?
          AND t.name = ?
          AND c.is_identity = 0
          AND c.is_computed = 0
          AND c.system_type_id <> 189
    """, (schema, table))
    return [row[0] for row in cursor.fetchall()]


def modify_workspace_record(
    user_id,
    table_name,
    keys,
    values=None,
    delete=False
):
    if (
        not isinstance(user_id, int)
        or isinstance(user_id, bool)
        or user_id <= 0
    ):
        raise ValueError("Invalid user ID.")

    verify_workspace_user(user_id)

    quoted_table = validate_identifier(table_name)

    if not isinstance(keys, dict) or not keys:
        raise ValueError("Primary key values are required.")

    if not delete:
        if not isinstance(values, dict) or not values:
            raise ValueError("Provide fields to update.")

        if len(values) > 50:
            raise ValueError("Too many fields.")

    schema = get_workspace_schema(user_id)
    quoted_schema = validate_identifier(schema)

    connection = get_connection()
    connection.timeout = 10

    if connection.autocommit:
        connection.close()
        raise RuntimeError("Record changes require a transaction.")

    try:
        cursor = connection.cursor()

        primary_keys = _get_primary_key(
            cursor,
            schema,
            table_name
        )

        if not primary_keys:
            raise ValueError(
                "This table has no primary key. "
                "Editing and deletion are disabled."
            )

        if (
            len(keys) != len(primary_keys)
            or set(keys) != set(primary_keys)
        ):
            raise ValueError("Incorrect primary key fields.")

        for name in keys:
            validate_identifier(name)

        editable = set(
            _get_editable_columns(
                cursor,
                schema,
                table_name
            )
        )

        if not set(primary_keys).issubset(editable):
            raise ValueError(
                "This table's primary key is not supported."
            )

        key_values = [
            keys[name]
            for name in primary_keys
        ]

        for value in key_values:
            if value is None or isinstance(value, (dict, list)):
                raise ValueError("Invalid primary key value.")

            if not isinstance(value, (str, int, float, bool)):
                raise ValueError("Invalid primary key value.")

        where_clause = " AND ".join(
            f"{validate_identifier(name)} = ?"
            for name in primary_keys
        )

        table_sql = f"{quoted_schema}.{quoted_table}"

        if delete:
            sql = (
                f"DELETE FROM {table_sql} "
                f"WHERE {where_clause}"
            )
            parameters = key_values

        else:
            for name, value in values.items():
                validate_identifier(name)

                if isinstance(value, (dict, list)):
                    raise ValueError("Invalid update value.")

                if value is not None and not isinstance(
                    value, (str, int, float, bool)
                ):
                    raise ValueError("Invalid update value.")

            allowed = editable - set(primary_keys)

            if not set(values).issubset(allowed):
                raise ValueError(
                    "Invalid or protected update field."
                )

            assignments = ", ".join(
                f"{validate_identifier(name)} = ?"
                for name in values
            )

            sql = (
                f"UPDATE {table_sql} "
                f"SET {assignments} "
                f"WHERE {where_clause}"
            )

            parameters = list(values.values()) + key_values

        cursor.execute(sql, tuple(parameters))

        if cursor.rowcount != 1:
            raise ValueError(
                "Record not found or more than one record affected."
            )

        connection.commit()

        return {
            "status": "success",
            "message": (
                "Record deleted successfully."
                if delete
                else "Record updated successfully."
            )
        }

    except Exception:
        connection.rollback()
        raise

    finally:
        connection.close()


def get_workspace_record_keys(user_id, table_name):
    """Read primary key columns from the user's own table."""

    if (
        not isinstance(user_id, int)
        or isinstance(user_id, bool)
        or user_id <= 0
    ):
        raise ValueError("Invalid user ID.")

    verify_workspace_user(user_id)

    validate_identifier(table_name)

    schema = get_workspace_schema(user_id)
    validate_identifier(schema)

    connection = get_connection()

    try:
        cursor = connection.cursor()

        cursor.execute(
            """
            SELECT COUNT(*)
            FROM sys.tables AS t
            JOIN sys.schemas AS s
                ON s.schema_id = t.schema_id
            WHERE s.name = ?
              AND t.name = ?
            """,
            (schema, table_name)
        )

        if cursor.fetchone()[0] != 1:
            raise ValueError(
                "Table not found in your workspace."
            )

        primary_keys = _get_primary_key(
            cursor,
            schema,
            table_name
        )

        return {
            "primary_keys": primary_keys
        }

    finally:
        connection.rollback()
        connection.close()



def add_workspace_column(
    user_id,
    table_name,
    column_name,
    data_type
):
    """
    Add a new nullable column to an existing table
    in the authenticated user's private workspace.
    """

    if (
        not isinstance(user_id, int)
        or isinstance(user_id, bool)
        or user_id <= 0
    ):
        raise ValueError("Invalid user ID.")

    verify_workspace_user(user_id)

    quoted_table = validate_identifier(table_name)
    quoted_column = validate_identifier(column_name)

    if not isinstance(data_type, str):
        raise ValueError("Invalid column data type.")

    data_type = data_type.strip().upper()

    if data_type not in ALLOWED_TYPES:
        raise ValueError(
            f"Unsupported data type: {data_type}"
        )

    schema_name = get_workspace_schema(user_id)
    quoted_schema = validate_identifier(schema_name)

    connection = get_connection()
    connection.timeout = 10

    if connection.autocommit:
        connection.close()
        raise RuntimeError(
            "Adding a column requires a transaction."
        )

    try:
        cursor = connection.cursor()

        # Verify that the table belongs to this workspace.
        cursor.execute(
            """
            SELECT c.name
            FROM sys.tables AS t
            INNER JOIN sys.schemas AS s
                ON s.schema_id = t.schema_id
            INNER JOIN sys.columns AS c
                ON c.object_id = t.object_id
            WHERE s.name = ?
              AND t.name = ?
            """,
            (schema_name, table_name),
        )

        existing_columns = [
            row.name.casefold()
            for row in cursor.fetchall()
        ]

        if not existing_columns:
            raise ValueError(
                "Table not found in your workspace."
            )

        # Prevent duplicate column names.
        if column_name.casefold() in existing_columns:
            raise ValueError(
                f"Column '{column_name}' already exists."
            )

        # Add the new nullable column.
        sql = (
            f"ALTER TABLE {quoted_schema}.{quoted_table} "
            f"ADD {quoted_column} {data_type} NULL"
        )

        cursor.execute(sql)
        connection.commit()

        return {
            "status": "success",
            "message": "Column added successfully.",
            "table": table_name,
            "column": column_name,
            "data_type": data_type,
        }

    except Exception:
        connection.rollback()
        raise

    finally:
        connection.close()




def _run_workspace_table_ddl(user_id, table_name, operation):
    """Run a validated DDL operation on a table in the user's workspace."""

    if (
        not isinstance(user_id, int)
        or isinstance(user_id, bool)
        or user_id <= 0
    ):
        raise ValueError("Invalid user ID.")

    verify_workspace_user(user_id)
    quoted_table = validate_identifier(table_name)
    schema = get_workspace_schema(user_id)
    quoted_schema = validate_identifier(schema)

    connection = get_connection()
    connection.timeout = 10

    if connection.autocommit:
        connection.close()
        raise RuntimeError("Table changes require a transaction.")

    try:
        cursor = connection.cursor()

        cursor.execute(
            """
            SELECT t.object_id
            FROM sys.tables t
            JOIN sys.schemas s ON s.schema_id = t.schema_id
            WHERE s.name = ? AND t.name = ?
            """,
            (schema, table_name),
        )

        row = cursor.fetchone()

        if not row:
            raise ValueError("Table not found in your workspace.")

        result = operation(
            cursor,
            schema,
            quoted_schema,
            quoted_table,
            row[0],
        )

        connection.commit()
        return result

    except Exception:
        connection.rollback()
        raise

    finally:
        connection.close()


def delete_workspace_column(user_id, table_name, column_name):
    quoted_column = validate_identifier(column_name)

    def operation(cursor, schema, qs, qt, object_id):
        cursor.execute(
            """
            SELECT column_id
            FROM sys.columns
            WHERE object_id = ? AND name = ?
            """,
            (object_id, column_name),
        )
        row = cursor.fetchone()

        if not row:
            raise ValueError("Column not found.")

        column_id = row[0]

        cursor.execute(
            "SELECT COUNT(*) FROM sys.columns WHERE object_id = ?",
            (object_id,),
        )
        if cursor.fetchone()[0] <= 1:
            raise ValueError("Cannot delete the last column.")

        cursor.execute(
            """
            SELECT COUNT(*)
            FROM sys.index_columns
            WHERE object_id = ? AND column_id = ?
            """,
            (object_id, column_id),
        )
        if cursor.fetchone()[0]:
            raise ValueError(
                "Cannot delete a column used by an index or primary key."
            )

        cursor.execute(
            """
            SELECT COUNT(*)
            FROM sys.foreign_key_columns
            WHERE (parent_object_id = ? AND parent_column_id = ?)
               OR (referenced_object_id = ? AND referenced_column_id = ?)
            """,
            (object_id, column_id, object_id, column_id),
        )
        if cursor.fetchone()[0]:
            raise ValueError(
                "Cannot delete a column used by a foreign key."
            )

        cursor.execute(
            f"ALTER TABLE {qs}.{qt} DROP COLUMN {quoted_column}"
        )

        return {
            "status": "success",
            "message": "Column deleted successfully.",
        }

    return _run_workspace_table_ddl(user_id, table_name, operation)


def rename_workspace_column(user_id, table_name, old_name, new_name):
    old_column = validate_identifier(old_name)
    validate_identifier(new_name)

    def operation(cursor, schema, qs, qt, object_id):
        cursor.execute(
            "SELECT name FROM sys.columns WHERE object_id = ?",
            (object_id,),
        )
        names = [row[0].casefold() for row in cursor.fetchall()]

        if old_name.casefold() not in names:
            raise ValueError("Existing column not found.")

        if new_name.casefold() in names:
            raise ValueError("A column with the new name already exists.")

        object_name = f"{qs}.{qt}.{old_column}"

        cursor.execute(
            "EXEC sys.sp_rename ?, ?, 'COLUMN'",
            (object_name, new_name),
        )

        return {
            "status": "success",
            "message": "Column renamed successfully.",
        }

    return _run_workspace_table_ddl(user_id, table_name, operation)


def modify_workspace_column(
    user_id,
    table_name,
    column_name,
    data_type,
    nullable=True,
):
    quoted_column = validate_identifier(column_name)

    if not isinstance(data_type, str):
        raise ValueError("Invalid data type.")

    data_type = data_type.strip().upper()

    if data_type not in ALLOWED_TYPES:
        raise ValueError("Unsupported data type.")

    if not isinstance(nullable, bool):
        raise ValueError("Nullable must be true or false.")

    def operation(cursor, schema, qs, qt, object_id):
        cursor.execute(
            """
            SELECT is_identity, is_computed
            FROM sys.columns
            WHERE object_id = ? AND name = ?
            """,
            (object_id, column_name),
        )
        row = cursor.fetchone()

        if not row:
            raise ValueError("Column not found.")

        if row[0] or row[1]:
            raise ValueError(
                "Identity or computed columns cannot be modified here."
            )

        null_option = "NULL" if nullable else "NOT NULL"

        cursor.execute(
            f"ALTER TABLE {qs}.{qt} ALTER COLUMN "
            f"{quoted_column} {data_type} {null_option}"
        )

        return {
            "status": "success",
            "message": "Column modified successfully.",
        }

    return _run_workspace_table_ddl(user_id, table_name, operation)


def rename_workspace_table(user_id, old_name, new_name):
    validate_identifier(new_name)

    def operation(cursor, schema, qs, qt, object_id):
        cursor.execute(
            """
            SELECT COUNT(*)
            FROM sys.tables t
            JOIN sys.schemas s ON s.schema_id = t.schema_id
            WHERE s.name = ? AND t.name = ?
            """,
            (schema, new_name),
        )

        if cursor.fetchone()[0]:
            raise ValueError("A table with the new name already exists.")

        cursor.execute(
            "EXEC sys.sp_rename ?, ?, 'OBJECT'",
            (f"{qs}.{qt}", new_name),
        )

        return {
            "status": "success",
            "message": "Table renamed successfully.",
        }

    return _run_workspace_table_ddl(user_id, old_name, operation)


def delete_workspace_table(user_id, table_name):
    def operation(cursor, schema, qs, qt, object_id):
        cursor.execute(f"DROP TABLE {qs}.{qt}")

        return {
            "status": "success",
            "message": "Table deleted successfully.",
        }

    return _run_workspace_table_ddl(user_id, table_name, operation)
