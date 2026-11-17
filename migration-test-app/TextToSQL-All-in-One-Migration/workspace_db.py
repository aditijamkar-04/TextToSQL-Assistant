
import os

import pyodbc
from dotenv import load_dotenv

from workspace_service import get_workspace_login

load_dotenv(dotenv_path=".env")



def get_user_workspace_connection(user_id):
    """
    Connect to a user's private SQL Server workspace
    using credentials stored in the authentication database.
    """
    import os
    import pyodbc

    from workspace_credentials import get_workspace_credentials
    from workspace_service import get_workspace_login

    user_id = int(user_id)

    if user_id <= 0:
        raise ValueError("Invalid user ID.")

    credentials = get_workspace_credentials(user_id)

    if credentials is None:
        raise RuntimeError(
            "Workspace is not provisioned or is not ready."
        )

    expected_login = get_workspace_login(user_id)

    if credentials["login"] != expected_login:
        raise RuntimeError(
            "Workspace login does not match the user."
        )

    server = os.getenv("DB_SERVER")
    database = os.getenv("DB_NAME")
    driver = os.getenv("DB_DRIVER")

    if not all((server, database, driver)):
        raise RuntimeError(
            "SQL Server connection configuration is missing."
        )

    connection_string = (
        f"DRIVER={{{driver}}};"
        f"SERVER={server};"
        f"DATABASE={database};"
        f"UID={credentials['login']};"
        f"PWD={credentials['password']};"
        "Encrypt=yes;"
        "TrustServerCertificate=yes;"
        "Connection Timeout=10;"
    )

    return pyodbc.connect(connection_string)
