
import re

import sqlglot
from sqlglot import exp

from db import get_connection


from sql_service import execute_sql, validate_sql


def main():
    query = """
        SELECT EmployeeID, EmployeeName, Salary
        FROM dbo.Employees
        WHERE Salary > 50000
    """

    # Test 1: SQL validation.
    print("Step 1: Testing SQL validation...", flush=True)

    safe_query = validate_sql(query)

    print("Validation passed.", flush=True)
    print("\nValidated SQL:", flush=True)
    print(safe_query, flush=True)

    # Test 2: SQL Server execution.
    print(
        "\nStep 2: Testing SQL Server execution...",
        flush=True,
    )

    result = execute_sql(safe_query)

    # Test 3: Display returned columns and rows.
    print("\nColumns:", result["columns"], flush=True)
    print("\nResults:", flush=True)

    for row in result["rows"]:
        print(row, flush=True)

    print(
        "\nRows returned:",
        len(result["rows"]),
        flush=True,
    )

    print(
        "Configured row limit:",
        result["row_limit"],
        flush=True,
    )

    print(
        "\nSQL service test completed successfully.",
        flush=True,
    )


if __name__ == "__main__":
    main()



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
    Mask comments and quoted text while preserving positions.
    Handles single-quoted strings, double-quoted text,
    bracketed identifiers, and SQL comments.
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
    Allow exactly one read-only SELECT query using T-SQL.
    Raise ValueError when a query is invalid or disallowed.
    """
    if not isinstance(sql, str) or not sql.strip():
        raise ValueError("SQL query cannot be empty.")

    query = sql.strip()

    # Reject risky SQL Server functions outside comments and strings.
    inspected_sql = _mask_comments_and_strings(query)

    risky_pattern = (
        r"\b(?:OPENROWSET|OPENDATASOURCE|OPENQUERY|XP_CMDSHELL)\b"
    )

    if re.search(risky_pattern, inspected_sql, flags=re.IGNORECASE):
        raise ValueError(
            "SQL Server external-access or system functions "
            "are not allowed."
        )

    # Parse using SQL Server T-SQL.
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

    # Exactly one statement is allowed.
    if len(statements) != 1:
        raise ValueError("Multiple SQL statements are not allowed.")

    statement = statements[0]

    # Only SELECT statements are permitted.
    if not isinstance(statement, exp.Select):
        raise ValueError("Only SELECT queries are allowed.")

    # SELECT INTO creates a table and is disallowed.
    if statement.args.get("into") is not None:
        raise ValueError("SELECT INTO is not allowed.")

    # Inspect nested queries, CTEs, and subqueries.
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


def execute_sql(sql):
    """Validate and execute a SQL query against SQL Server."""
    safe_sql = validate_sql(sql)
    connection = None

    try:
        connection = get_connection()
        connection.timeout = QUERY_TIMEOUT_SECONDS

        cursor = connection.cursor()

        try:
            cursor.execute(safe_sql)

            if cursor.description is None:
                raise ValueError(
                    "The query did not return a result set."
                )

            columns = [column[0] for column in cursor.description]
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
