"""PostgreSQL SELECT guard for the Text-to-SQL migration.

Defense in depth only. The database connection MUST use a restricted,
read-only role with no permissions on public or other workspace schemas.
"""
import re
import sqlglot
from sqlglot import exp

BLOCKED = (
    exp.Insert, exp.Update, exp.Delete, exp.Drop, exp.Alter,
    exp.Create, exp.Merge, exp.Command, exp.Grant, exp.Revoke,
    exp.Transaction, exp.Copy,
)

# Functions that can read files, inspect privileged metadata, sleep, or
# otherwise perform unexpected operations must never be generated.
DISALLOWED_FUNCTIONS = {
    'PG_READ_FILE', 'PG_READ_BINARY_FILE', 'PG_LS_DIR',
    'PG_SLEEP', 'DBLINK', 'DBLINK_EXEC', 'LO_IMPORT', 'LO_EXPORT',
    'SET_CONFIG', 'CURRENT_SETTING', 'PG_TERMINATE_BACKEND',
    'PG_CANCEL_BACKEND', 'PG_NOTIFY', 'NEXTVAL', 'SETVAL',
}


def validate_workspace_select(sql: str, schema_name: str) -> str:
    if not isinstance(sql, str) or not sql.strip():
        raise ValueError('SQL query cannot be empty.')
    if not re.fullmatch(r'workspace_[1-9][0-9]*', schema_name):
        raise ValueError('Invalid workspace schema.')
    try:
        statements = [s for s in sqlglot.parse(sql, read='postgres') if s]
    except sqlglot.errors.ParseError as exc:
        raise ValueError('Invalid PostgreSQL SQL.') from exc
    if len(statements) != 1 or not isinstance(statements[0], exp.Select):
        raise ValueError('Only one SELECT statement is allowed.')
    stmt = statements[0]
    for node in stmt.walk():
        if isinstance(node, BLOCKED) or isinstance(node, exp.Into):
            raise ValueError('Data-changing SQL is not allowed.')
        if isinstance(node, exp.Table):
            if node.catalog or not node.db or node.db.lower() != schema_name:
                raise ValueError('Queries must use only fully qualified tables in your workspace.')
        if isinstance(node, exp.Anonymous) and node.name.upper() in DISALLOWED_FUNCTIONS:
            raise ValueError('Function not permitted.')
        if isinstance(node, exp.Func) and node.sql_name().upper() in DISALLOWED_FUNCTIONS:
            raise ValueError('Function not permitted.')
    if stmt.args.get('into') is not None:
        raise ValueError('SELECT INTO is not allowed.')
    # Reject advanced expressions until explicitly reviewed, including CTEs
    # (CTE table references require separate scope-aware validation).
    if stmt.args.get('with_') is not None:
        raise ValueError('CTEs are not supported yet.')
    return sql.strip().removesuffix(';').rstrip()
