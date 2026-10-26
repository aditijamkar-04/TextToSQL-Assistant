
import re


WORKSPACE_PREFIX = "workspace_"


def get_workspace_schema(user_id):
    """
    Return a deterministic private schema name
    for an authenticated user ID.
    """
    if isinstance(user_id, bool):
        raise ValueError("Invalid user ID.")

    try:
        user_id = int(user_id)
    except (TypeError, ValueError):
        raise ValueError("Invalid user ID.")

    if user_id <= 0:
        raise ValueError("Invalid user ID.")

    return f"{WORKSPACE_PREFIX}{user_id}"


def quote_identifier(identifier):
    """
    Safely quote a SQL Server identifier.
    """
    if not isinstance(identifier, str):
        raise ValueError("Invalid SQL identifier.")

    if not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", identifier):
        raise ValueError("Invalid SQL identifier.")

    return f"[{identifier}]"




def get_workspace_login(user_id):
    """
    Return a deterministic SQL Server login name
    for an authenticated application user.
    """
    schema = get_workspace_schema(user_id)

    return schema.replace(
        "workspace_",
        "workspace_login_",
        1,
    )
