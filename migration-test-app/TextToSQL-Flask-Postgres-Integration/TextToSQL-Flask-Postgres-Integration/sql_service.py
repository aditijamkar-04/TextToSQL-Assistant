
import re

import sqlglot
from sqlglot import exp

from workspace_db import get_user_workspace_connection

MAX_ROWS = 100
QUERY_TIMEOUT_SECONDS = 10

FORBIDDEN_NODE_TYPES = {
    "Insert",
    "Update",
    "Delete",
    "Drop",
    "Alter",
    "Create",
    "Merge",
    "Command",
    "Execute",
    "Grant",
    "Revoke",
    "Transaction",
    "TruncateTable",
    "Use",
    "Copy",
}

FORBIDDEN_FUNCTIONS = {
    "OPENROWSET",
    "OPENDATASOURCE",
    "OPENQUERY",
    "XP_CMDSHELL",
}


def _mask_comments_and_strings(sql):
    """
    Mask SQL comments and quoted text while preserving positions.
    Handles single quotes, double quotes, bracketed identifiers,
    single-line comments, and block comments.
    """
    result = list(sql)
    i = 0
    n = len(sql)

    while i < n:
        # Single-quoted string literal.
        if sql[i] == "'":
            result[i] = " "
            i += 1

            while i < n:
                result[i] = " "

                if sql[i] == "'":
                    if i + 1 < n and sql[i + 1] == "'":
                        result[i + 1] = " "
                        i += 2
                        continue

                    i += 1
                    break

                i += 1

        # Double-quoted identifier or string.
        elif sql[i] == '"':
            result[i] = " "
            i += 1

            while i < n:
                result[i] = " "

                if sql[i] == '"':
                    if i + 1 < n and sql[i + 1] == '"':
                        result[i + 1] = " "
                        i += 2
                        continue

                    i += 1
                    break

                i += 1

        # SQL Server bracketed identifier.
        elif sql[i] == "[":
            result[i] = " "
            i += 1

            while i < n:
                result[i] = " "

                if sql[i] == "]":
                    if i + 1 < n and sql[i + 1] == "]":
                        result[i + 1] = " "
                        i += 2
                        continue

                    i += 1
                    break

                i += 1

        # Single-line comment.
        elif sql.startswith("--", i):
            while i < n and sql[i] not in "\r\n":
                result[i] = " "
                i += 1

        # Block comment.
        elif sql.startswith("/*", i):
            result[i] = " "
            if i + 1 < n:
                result[i + 1] = " "

            i += 2

            while i < n and not sql.startswith("*/", i):
                result[i] = " "
                i += 1

            if i < n:
                result[i] = " "
                if i + 1 < n:
                    result[i + 1] = " "
                i += 2

        else:
            i += 1

    return "".join(result)


def validate_sql(sql):
    """
    Allow one read-only SELECT query using SQL Server T-SQL.

    Raises ValueError for empty, invalid, multi-statement,
    destructive, or disallowed SQL.
    """
    if not isinstance(sql, str) or not sql.strip():
        raise ValueError("SQL query cannot be empty.")

    query = sql.strip()

    # Check risky function names outside comments and quoted text.
    inspected_sql = _mask_comments_and_strings(query)

    risky_pattern = (
        r"\b(?:OPENROWSET|OPENDATASOURCE|OPENQUERY|XP_CMDSHELL)\b"
    )

    if re.search(
        risky_pattern,
        inspected_sql,
        flags=re.IGNORECASE,
    ):
        raise ValueError(
            "SQL Server external-access or system functions "
            "are not allowed."
        )

    # Parse using SQL Server T-SQL syntax.
    try:
        statements = [
            statement
            for statement in sqlglot.parse(query, read="tsql")
            if statement is not None
        ]
    except sqlglot.errors.ParseError as exc:
        raise ValueError(
            "Invalid SQL Server query. Please check the generated SQL."
        ) from exc

    # Allow exactly one statement.
    if len(statements) != 1:
        raise ValueError("Multiple SQL statements are not allowed.")

    statement = statements[0]

    # Only SELECT is allowed at the top level.
    if not isinstance(statement, exp.Select):
        raise ValueError("Only SELECT queries are allowed.")

    # SELECT INTO creates a table.
    if statement.args.get("into") is not None:
        raise ValueError("SELECT INTO is not allowed.")

    # Check nested expressions, CTEs, and subqueries.
    for node in statement.walk():
        node_type = type(node).__name__

        if node_type in FORBIDDEN_NODE_TYPES:
            raise ValueError(
                f"Forbidden SQL operation: {node_type}."
            )

        if node_type == "Into":
            raise ValueError("SELECT INTO is not allowed.")

    # Remove an optional trailing semicolon.
    if query.endswith(";"):
        query = query[:-1].rstrip()

    return query


def execute_sql(sql, user_id):
    """
    Validate and execute a SELECT query using
    the logged-in user's restricted SQL Server account.
    """
    safe_sql = validate_sql(sql)
    connection = None

    try:
        connection = get_user_workspace_connection(user_id)
        connection.timeout = QUERY_TIMEOUT_SECONDS

        cursor = connection.cursor()

        try:
            cursor.execute(safe_sql)

            if cursor.description is None:
                raise ValueError(
                    "The query did not return a result set."
                )

            columns = [
                column[0] for column in cursor.description
            ]

            rows = cursor.fetchmany(MAX_ROWS)

            return {
                "columns": columns,
                "rows": [list(row) for row in rows],
                "row_limit": MAX_ROWS,
            }

        finally:
            cursor.close()

    finally:
        if connection is not None:
            connection.close()
