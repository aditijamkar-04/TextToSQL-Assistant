
import os
import sqlite3
import time
import math
from pathlib import Path

from werkzeug.security import (
    generate_password_hash,
    check_password_hash,
)


# --------------------------------------------------
# DATABASE CONFIGURATION
# --------------------------------------------------

BASE_DIR = Path(__file__).resolve().parent

AUTH_DB_PATH = Path(
    os.getenv(
        "AUTH_DB_PATH",
        str(BASE_DIR / "instance" / "auth.db"),
    )
).resolve()

VALID_ROLES = {"admin", "user"}


# --------------------------------------------------
# LOGIN RATE-LIMIT CONFIGURATION
# --------------------------------------------------

MAX_LOGIN_ATTEMPTS = 5
LOGIN_WINDOW_SECONDS = 60
LOGIN_LOCKOUT_SECONDS = 60


# --------------------------------------------------
# DATABASE CONNECTION
# --------------------------------------------------

def get_auth_connection():
    AUTH_DB_PATH.parent.mkdir(
        parents=True,
        exist_ok=True,
    )

    connection = sqlite3.connect(
        str(AUTH_DB_PATH),
        timeout=10,
    )

    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA foreign_keys = ON")

    return connection


# --------------------------------------------------
# DATABASE INITIALIZATION
# --------------------------------------------------


def init_auth_db():
    with get_auth_connection() as connection:

        connection.execute("""
            CREATE TABLE IF NOT EXISTS users (
                user_id INTEGER PRIMARY KEY AUTOINCREMENT,
                username TEXT NOT NULL COLLATE NOCASE UNIQUE,
                password_hash TEXT NOT NULL,
                role TEXT NOT NULL
                    CHECK (role IN ('admin', 'user')),
                is_active INTEGER NOT NULL DEFAULT 1
                    CHECK (is_active IN (0, 1)),
                created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
            )
        """)

        connection.execute("""
            CREATE TABLE IF NOT EXISTS query_history (
                query_id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER NOT NULL,
                question TEXT NOT NULL,
                generated_sql TEXT,
                status TEXT NOT NULL,
                created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (user_id)
                    REFERENCES users(user_id)
                    ON DELETE CASCADE
            )
        """)

        connection.execute("""
            CREATE TABLE IF NOT EXISTS login_rate_limits (
                scope TEXT NOT NULL,
                identifier TEXT NOT NULL,
                attempts INTEGER NOT NULL DEFAULT 0,
                window_started REAL NOT NULL,
                locked_until REAL NOT NULL DEFAULT 0,
                PRIMARY KEY (scope, identifier)
            )
        """)



        # --------------------------------------------------
        # PRIVATE WORKSPACE CREDENTIALS
        # --------------------------------------------------

        connection.execute("""
            CREATE TABLE IF NOT EXISTS workspace_credentials (
                user_id INTEGER PRIMARY KEY,
                sql_login TEXT NOT NULL UNIQUE,
                encrypted_password TEXT NOT NULL,
                provisioning_status TEXT NOT NULL
                    DEFAULT 'pending'
                    CHECK (
                        provisioning_status IN (
                            'pending',
                            'ready',
                            'failed'
                        )
                    ),
                created_at TEXT NOT NULL
                    DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (user_id)
                    REFERENCES users(user_id)
                    ON DELETE CASCADE
            )
        """)



        connection.execute("""
            CREATE TABLE IF NOT EXISTS feedback (
                feedback_id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER NOT NULL,
                category TEXT NOT NULL,
                message TEXT NOT NULL,
                created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (user_id)
                    REFERENCES users(user_id)
                    ON DELETE CASCADE
            )
        """)


        connection.execute("""
            CREATE TABLE IF NOT EXISTS feedback_messages (
                message_id INTEGER PRIMARY KEY AUTOINCREMENT,
                feedback_id INTEGER NOT NULL,
                sender_id INTEGER NOT NULL,
                sender_role TEXT NOT NULL
                    CHECK (sender_role IN ('admin', 'user')),
                message TEXT NOT NULL,
                created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (feedback_id)
                    REFERENCES feedback(feedback_id)
                    ON DELETE CASCADE,
                FOREIGN KEY (sender_id)
                    REFERENCES users(user_id)
                    ON DELETE CASCADE
            )
        """)

        connection.execute("""
            CREATE INDEX IF NOT EXISTS idx_feedback_messages_thread
            ON feedback_messages(feedback_id, created_at, message_id)
        """)


        # Safely migrate existing databases without recreating tables.
        user_columns = {
            row["name"]
            for row in connection.execute(
                "PRAGMA table_info(users)"
            ).fetchall()
        }

        if "email" not in user_columns:
            connection.execute(
                "ALTER TABLE users ADD COLUMN email TEXT"
            )

        feedback_columns = {
            row["name"]
            for row in connection.execute(
                "PRAGMA table_info(feedback)"
            ).fetchall()
        }

        if "admin_reply" not in feedback_columns:
            connection.execute(
                "ALTER TABLE feedback ADD COLUMN admin_reply TEXT"
            )

        if "replied_at" not in feedback_columns:
            connection.execute(
                "ALTER TABLE feedback ADD COLUMN replied_at TEXT"
            )

        # Allow only one account per non-empty email address.
        connection.execute("""
            CREATE UNIQUE INDEX IF NOT EXISTS
                idx_users_email_unique
            ON users(email COLLATE NOCASE)
            WHERE email IS NOT NULL AND email != ''
        """)



# --------------------------------------------------
# CREATE USER
# --------------------------------------------------


def create_user(username, password, role="user", email=None):
    if not isinstance(username, str):
        raise ValueError("Invalid username.")

    if not isinstance(password, str):
        raise ValueError("Invalid password.")

    username = username.strip()

    if not 3 <= len(username) <= 50:
        raise ValueError(
            "Username must be between 3 and 50 characters."
        )

    if len(password) < 12:
        raise ValueError(
            "Password must contain at least 12 characters."
        )

    if role not in VALID_ROLES:
        raise ValueError("Invalid role.")

    if email is not None:
        if not isinstance(email, str):
            raise ValueError("Invalid email address.")

        email = email.strip().lower()

        if not email:
            email = None
        elif (
            len(email) > 254
            or "@" not in email
            or email.startswith("@")
            or email.endswith("@")
            or any(char.isspace() for char in email)
        ):
            raise ValueError("Please enter a valid email address.")

    password_hash = generate_password_hash(password)

    try:
        with get_auth_connection() as connection:
            cursor = connection.execute(
                """
                INSERT INTO users (
                    username,
                    password_hash,
                    role,
                    email
                )
                VALUES (?, ?, ?, ?)
                """,
                (
                    username,
                    password_hash,
                    role,
                    email,
                ),
            )

            return cursor.lastrowid

    except sqlite3.IntegrityError as exc:
        error_message = str(exc).lower()

        if "email" in error_message:
            raise ValueError(
                "That email address is already registered."
            ) from exc

        raise ValueError(
            "That username already exists."
        ) from exc



# --------------------------------------------------
# RATE-LIMIT IDENTIFIERS
# --------------------------------------------------

def _login_identifiers(username, ip_address=None):
    """
    Return normalized username and IP identifiers.
    Empty usernames are not stored as username identifiers.
    """
    identifiers = []

    normalized_username = (
        username.strip().casefold()
        if isinstance(username, str)
        else ""
    )

    if normalized_username:
        identifiers.append(
            ("username", normalized_username)
        )

    if ip_address:
        identifiers.append(
            ("ip", str(ip_address).strip())
        )

    return identifiers


# --------------------------------------------------
# CHECK ACTIVE LOGIN LOCKOUT
# --------------------------------------------------

def get_login_lockout(username, ip_address=None):
    """
    Return remaining lockout time in seconds.
    Return 0 if no active lockout exists.
    """
    now = time.time()
    remaining = 0

    with get_auth_connection() as connection:
        # Serialize cleanup and reads to avoid racing with updates.
        connection.execute("BEGIN IMMEDIATE")

        for scope, identifier in _login_identifiers(
            username,
            ip_address,
        ):
            row = connection.execute(
                """
                SELECT attempts, window_started, locked_until
                FROM login_rate_limits
                WHERE scope = ? AND identifier = ?
                """,
                (
                    scope,
                    identifier,
                ),
            ).fetchone()

            if row is None:
                continue

            if row["locked_until"] > now:
                remaining = max(
                    remaining,
                    math.ceil(
                        row["locked_until"] - now
                    ),
                )
                continue

            # Remove expired windows and their old lockout records.
            if (
                now - row["window_started"]
                >= LOGIN_WINDOW_SECONDS
            ):
                connection.execute(
                    """
                    DELETE FROM login_rate_limits
                    WHERE scope = ? AND identifier = ?
                    """,
                    (
                        scope,
                        identifier,
                    ),
                )

    return remaining


# --------------------------------------------------
# RECORD FAILED LOGIN
# --------------------------------------------------

def record_failed_login(username, ip_address=None):
    """
    Record a failed login against the username and IP.

    Returns the remaining lockout duration in seconds.
    Returns 0 when the attempt has not reached the lockout threshold.
    """
    now = time.time()
    remaining = 0

    with get_auth_connection() as connection:
        # Protect concurrent updates using a SQLite write transaction.
        connection.execute("BEGIN IMMEDIATE")

        for scope, identifier in _login_identifiers(
            username,
            ip_address,
        ):
            row = connection.execute(
                """
                SELECT attempts, window_started, locked_until
                FROM login_rate_limits
                WHERE scope = ? AND identifier = ?
                """,
                (
                    scope,
                    identifier,
                ),
            ).fetchone()

            # Existing lockouts cannot be shortened by another failure.
            if row and row["locked_until"] > now:
                remaining = max(
                    remaining,
                    math.ceil(
                        row["locked_until"] - now
                    ),
                )
                continue

            # Start a new window when no record exists or the old
            # attempt window has expired.
            if (
                row is None
                or now - row["window_started"]
                >= LOGIN_WINDOW_SECONDS
            ):
                attempts = 1
                window_started = now
            else:
                attempts = row["attempts"] + 1
                window_started = row["window_started"]

            locked_until = (
                now + LOGIN_LOCKOUT_SECONDS
                if attempts >= MAX_LOGIN_ATTEMPTS
                else 0
            )

            connection.execute(
                """
                INSERT INTO login_rate_limits (
                    scope,
                    identifier,
                    attempts,
                    window_started,
                    locked_until
                )
                VALUES (?, ?, ?, ?, ?)
                ON CONFLICT(scope, identifier) DO UPDATE SET
                    attempts = excluded.attempts,
                    window_started = excluded.window_started,
                    locked_until = excluded.locked_until
                """,
                (
                    scope,
                    identifier,
                    attempts,
                    window_started,
                    locked_until,
                ),
            )

            if locked_until > now:
                remaining = max(
                    remaining,
                    math.ceil(
                        locked_until - now
                    ),
                )

    return remaining


# --------------------------------------------------
# CLEAR USERNAME ATTEMPTS AFTER SUCCESS
# --------------------------------------------------

def clear_login_attempts(username):
    """
    Clear username-specific failed attempts after successful login.

    The IP-based counter is intentionally retained until its
    window expires, helping prevent repeated attacks from one IP.
    """
    if not isinstance(username, str):
        return

    normalized_username = username.strip().casefold()

    if not normalized_username:
        return

    with get_auth_connection() as connection:
        connection.execute(
            """
            DELETE FROM login_rate_limits
            WHERE scope = 'username'
              AND identifier = ?
            """,
            (normalized_username,),
        )


# --------------------------------------------------
# AUTHENTICATE USER
# --------------------------------------------------

def authenticate_user(username, password):
    if not isinstance(username, str):
        return None

    if not isinstance(password, str):
        return None

    with get_auth_connection() as connection:
        user = connection.execute(
            """
            SELECT
                user_id,
                username,
                password_hash,
                role,
                is_active
            FROM users
            WHERE username = ?
            """,
            (username.strip(),),
        ).fetchone()

    if user is None or not user["is_active"]:
        return None

    if not check_password_hash(
        user["password_hash"],
        password,
    ):
        return None

    return {
        "user_id": user["user_id"],
        "username": user["username"],
        "role": user["role"],
    }


# --------------------------------------------------
# LIST USERS
# --------------------------------------------------

def list_users():
    with get_auth_connection() as connection:
        rows = connection.execute("""
            SELECT
                user_id,
                username,
                role,
                is_active,
                created_at
            FROM users
            ORDER BY user_id
        """).fetchall()

    return [
        dict(row)
        for row in rows
    ]


# --------------------------------------------------
# ACTIVATE OR DEACTIVATE USER
# --------------------------------------------------

def set_user_active(user_id, is_active):
    with get_auth_connection() as connection:
        cursor = connection.execute(
            """
            UPDATE users
            SET is_active = ?
            WHERE user_id = ?
            """,
            (
                int(bool(is_active)),
                user_id,
            ),
        )

        return cursor.rowcount > 0


# --------------------------------------------------
# CHANGE USER ROLE
# --------------------------------------------------

def set_user_role(user_id, role):
    if role not in VALID_ROLES:
        raise ValueError("Invalid role.")

    with get_auth_connection() as connection:
        cursor = connection.execute(
            """
            UPDATE users
            SET role = ?
            WHERE user_id = ?
            """,
            (
                role,
                user_id,
            ),
        )

        return cursor.rowcount > 0


# --------------------------------------------------
# RECORD QUERY HISTORY
# --------------------------------------------------

def record_query(
    user_id,
    question,
    generated_sql,
    status,
):
    with get_auth_connection() as connection:
        cursor = connection.execute(
            """
            INSERT INTO query_history (
                user_id,
                question,
                generated_sql,
                status
            )
            VALUES (?, ?, ?, ?)
            """,
            (
                user_id,
                question,
                generated_sql,
                status,
            ),
        )

        return cursor.lastrowid


# --------------------------------------------------
# GET QUERY HISTORY
# --------------------------------------------------

def get_query_history(user_id=None, limit=10):
    limit = max(
        1,
        min(int(limit), 100),
    )

    with get_auth_connection() as connection:
        if user_id is None:
            rows = connection.execute(
                """
                SELECT
                    q.query_id,
                    q.user_id,
                    u.username,
                    q.question,
                    q.generated_sql,
                    q.status,
                    q.created_at
                FROM query_history AS q
                JOIN users AS u
                    ON u.user_id = q.user_id
                ORDER BY q.query_id DESC
                LIMIT ?
                """,
                (limit,),
            ).fetchall()

        else:
            rows = connection.execute(
                """
                SELECT
                    query_id,
                    user_id,
                    question,
                    generated_sql,
                    status,
                    created_at
                FROM query_history
                WHERE user_id = ?
                ORDER BY query_id DESC
                LIMIT ?
                """,
                (
                    user_id,
                    limit,
                ),
            ).fetchall()

    return [
        dict(row)
        for row in rows
    ]


# --------------------------------------------------
# INITIALIZE DATABASE WHEN RUN DIRECTLY
# --------------------------------------------------

if __name__ == "__main__":
    init_auth_db()

    print("Authentication database initialized.")
    print(f"Location: {AUTH_DB_PATH}")
    print(
        f"Maximum failed attempts: {MAX_LOGIN_ATTEMPTS}"
    )
    print(
        f"Attempt window: {LOGIN_WINDOW_SECONDS} seconds"
    )
    print(
        f"Lockout duration: {LOGIN_LOCKOUT_SECONDS} seconds"
    )




def record_feedback(user_id, category, message):
    with get_auth_connection() as connection:
        cursor = connection.execute(
            """
            INSERT INTO feedback (user_id, category, message)
            VALUES (?, ?, ?)
            """,
            (user_id, category, message),
        )

        return cursor.lastrowid


def get_all_feedback():
    with get_auth_connection() as connection:
        rows = connection.execute(
            """
            SELECT
                f.feedback_id,
                f.user_id,
                u.username,
                u.email,
                f.category,
                f.message,
                f.created_at,
                f.admin_reply,
                f.replied_at
            FROM feedback AS f
            JOIN users AS u ON u.user_id = f.user_id
            ORDER BY f.created_at DESC, f.feedback_id DESC
            """
        ).fetchall()

        return [dict(row) for row in rows]


def get_user_feedback(user_id):
    with get_auth_connection() as connection:
        rows = connection.execute(
            """
            SELECT
                feedback_id,
                category,
                message,
                created_at,
                admin_reply,
                replied_at
            FROM feedback
            WHERE user_id = ?
            ORDER BY created_at DESC, feedback_id DESC
            """,
            (user_id,),
        ).fetchall()

        return [dict(row) for row in rows]


def save_admin_feedback_reply(feedback_id, admin_reply):
    with get_auth_connection() as connection:
        cursor = connection.execute(
            """
            UPDATE feedback
            SET admin_reply = ?, replied_at = CURRENT_TIMESTAMP
            WHERE feedback_id = ?
            """,
            (admin_reply, feedback_id),
        )

        return cursor.rowcount > 0



def add_feedback_message(feedback_id, sender_id, sender_role, message):
    """Save one message in a feedback conversation."""
    if sender_role not in {"admin", "user"}:
        raise ValueError("Invalid sender role.")

    with get_auth_connection() as connection:
        feedback_exists = connection.execute(
            "SELECT 1 FROM feedback WHERE feedback_id = ?",
            (feedback_id,),
        ).fetchone()

        if not feedback_exists:
            return False

        cursor = connection.execute(
            """
            INSERT INTO feedback_messages
                (feedback_id, sender_id, sender_role, message)
            VALUES (?, ?, ?, ?)
            """,
            (feedback_id, sender_id, sender_role, message),
        )

        return cursor.lastrowid


def get_feedback_messages(feedback_id):
    """Return all messages in one conversation, oldest first."""
    with get_auth_connection() as connection:
        rows = connection.execute(
            """
            SELECT
                fm.message_id,
                fm.feedback_id,
                fm.sender_id,
                fm.sender_role,
                fm.message,
                fm.created_at,
                u.username
            FROM feedback_messages AS fm
            JOIN users AS u ON u.user_id = fm.sender_id
            WHERE fm.feedback_id = ?
            ORDER BY fm.created_at ASC, fm.message_id ASC
            """,
            (feedback_id,),
        ).fetchall()

        return [dict(row) for row in rows]


def get_feedback_owner(feedback_id):
    """Return the user who owns a feedback conversation."""
    with get_auth_connection() as connection:
        row = connection.execute(
            """
            SELECT feedback_id, user_id, category, message, created_at
            FROM feedback
            WHERE feedback_id = ?
            """,
            (feedback_id,),
        ).fetchone()

        return dict(row) if row else None



def verify_workspace_user(user_id):
    """
    Verify that a workspace belongs to an existing,
    active, ordinary user account.
    """
    if (
        not isinstance(user_id, int)
        or isinstance(user_id, bool)
        or user_id <= 0
    ):
        raise ValueError("Invalid user ID.")

    with get_auth_connection() as connection:
        user = connection.execute(
            """
            SELECT user_id, role, is_active
            FROM users
            WHERE user_id = ?
            """,
            (user_id,),
        ).fetchone()

    if user is None:
        raise PermissionError("User account does not exist.")

    if user["role"] != "user":
        raise PermissionError("Only ordinary users can access workspaces.")

    if not user["is_active"]:
        raise PermissionError("User account is inactive.")

    return True
