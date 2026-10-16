
import os
import sqlite3
from functools import wraps
from pathlib import Path

import requests
from dotenv import load_dotenv
from flask import (
    Flask,
    abort,
    flash,
    redirect,
    render_template,
    request,
    session,
    url_for,
)
from flask_wtf.csrf import CSRFProtect

from auth_db import (
    init_auth_db,
    create_user,
    authenticate_user,
    list_users,
    set_user_active,
    get_query_history,
    record_query,
    get_login_lockout,
    record_failed_login,
    clear_login_attempts,
)
from text_to_sql import ask_database


# --------------------------------------------------
# APPLICATION CONFIGURATION
# --------------------------------------------------

BASE_DIR = Path(__file__).resolve().parent
load_dotenv(BASE_DIR / ".env")

secret_key = os.getenv("FLASK_SECRET_KEY")

if not secret_key:
    raise RuntimeError(
        "FLASK_SECRET_KEY is missing from your .env file."
    )

app = Flask(__name__)

app.config.update(
    SECRET_KEY=secret_key,
    SESSION_COOKIE_HTTPONLY=True,
    SESSION_COOKIE_SAMESITE="Lax",
    # Set FLASK_HTTPS=1 only when HTTPS is configured.
    SESSION_COOKIE_SECURE=os.getenv("FLASK_HTTPS", "0") == "1",
    PERMANENT_SESSION_LIFETIME=1800,
    MAX_CONTENT_LENGTH=16 * 1024,
)

# Protect POST requests against CSRF.
CSRFProtect(app)

# Initialize authentication tables, including login rate limits.
init_auth_db()


# --------------------------------------------------
# AUTHENTICATION AND AUTHORIZATION
# --------------------------------------------------

def login_required(view):
    @wraps(view)
    def wrapped_view(*args, **kwargs):
        if not session.get("user_id"):
            flash(
                "Please sign in to continue.",
                "warning",
            )
            return redirect(url_for("signin"))

        return view(*args, **kwargs)

    return wrapped_view


def role_required(required_role):
    def decorator(view):
        @wraps(view)
        @login_required
        def wrapped_view(*args, **kwargs):
            if session.get("role") != required_role:
                abort(403)

            return view(*args, **kwargs)

        return wrapped_view

    return decorator


# --------------------------------------------------
# WELCOME PAGE
# --------------------------------------------------

@app.route("/")
def welcome():
    if session.get("user_id"):
        if session.get("role") == "admin":
            return redirect(url_for("admin_dashboard"))

        return redirect(url_for("user_home"))

    return render_template("welcome.html")


# --------------------------------------------------
# USER REGISTRATION
# --------------------------------------------------

@app.route("/register", methods=["GET", "POST"])
def register():
    if session.get("user_id"):
        if session.get("role") == "admin":
            return redirect(url_for("admin_dashboard"))

        return redirect(url_for("user_home"))

    if request.method == "POST":
        username = request.form.get("username", "").strip()
        password = request.form.get("password", "")
        confirm = request.form.get("confirm_password", "")

        if password != confirm:
            flash(
                "Passwords do not match.",
                "error",
            )
        else:
            try:
                # Public registration can create ordinary users only.
                create_user(
                    username,
                    password,
                    role="user",
                )

                flash(
                    "Registration successful. Please sign in.",
                    "success",
                )
                return redirect(url_for("signin"))

            except ValueError as exc:
                flash(str(exc), "error")

    return render_template("register.html")


# --------------------------------------------------
# SIGN-IN WITH RATE LIMITING
# --------------------------------------------------

@app.route("/signin", methods=["GET", "POST"])
def signin():
    if session.get("user_id"):
        if session.get("role") == "admin":
            return redirect(url_for("admin_dashboard"))

        return redirect(url_for("user_home"))

    if request.method == "POST":
        username = request.form.get("username", "").strip()
        password = request.form.get("password", "")

        # Use the direct client address Flask sees.
        # Do not trust forwarded headers unless a trusted
        # reverse proxy is explicitly configured.
        ip_address = request.remote_addr or "unknown"

        # Check the username and IP lockout before password verification.
        try:
            remaining = get_login_lockout(
                username,
                ip_address,
            )
        except sqlite3.Error:
            app.logger.exception(
                "Unable to check login rate limits."
            )
            flash(
                "Sign-in is temporarily unavailable. Please try again.",
                "error",
            )
            return render_template("signin.html"), 503

        if remaining > 0:

            return render_template("signin.html",remaining_seconds=remaining,), 429

        # Verify credentials.
        try:
            user = authenticate_user(
                username,
                password,
            )
        except Exception:
            app.logger.exception(
                "Authentication failed unexpectedly."
            )
            flash(
                "Sign-in is temporarily unavailable. Please try again.",
                "error",
            )
            return render_template("signin.html"), 503

        if user:
            # Clear the username-based counter after successful login.
            try:
                clear_login_attempts(username)
            except sqlite3.Error:
                app.logger.exception(
                    "Unable to clear login attempt counter."
                )
                flash(
                    "Sign-in is temporarily unavailable. Please try again.",
                    "error",
                )
                return render_template("signin.html"), 503

            # Clear previous session data before setting the identity.
            session.clear()
            session.permanent = True
            session["user_id"] = user["user_id"]
            session["username"] = user["username"]
            session["role"] = user["role"]

            flash(
                "Signed in successfully.",
                "success",
            )

            if user["role"] == "admin":
                return redirect(url_for("admin_dashboard"))

            return redirect(url_for("user_home"))

        # Record incorrect passwords, unknown usernames, and inactive accounts.
        try:
            remaining = record_failed_login(
                username,
                ip_address,
            )
        except sqlite3.Error:
            app.logger.exception(
                "Unable to record failed login attempt."
            )
            flash(
                "Sign-in is temporarily unavailable. Please try again.",
                "error",
            )
            return render_template("signin.html"), 503

        if remaining > 0:

            return render_template("signin.html", remaining_seconds=remaining,), 429

        flash(
            "Invalid username or password.",
            "error",
        )

    return render_template("signin.html")


# --------------------------------------------------
# LOGOUT
# --------------------------------------------------

@app.route("/logout", methods=["POST"])
def logout():
    session.clear()
    flash(
        "You have signed out.",
        "success",
    )
    return redirect(url_for("welcome"))


# --------------------------------------------------
# USER HOME
# --------------------------------------------------

@app.route("/user")
@role_required("user")
def user_home():
    history = get_query_history(
        session["user_id"],
        limit=10,
    )

    return render_template(
        "user_home.html",
        question="",
        result=None,
        error=None,
        history=history,
    )


# --------------------------------------------------
# USER DASHBOARD
# --------------------------------------------------

@app.route("/user/dashboard")
@role_required("user")
def user_dashboard():
    history = get_query_history(
        session["user_id"],
        limit=10,
    )

    return render_template(
        "user_dashboard.html",
        history=history,
    )


# --------------------------------------------------
# TEXT-TO-SQL QUERY
# --------------------------------------------------

@app.route("/ask", methods=["POST"])
@role_required("user")
def ask():
    question = request.form.get(
        "question",
        "",
    ).strip()

    if not question:
        flash(
            "Please enter a question.",
            "error",
        )
        return redirect(url_for("user_home"))

    if len(question) > 2000:
        flash(
            "Please keep your question under 2,000 characters.",
            "error",
        )
        return redirect(url_for("user_home"))

    result = None
    error = None
    status = "failed"
    generated_sql = None

    try:
        result = ask_database(question)

        if result.get("status") == "clarification_needed":
            error = result.get(
                "message",
                "Please clarify your question.",
            )
            result = None
        else:
            status = "completed"
            generated_sql = result.get("sql")

    except (ValueError, requests.RequestException):
        app.logger.exception(
            "Text-to-SQL request failed."
        )
        error = (
            "Unable to process the question. "
            "Check the server logs."
        )

    except Exception:
        app.logger.exception(
            "Unexpected Text-to-SQL error."
        )
        error = (
            "An unexpected error occurred. "
            "Check the server logs."
        )

    # Preserve query history even if query execution fails.
    try:
        record_query(
            session["user_id"],
            question,
            generated_sql,
            status,
        )
    except Exception:
        app.logger.exception(
            "Unable to save query history."
        )

    history = get_query_history(
        session["user_id"],
        limit=10,
    )

    return render_template(
        "user_home.html",
        question=question,
        result=result,
        error=error,
        history=history,
    )


# --------------------------------------------------
# DATA SOURCES
# --------------------------------------------------

@app.route("/data-sources")
@role_required("user")
def data_sources():
    # Connect this page to the actual database connection
    # after confirming the connection function in db.py.
    return render_template("data_sources.html")


# --------------------------------------------------
# ADMIN DASHBOARD
# --------------------------------------------------

@app.route("/admin")
@role_required("admin")
def admin_dashboard():
    users = list_users()
    history = get_query_history(limit=10)

    return render_template(
        "admin_dashboard.html",
        users=users,
        history=history,
        user_count=len(users),
        active_count=sum(
            user["is_active"] for user in users
        ),
    )


# --------------------------------------------------
# ADMIN USER MANAGEMENT
# --------------------------------------------------

@app.route("/admin/users")
@role_required("admin")
def admin_users():
    return render_template(
        "manage_users.html",
        users=list_users(),
    )


@app.route(
    "/admin/users/<int:user_id>/status",
    methods=["POST"],
)
@role_required("admin")
def admin_user_status(user_id):
    if user_id == session.get("user_id"):
        flash(
            "You cannot deactivate your own account.",
            "error",
        )
        return redirect(url_for("admin_users"))

    active = request.form.get("active") == "1"

    try:
        if not set_user_active(user_id, active):
            flash(
                "User account was not found.",
                "error",
            )
        else:
            flash(
                "User status updated.",
                "success",
            )

    except sqlite3.Error:
        app.logger.exception(
            "Unable to update user status."
        )
        flash(
            "Could not update the user account.",
            "error",
        )

    return redirect(url_for("admin_users"))


# --------------------------------------------------
# ERROR HANDLERS
# --------------------------------------------------

@app.errorhandler(403)
def forbidden(_error):
    return (
        render_template(
            "error.html",
            code=403,
            message=(
                "You do not have permission "
                "to access this page."
            ),
        ),
        403,
    )


@app.errorhandler(404)
def not_found(_error):
    return (
        render_template(
            "error.html",
            code=404,
            message="The requested page was not found.",
        ),
        404,
    )


# --------------------------------------------------
# RUN APPLICATION
# --------------------------------------------------



# --------------------------------------------------
# RUN APPLICATION
# --------------------------------------------------

if __name__ == "__main__":
    import os

    debug_mode = os.getenv("FLASK_DEBUG", "0").strip() == "1"

    app.run(
        host="127.0.0.1",
        port=int(os.getenv("PORT", "5000")),
        debug=debug_mode,
    )
