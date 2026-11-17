
import os

from cryptography.fernet import Fernet
from dotenv import load_dotenv

from auth_db import get_auth_connection
from workspace_service import get_workspace_login

load_dotenv(dotenv_path=".env")


def get_cipher():
    """Load the workspace encryption key."""
    key = os.getenv("WORKSPACE_CREDENTIAL_KEY")

    if not key:
        raise RuntimeError(
            "WORKSPACE_CREDENTIAL_KEY is missing."
        )

    return Fernet(key.encode())


def save_workspace_credentials(user_id, password):
    """
    Save an encrypted workspace password.

    This function is for trusted server-side
    provisioning code only.
    """
    login_name = get_workspace_login(user_id)

    if not isinstance(password, str) or len(password) < 20:
        raise ValueError("Invalid workspace password.")

    encrypted = get_cipher().encrypt(
        password.encode("utf-8")
    ).decode("utf-8")

    with get_auth_connection() as connection:
        connection.execute(
            """
            INSERT INTO workspace_credentials (
                user_id,
                sql_login,
                encrypted_password,
                provisioning_status
            )
            VALUES (?, ?, ?, 'pending')
            """,
            (user_id, login_name, encrypted),
        )


def get_workspace_credentials(user_id):
    """
    Retrieve credentials for a ready workspace.

    Never expose the returned password to
    templates, browser sessions, or logs.
    """
    login_name = get_workspace_login(user_id)

    with get_auth_connection() as connection:
        row = connection.execute(
            """
            SELECT
                sql_login,
                encrypted_password
            FROM workspace_credentials
            WHERE user_id = ?
              AND provisioning_status = 'ready'
            """,
            (user_id,),
        ).fetchone()

    if row is None:
        raise ValueError(
            "Workspace credentials are not ready."
        )

    if row["sql_login"] != login_name:
        raise ValueError(
            "Workspace login does not match user ID."
        )

    password = get_cipher().decrypt(
        row["encrypted_password"].encode("utf-8")
    ).decode("utf-8")

    return {
        "login": login_name,
        "password": password,
    }




def update_workspace_status(user_id, status):
    """
    Update the provisioning status of a user's
    private SQL Server workspace.
    """
    allowed_statuses = {"pending", "ready", "failed"}

    if status not in allowed_statuses:
        raise ValueError(
            "Invalid workspace provisioning status."
        )

    # Validate the user ID before accessing the database.
    get_workspace_login(user_id)

    with get_auth_connection() as connection:
        cursor = connection.execute(
            """
            UPDATE workspace_credentials
            SET provisioning_status = ?
            WHERE user_id = ?
            """,
            (status, user_id),
        )

        if cursor.rowcount != 1:
            raise ValueError(
                "Workspace credential record not found."
            )
