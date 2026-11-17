
import os

import pyodbc
# Disable pyodbc connection pooling before any connections are opened.
pyodbc.pooling = False

import threading

import secrets
import string

from workspace_service import get_workspace_login
from db import get_connection
from workspace_service import (
    get_workspace_schema,
    quote_identifier,
)

from workspace_credentials import (
    get_cipher,
    update_workspace_status,
)
from auth_db import get_auth_connection

def provision_workspace_schema(user_id):
    """
    Create a private SQL Server schema for a user.

    Administrative operation only.
    Do not expose this function to generated SQL
    or call it with a user-supplied ID.
    """
    schema_name = get_workspace_schema(user_id)
    quoted_schema = quote_identifier(schema_name)

    connection = get_connection()

    try:
        cursor = connection.cursor()

        cursor.execute(
            """
            SELECT SCHEMA_ID(?)
            """,
            schema_name,
        )

        exists = cursor.fetchone()[0] is not None

        if not exists:
            create_sql = (
                f"CREATE SCHEMA {quoted_schema} "
                "AUTHORIZATION [dbo]"
            )

            cursor.execute(create_sql)
            connection.commit()

        return {
            "schema": schema_name,
            "created": not exists,
        }

    except Exception:
        connection.rollback()
        raise

    finally:
        connection.close()




def provision_test_workspace_9001():
    """
    Provision an isolated SQL Server test workspace.

    Administrative operation only.
    Never expose this function through a user
    query or an unauthenticated Flask route.
    """
    user_id = 9001

    schema_name = get_workspace_schema(user_id)
    login_name = get_workspace_login(user_id)

    quoted_schema = quote_identifier(schema_name)
    quoted_login = quote_identifier(login_name)

    password = os.getenv("WORKSPACE_9001_PASSWORD")

    if not password or len(password) < 20:
        raise ValueError(
            "WORKSPACE_9001_PASSWORD must contain "
            "at least 20 characters."
        )

    connection = get_connection()
    cursor = connection.cursor()

    try:
        # CREATE LOGIN is a server-level operation.
        # It must not run inside a user transaction.
        connection.autocommit = True

        cursor.execute(
            "SELECT 1 FROM sys.server_principals WHERE name = ?",
            login_name,
        )

        if cursor.fetchone() is None:
            # The login identifier is validated by
            # quote_identifier(). The password is
            # escaped for the DDL statement.
            escaped_password = password.replace("'", "''")

            cursor.execute(
                f"CREATE LOGIN {quoted_login} "
                f"WITH PASSWORD = '{escaped_password}', "
                "CHECK_POLICY = ON"
            )

        cursor.execute(
            "SELECT 1 FROM sys.database_principals WHERE name = ?",
            login_name,
        )

        if cursor.fetchone() is None:
            cursor.execute(
                f"CREATE USER {quoted_login} "
                f"FOR LOGIN {quoted_login}"
            )

        cursor.execute(
            "SELECT SCHEMA_ID(?)",
            schema_name,
        )

        if cursor.fetchone()[0] is None:
            cursor.execute(
                f"CREATE SCHEMA {quoted_schema} "
                "AUTHORIZATION [dbo]"
            )

        cursor.execute(
            f"ALTER USER {quoted_login} "
            f"WITH DEFAULT_SCHEMA = {quoted_schema}"
        )

        cursor.execute(
            f"GRANT SELECT, INSERT, UPDATE, DELETE "
            f"ON SCHEMA::{quoted_schema} "
            f"TO {quoted_login}"
        )



        return {
            "schema": schema_name,
            "login": login_name,
            "status": "provisioned",
        }

    finally:
        cursor.close()
        connection.close()




def generate_workspace_password(length=32):
    """
    Generate a strong SQL Server login password
    with guaranteed character-category diversity.
    """
    if length < 20:
        raise ValueError(
            "Workspace passwords must contain at least 20 characters."
        )

    groups = [
        string.ascii_uppercase,
        string.ascii_lowercase,
        string.digits,
        "!@#%_-",
    ]

    alphabet = "".join(groups)

    characters = [
        secrets.choice(group)
        for group in groups
    ]

    characters.extend(
        secrets.choice(alphabet)
        for _ in range(length - len(characters))
    )

    # Cryptographically secure shuffle.
    secrets.SystemRandom().shuffle(characters)

    return "".join(characters)




def verify_workspace_login(user_id, password):
    """
    Verify the restricted login and its permissions
    using an actual SQL Server connection.
    """
    schema_name = get_workspace_schema(user_id)
    login_name = get_workspace_login(user_id)

    driver = os.getenv("DB_DRIVER")
    server = os.getenv("DB_SERVER")
    database = os.getenv("DB_NAME")

    if not all((driver, server, database)):
        raise RuntimeError(
            "SQL Server connection settings are missing."
        )

    connection_string = (
        f"DRIVER={{{driver}}};"
        f"SERVER={server};"
        f"DATABASE={database};"
        f"UID={login_name};"
        f"PWD={password};"
        "Encrypt=yes;"
        "TrustServerCertificate=yes;"
        "Connection Timeout=10;"
    )

    connection = pyodbc.connect(connection_string)

    try:
        cursor = connection.cursor()

        cursor.execute(
            """
            SELECT
                ORIGINAL_LOGIN(),
                USER_NAME(),
                IS_MEMBER('db_owner'),
                IS_SRVROLEMEMBER('sysadmin'),
                HAS_PERMS_BY_NAME(
                    ?, 'SCHEMA', 'SELECT'
                ),
                HAS_PERMS_BY_NAME(
                    ?, 'SCHEMA', 'INSERT'
                )
            """,
            (schema_name, schema_name),
        )

        row = cursor.fetchone()

        if (
            row is None
            or row[0] != login_name
            or row[1] != login_name
            or row[2] != 0
            or row[3] != 0
            or row[4] != 1
            or row[5] != 1
        ):
            raise RuntimeError(
                "Workspace login verification failed."
            )

        return True



        # Check permissions against every other workspace schema.
        cursor.execute("""
            SELECT name
            FROM sys.schemas
            WHERE name LIKE 'workspace[_]%'
              AND name <> ?
        """, (schema_name,))

        other_schemas = [row[0] for row in cursor.fetchall()]

        for other_schema in other_schemas:
            cursor.execute(
                """
                SELECT
                    HAS_PERMS_BY_NAME(?, 'SCHEMA', 'SELECT'),
                    HAS_PERMS_BY_NAME(?, 'SCHEMA', 'INSERT'),
                    HAS_PERMS_BY_NAME(?, 'SCHEMA', 'UPDATE'),
                    HAS_PERMS_BY_NAME(?, 'SCHEMA', 'DELETE'),
                    HAS_PERMS_BY_NAME(?, 'SCHEMA', 'ALTER'),
                    HAS_PERMS_BY_NAME(?, 'SCHEMA', 'CONTROL')
                """,
                (other_schema,) * 6,
            )

            permissions = cursor.fetchone()

            if permissions is None or any(
                permission not in (0, None)
                for permission in permissions
            ):
                raise RuntimeError(
                    "Workspace isolation verification failed."
                )



    finally:
        connection.close()




# Prevent simultaneous provisioning within one Python process.
_provisioning_lock = threading.RLock()



def acquire_workspace_provisioning_lock(cursor, user_id):
    """
    Acquire a SQL Server application lock for one workspace.

    The caller must use a transaction and keep it open
    until provisioning is finished.
    """
    resource = f"workspace_provisioning_{int(user_id)}"

    cursor.execute(
        """
        DECLARE @result INT;

        EXEC @result = sys.sp_getapplock
            @Resource = ?,
            @LockMode = 'Exclusive',
            @LockOwner = 'Transaction',
            @LockTimeout = 15000;

        SELECT @result;
        """,
        (resource,),
    )

    result = cursor.fetchone()

    if result is None or result[0] < 0:
        raise RuntimeError(
            "Could not acquire workspace provisioning lock."
        )

    return True





def provision_user_workspace(user_id):
    """
    Provision or recover a private SQL Server workspace.

    Uses a SQL Server session application lock to
    prevent concurrent provisioning across processes.

    Call only from trusted server-side code.
    """
    user_id = int(user_id)

    if user_id <= 0:
        raise ValueError("Invalid user ID.")

    schema_name = get_workspace_schema(user_id)
    login_name = get_workspace_login(user_id)

    quoted_schema = quote_identifier(schema_name)
    quoted_login = quote_identifier(login_name)

    connection = None
    cursor = None
    lock_acquired = False

    try:
        connection = get_connection()
        connection.autocommit = True
        cursor = connection.cursor()

        # Session locks work with autocommit=True.
        # They remain held until explicitly released
        # or the SQL Server session closes.
        lock_name = f"workspace_provisioning_{user_id}"

        cursor.execute(
            """
            DECLARE @result INT;

            EXEC @result = sys.sp_getapplock
                @Resource = ?,
                @LockMode = 'Exclusive',
                @LockOwner = 'Session',
                @LockTimeout = 15000;

            SELECT @result;
            """,
            (lock_name,),
        )

        lock_result = cursor.fetchone()

        if lock_result is None or lock_result[0] < 0:
            raise RuntimeError(
                "Could not acquire workspace provisioning lock."
            )

        lock_acquired = True

        # Check the user exists and is not an admin.
        with get_auth_connection() as auth_connection:
            user = auth_connection.execute(
                """
                SELECT user_id, role
                FROM users
                WHERE user_id = ?
                """,
                (user_id,),
            ).fetchone()

            if user is None or user["role"] != "user":
                raise ValueError(
                    "Workspace provisioning requires a valid user account."
                )

            existing = auth_connection.execute(
                """
                SELECT sql_login, encrypted_password,
                       provisioning_status
                FROM workspace_credentials
                WHERE user_id = ?
                """,
                (user_id,),
            ).fetchone()

            if existing is None:
                password = generate_workspace_password()

                encrypted = get_cipher().encrypt(
                    password.encode("utf-8")
                ).decode("utf-8")

                auth_connection.execute(
                    """
                    INSERT INTO workspace_credentials (
                        user_id,
                        sql_login,
                        encrypted_password,
                        provisioning_status
                    )
                    VALUES (?, ?, ?, 'pending')
                    """,
                    (
                        user_id,
                        login_name,
                        encrypted,
                    ),
                )
            else:
                if existing["sql_login"] != login_name:
                    raise RuntimeError(
                        "Stored workspace login does not match user."
                    )

                password = get_cipher().decrypt(
                    existing["encrypted_password"].encode("utf-8")
                ).decode("utf-8")

        # Existing ready workspaces must still pass verification.
        if (
            existing is not None
            and existing["provisioning_status"] == "ready"
        ):
            verify_workspace_login(user_id, password)

            return {
                "schema": schema_name,
                "login": login_name,
                "status": "ready",
            }

        # Create the SQL Server login if missing.
        cursor.execute(
            """
            SELECT 1
            FROM sys.server_principals
            WHERE name = ?
            """,
            (login_name,),
        )

        login_exists = cursor.fetchone() is not None

        if not login_exists:
            escaped_password = password.replace("'", "''")

            cursor.execute(
                f"CREATE LOGIN {quoted_login} "
                f"WITH PASSWORD = '{escaped_password}', "
                "CHECK_POLICY = ON"
            )

        # Create database user if missing.
        cursor.execute(
            """
            SELECT 1
            FROM sys.database_principals
            WHERE name = ?
            """,
            (login_name,),
        )

        if cursor.fetchone() is None:
            cursor.execute(
                f"CREATE USER {quoted_login} "
                f"FOR LOGIN {quoted_login}"
            )

        # Create private schema if missing.
        cursor.execute(
            "SELECT SCHEMA_ID(?)",
            (schema_name,),
        )

        if cursor.fetchone()[0] is None:
            cursor.execute(
                f"CREATE SCHEMA {quoted_schema} "
                "AUTHORIZATION [dbo]"
            )

        cursor.execute(
            f"ALTER USER {quoted_login} "
            f"WITH DEFAULT_SCHEMA = {quoted_schema}"
        )

        cursor.execute(
            f"GRANT SELECT, INSERT, UPDATE, DELETE "
            f"ON SCHEMA::{quoted_schema} "
            f"TO {quoted_login}"
        )

        # Do not mark ready until the restricted
        # login successfully connects.
        verify_workspace_login(user_id, password)

        update_workspace_status(user_id, "ready")

        return {
            "schema": schema_name,
            "login": login_name,
            "status": "ready",
        }

    except Exception:
        # Only mark failed when credentials exist.
        with get_auth_connection() as auth_connection:
            row = auth_connection.execute(
                """
                SELECT provisioning_status
                FROM workspace_credentials
                WHERE user_id = ?
                """,
                (user_id,),
            ).fetchone()

        if row is not None and row["provisioning_status"] != "ready":
            update_workspace_status(user_id, "failed")

        raise

    finally:
        if cursor is not None and lock_acquired:
            try:
                cursor.execute(
                    """
                    EXEC sys.sp_releaseapplock
                        @Resource = ?,
                        @LockOwner = 'Session';
                    """,
                    (f"workspace_provisioning_{user_id}",),
                )
            except Exception:
                pass

        if cursor is not None:
            try:
                cursor.close()
            except Exception:
                pass

        if connection is not None:
            try:
                connection.close()
            except Exception:
                pass




def grant_workspace_table_creation(user_id):
    raise RuntimeError(
        "Direct workspace table-creation grants are disabled. "
        "Use the controlled server-side table creation service."
    )
    """
    Grant table-creation permissions to an existing,
    ready workspace without changing its credentials.
    """
    from workspace_credentials import get_workspace_credentials

    if not isinstance(user_id, int) or isinstance(user_id, bool) or user_id <= 0:
        raise ValueError("Invalid user ID.")

    # Only ready workspaces can receive these permissions.
    credentials = get_workspace_credentials(user_id)

    expected_login = get_workspace_login(user_id)
    schema_name = get_workspace_schema(user_id)

    if credentials["login"] != expected_login:
        raise RuntimeError("Workspace login mismatch.")

    quoted_login = quote_identifier(expected_login)
    quoted_schema = quote_identifier(schema_name)

    connection = get_connection()

    try:
        cursor = connection.cursor()

        cursor.execute(
            """
            SELECT 1
            FROM sys.database_principals
            WHERE name = ?
            """,
            (expected_login,),
        )

        if cursor.fetchone() is None:
            raise RuntimeError("SQL Server workspace user does not exist.")

        cursor.execute(
            "SELECT SCHEMA_ID(?)",
            (schema_name,),
        )

        if cursor.fetchone()[0] is None:
            raise RuntimeError("Private workspace schema does not exist.")

        cursor.execute(
            f"GRANT CREATE TABLE TO {quoted_login}"
        )

        cursor.execute(
            f"GRANT ALTER ON SCHEMA::{quoted_schema} "
            f"TO {quoted_login}"
        )

        connection.commit()

    except Exception:
        connection.rollback()
        raise

    finally:
        connection.close()

    return {
        "user_id": user_id,
        "schema": schema_name,
        "status": "permissions_updated",
    }
