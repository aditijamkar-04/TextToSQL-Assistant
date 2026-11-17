
from workspace_service import (
    get_workspace_schema,
    quote_identifier,
)


def get_user_workspace(user_id):
    """
    Return workspace metadata for an authenticated
    application user.

    This function does not create schemas or
    grant SQL Server permissions.
    """
    schema = get_workspace_schema(user_id)

    return {
        "schema": schema,
        "quoted_schema": quote_identifier(schema),
    }
