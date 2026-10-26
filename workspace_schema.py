
from workspace_db import get_user_workspace_connection
from workspace_service import get_workspace_schema


def get_database_schema(user_id):
    """
    Read the tables and columns visible in
    the user's private SQL Server schema.
    """
    schema_name = get_workspace_schema(user_id)

    connection = get_user_workspace_connection(user_id)

    try:
        cursor = connection.cursor()

        try:
            cursor.execute(
                """
                SELECT
                    t.TABLE_NAME,
                    c.COLUMN_NAME,
                    c.DATA_TYPE,
                    c.CHARACTER_MAXIMUM_LENGTH
                FROM INFORMATION_SCHEMA.TABLES AS t
                JOIN INFORMATION_SCHEMA.COLUMNS AS c
                    ON t.TABLE_SCHEMA = c.TABLE_SCHEMA
                   AND t.TABLE_NAME = c.TABLE_NAME
                WHERE t.TABLE_SCHEMA = ?
                  AND t.TABLE_TYPE = 'BASE TABLE'
                ORDER BY
                    t.TABLE_NAME,
                    c.ORDINAL_POSITION
                """,
                (schema_name,),
            )

            rows = cursor.fetchall()

        finally:
            cursor.close()

    finally:
        connection.close()

    if not rows:
        return (
            f"SQL Server schema: {schema_name}\n"
            "No tables currently exist in this workspace."
        )

    schema_lines = [
        "SQL Server (T-SQL)",
        f"Workspace schema: {schema_name}",
        "",
    ]

    current_table = None

    for table_name, column_name, data_type, length in rows:
        if table_name != current_table:
            if current_table is not None:
                schema_lines.append("")

            current_table = table_name

            schema_lines.append(
                f"Table: [{schema_name}].[{table_name}]"
            )

        column_type = data_type.upper()

        if length is not None and data_type.lower() in {
            "varchar",
            "nvarchar",
            "char",
            "nchar",
            "binary",
            "varbinary",
        }:
            size = "MAX" if length == -1 else str(length)
            column_type += f"({size})"

        schema_lines.append(
            f"- [{column_name}] {column_type}"
        )

    return "\n".join(schema_lines)
