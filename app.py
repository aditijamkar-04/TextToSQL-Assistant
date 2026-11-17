
import os
import sqlite3
from functools import wraps
from pathlib import Path

from workspace_tables import (
    create_workspace_table,
    add_workspace_column,
    list_workspace_tables,
    insert_workspace_record,
    view_workspace_records,
    modify_workspace_record,
    get_workspace_record_keys,
    delete_workspace_column,
    rename_workspace_column,
    modify_workspace_column,
    rename_workspace_table,
    delete_workspace_table,
)

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

BASE_DIR = Path(__file__).resolve().parent
load_dotenv(BASE_DIR / ".env")

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
    record_feedback,
    get_all_feedback,
    get_user_feedback,
    save_admin_feedback_reply,
    add_feedback_message,
    get_feedback_messages,
    get_feedback_owner,
)
from text_to_sql import ask_database, explain_sql

from workspace_provisioning import provision_user_workspace

from workspace_credentials import get_workspace_credentials

# --------------------------------------------------
# APPLICATION CONFIGURATION
# --------------------------------------------------



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
        email = request.form.get("email", "").strip() or None
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
                user_id = create_user(
                    username,
                    password,
                    role="user",
                    email=email,
                )

                # Create a private SQL Server workspace
                # for the newly registered user.
                try:
                    if os.getenv("DEMO_MODE", "0").strip() != "1":
                        provision_user_workspace(user_id)

                except Exception:
                    app.logger.exception(
                        "Workspace provisioning failed for user ID %s",
                        user_id,
                    )

                    flash(
                        "Your account was created, but your "
                        "database workspace is not ready yet. "
                        "Please contact the administrator.",
                        "error",
                    )

                    return redirect(url_for("signin"))

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
            # Only ordinary users require a private SQL workspace.
            if (
                user["role"] == "user"
                and os.getenv("DEMO_MODE", "0").strip() != "1"
            ):
                try:
                    workspace = get_workspace_credentials(
                        user["user_id"]
                    )

                    app.logger.warning(
                        "DEBUG SIGN-IN: user_id=%s, username=%s, role=%s",
                        user["user_id"],
                        user["username"],
                        user["role"],
                    )

                except ValueError as exc:
                    app.logger.warning(
                        "Workspace check failed for user ID %s: %s",
                        user["user_id"],
                        str(exc),
                    )
                    flash(
                        "Your database workspace is not ready yet. "
                        "Please contact the administrator.",
                        "error",
                    )
                    return render_template("signin.html"), 503
                
                except Exception:
                    app.logger.exception(
                        "Unable to check workspace for user ID %s",
                        user["user_id"],
                    )

                    flash(
                        "Your workspace is temporarily unavailable. "
                        "Please contact the administrator.",
                        "error",
                    )
                    return render_template("signin.html"), 503

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
    feedback_items = get_user_feedback(session["user_id"])

    for item in feedback_items:
        item["conversation_messages"] = get_feedback_messages(
            item["feedback_id"]
        )


    active_panel = request.args.get("panel", "")
    if active_panel not in {"feedback", "conversations"}:
        active_panel = ""


    return render_template(
        "user_home.html",
        question="",
        result=None,
        error=None,
        history=history,
        feedback_items=feedback_items,
        active_panel=active_panel,
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
    feedback_items = get_user_feedback(session["user_id"])

    return render_template(
        "user_dashboard.html",
        history=history,
        feedback_items=feedback_items,
    )



# --------------------------------------------------
# TEXT-TO-SQL QUERY
# --------------------------------------------------

@app.route("/ask", methods=["POST"])
@role_required("user")
def ask():

    if os.getenv("DEMO_MODE", "0").strip() == "1":
        flash(
            "Hosted demo mode is active. Real AI generation "
            "and database execution are disabled.",
            "info",
        )
        return redirect(url_for("user_home"))

    # Check workspace readiness for every SQL request.
    user_id = session["user_id"]

    try:
        workspace = get_workspace_credentials(user_id)

    except ValueError:
        flash(
            "Your database workspace is not ready yet. "
            "Please contact the administrator.",
            "error",
        )
        return redirect(url_for("user_home"))

    except Exception:
        app.logger.exception(
            "Workspace readiness check failed for user ID %s",
            user_id,
        )

        flash(
            "Your database workspace is temporarily unavailable.",
            "error",
        )

        return redirect(url_for("user_home"))


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


    # Hosted demo safety switch.
    # When enabled, do not call Ollama or execute SQL.

    result = None
    error = None
    status = "failed"
    generated_sql = None

    try:
        result = ask_database(
            question,
            user_id=session["user_id"],
        )

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
# EXPLAIN GENERATED SQL
# --------------------------------------------------

@app.route("/explain-query", methods=["POST"])
@role_required("user")
def explain_query():
    # Never call AI services in hosted demo mode.
    if os.getenv("DEMO_MODE", "0").strip() == "1":
        return {
            "error": "Query explanations are disabled in the hosted demo."
        }, 403

    data = request.get_json(silent=True)

    if not isinstance(data, dict):
        return {"error": "Invalid request."}, 400

    question = data.get("question", "")
    sql = data.get("sql", "")

    if not isinstance(question, str) or not isinstance(sql, str):
        return {"error": "Invalid question or SQL."}, 400

    question = question.strip()
    sql = sql.strip()

    if not question or not sql:
        return {
            "error": "A question and generated SQL are required."
        }, 400

    if len(question) > 2000 or len(sql) > 10000:
        return {"error": "The question or SQL is too long."}, 400

    try:
        explanation = explain_sql(question, sql)

        return {"explanation": explanation}, 200

    except (ValueError, requests.RequestException):
        app.logger.exception("SQL explanation request failed.")
        return {
            "error": "Unable to generate an explanation. Please try again."
        }, 502

    except Exception:
        app.logger.exception("Unexpected SQL explanation error.")
        return {
            "error": "An unexpected error occurred while explaining the query."
        }, 500


# --------------------------------------------------
# DATA SOURCES
# --------------------------------------------------

@app.route("/data-sources")
@role_required("user")
def data_sources():
    # Connect this page to the actual database connection
    # after confirming the connection function in db.py.
    return render_template("data_sources.html")





@app.route("/feedback", methods=["GET", "POST"])
@role_required("user")
def feedback():
    if request.method == "POST":
        category = request.form.get("category", "").strip()
        message = request.form.get("message", "").strip()

        allowed_categories = {
            "Suggestion",
            "Bug Report",
            "General Feedback",
        }

        if category not in allowed_categories:
            flash("Please select a valid feedback category.", "error")
            return redirect(url_for("user_home", panel="feedback"))

        if not message or len(message) > 2000:
            flash(
                "Please enter feedback between 1 and 2000 characters.",
                "error",
            )
            return redirect(url_for("user_home", panel="feedback"))

        record_feedback(
            session["user_id"],
            category,
            message,
        )

        flash("Thank you! Your feedback has been submitted.", "success")
        return redirect(url_for("user_home", panel="conversations"))

    return render_template("feedback.html")





@app.route(
    "/feedback/<int:feedback_id>/reply",
    methods=["POST"],
)
@role_required("user")
def user_feedback_reply(feedback_id):
    message = request.form.get("message", "").strip()

    if not message or len(message) > 2000:
        flash(
            "Please enter a message between 1 and 2000 characters.",
            "error",
        )
        return redirect(url_for("user_home"))

    owner = get_feedback_owner(feedback_id)

    if not owner or owner["user_id"] != session["user_id"]:
        flash("Feedback conversation was not found.", "error")
        return redirect(url_for("user_home"))

    try:
        add_feedback_message(
            feedback_id,
            session["user_id"],
            "user",
            message,
        )
    except sqlite3.Error:
        app.logger.exception("Unable to save user feedback message.")
        flash("Could not send your message. Please try again.", "error")
        return redirect(url_for("user_home"))

    flash("Message sent successfully.", "success")
    return redirect(url_for("user_home"))



# --------------------------------------------------
# ADMIN DASHBOARD
# --------------------------------------------------

@app.route("/admin")
@role_required("admin")
def admin_dashboard():

    active_panel = request.args.get("panel", "home")

    if active_panel not in {"home", "feedback"}:
        active_panel = "home"

    users = list_users()
    history = get_query_history(limit=10)

    feedback = get_all_feedback()

    for item in feedback:
        item["conversation_messages"] = get_feedback_messages(
            item["feedback_id"]
        )

    return render_template(
        "admin_dashboard.html",
        users=users,
        history=history,
        feedback=feedback,
        user_count=len(users),
        active_count=sum(
            user["is_active"] for user in users
        ),
        active_panel=active_panel,
    )



# --------------------------------------------------
# ADMIN FEEDBACK MANAGEMENT
# --------------------------------------------------


@app.route(
    "/admin/feedback/<int:feedback_id>/reply",
    methods=["POST"],
)
@role_required("admin")
def admin_feedback_reply(feedback_id):
    message = request.form.get("admin_reply", "").strip()

    if not message or len(message) > 2000:
        flash(
            "Please enter a reply between 1 and 2000 characters.",
            "error",
        )
        return redirect(
            url_for("admin_dashboard", panel="feedback")
        )

    owner = get_feedback_owner(feedback_id)

    if not owner:
        flash("Feedback conversation was not found.", "error")
        return redirect(
            url_for("admin_dashboard", panel="feedback")
        )

    try:
        message_id = add_feedback_message(
            feedback_id,
            session["user_id"],
            "admin",
            message,
        )

        if not message_id:
            flash("Feedback conversation was not found.", "error")
            return redirect(
                url_for("admin_dashboard", panel="feedback")
            )

        # Keep the legacy field updated for existing dashboard displays.
        save_admin_feedback_reply(feedback_id, message)

    except sqlite3.Error:
        app.logger.exception("Unable to save admin feedback message.")
        flash("Could not save the reply. Please try again.", "error")
        return redirect(
            url_for("admin_dashboard", panel="feedback")
        )

    flash("Admin reply sent successfully.", "success")
    return redirect(
        url_for("admin_dashboard", panel="feedback")
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
# CREATE TABLE IN PRIVATE USER WORKSPACE
# --------------------------------------------------

@app.route("/workspace/create-table", methods=["POST"])
@role_required("user")
def workspace_create_table():

    # Never execute database changes in hosted demo mode.
    if os.getenv("DEMO_MODE", "0").strip() == "1":
        return {
            "error": "Table creation is disabled in demo mode."
        }, 403

    # Identity must come from the authenticated session.
    user_id = session["user_id"]

    # Only accept JSON requests.
    if not request.is_json:
        return {
            "error": "JSON request required."
        }, 415

    data = request.get_json(silent=True)

    if not isinstance(data, dict):
        return {
            "error": "Invalid request body."
        }, 400

    # Reject unexpected fields, including supplied user IDs.
    if set(data) != {"table_name", "columns"}:
        return {
            "error": "Only table_name and columns are allowed."
        }, 400

    table_name = data["table_name"]
    columns = data["columns"]

    try:
        result = create_workspace_table(
            user_id=user_id,
            table_name=table_name,
            columns=columns,
        )

        return result, 201

    except ValueError as exc:
        return {"error": str(exc)}, 400

    except PermissionError:
        return {
            "error": "Workspace access denied."
        }, 403

    except Exception:
        app.logger.exception(
            "Table creation failed for user ID %s",
            user_id,
        )

        return {
            "error": "Unable to create table. Check server logs."
        }, 500




# --------------------------------------------------
# ADD COLUMN TO EXISTING WORKSPACE TABLE
# --------------------------------------------------

@app.route("/workspace/add-column", methods=["POST"])
@role_required("user")
def workspace_add_column():

    if os.getenv("DEMO_MODE", "0").strip() == "1":
        return {
            "error": "Adding columns is disabled in demo mode."
        }, 403

    if not request.is_json:
        return {"error": "JSON request required."}, 415

    data = request.get_json(silent=True)

    if not isinstance(data, dict):
        return {"error": "Invalid request body."}, 400

    if set(data) != {
        "table_name",
        "column_name",
        "data_type",
    }:
        return {
            "error": (
                "Provide table_name, column_name and data_type."
            )
        }, 400

    try:
        result = add_workspace_column(
            user_id=session["user_id"],
            table_name=data["table_name"],
            column_name=data["column_name"],
            data_type=data["data_type"],
        )

        return result, 200

    except ValueError as exc:
        return {"error": str(exc)}, 400

    except PermissionError:
        return {"error": "Workspace access denied."}, 403

    except Exception:
        app.logger.exception(
            "Unable to add column to workspace table."
        )

        return {
            "error": "Unable to add column. Check server logs."
        }, 500



# =========================================================
# WORKSPACE TABLE MANAGEMENT ROUTES
# =========================================================

def workspace_management_demo_mode():
    return os.getenv("DEMO_MODE", "0").strip() == "1"


@app.route("/workspace/delete-column", methods=["POST"])
@role_required("user")
def workspace_delete_column():

    if workspace_management_demo_mode():
        return {"error": "This feature is unavailable in demo mode."}, 403

    if not request.is_json:
        return {"error": "JSON request required."}, 415

    data = request.get_json(silent=True)

    if not isinstance(data, dict) or set(data) != {
        "table_name", "column_name"
    }:
        return {"error": "Provide table_name and column_name."}, 400

    try:
        delete_workspace_column(
            user_id=session["user_id"],
            table_name=data["table_name"],
            column_name=data["column_name"],
        )
        return {"message": "Column deleted successfully."}, 200

    except ValueError as exc:
        return {"error": str(exc)}, 400

    except PermissionError:
        return {"error": "Workspace access denied."}, 403

    except Exception:
        app.logger.exception("Delete column failed.")
        return {"error": "Could not delete column. Check server logs."}, 500


@app.route("/workspace/rename-column", methods=["POST"])
@role_required("user")
def workspace_rename_column():

    if workspace_management_demo_mode():
        return {"error": "This feature is unavailable in demo mode."}, 403

    if not request.is_json:
        return {"error": "JSON request required."}, 415

    data = request.get_json(silent=True)

    if not isinstance(data, dict) or set(data) != {
        "table_name", "old_column_name", "new_column_name"
    }:
        return {
            "error": "Provide table_name, old_column_name and new_column_name."
        }, 400

    try:
        rename_workspace_column(
            user_id=session["user_id"],
            table_name=data["table_name"],
            old_column_name=data["old_column_name"],
            new_column_name=data["new_column_name"],
        )
        return {"message": "Column renamed successfully."}, 200

    except ValueError as exc:
        return {"error": str(exc)}, 400

    except PermissionError:
        return {"error": "Workspace access denied."}, 403

    except Exception:
        app.logger.exception("Rename column failed.")
        return {"error": "Could not rename column. Check server logs."}, 500


@app.route("/workspace/modify-column", methods=["POST"])
@role_required("user")
def workspace_modify_column():

    if workspace_management_demo_mode():
        return {"error": "This feature is unavailable in demo mode."}, 403

    if not request.is_json:
        return {"error": "JSON request required."}, 415

    data = request.get_json(silent=True)

    if not isinstance(data, dict) or set(data) != {
        "table_name", "column_name", "data_type", "nullable"
    }:
        return {
            "error": "Provide table_name, column_name, data_type and nullable."
        }, 400

    if not isinstance(data["nullable"], bool):
        return {"error": "nullable must be true or false."}, 400

    try:
        modify_workspace_column(
            user_id=session["user_id"],
            table_name=data["table_name"],
            column_name=data["column_name"],
            data_type=data["data_type"],
            nullable=data["nullable"],
        )
        return {"message": "Column modified successfully."}, 200

    except ValueError as exc:
        return {"error": str(exc)}, 400

    except PermissionError:
        return {"error": "Workspace access denied."}, 403

    except Exception:
        app.logger.exception("Modify column failed.")
        return {"error": "Could not modify column. Check server logs."}, 500


@app.route("/workspace/rename-table", methods=["POST"])
@role_required("user")
def workspace_rename_table():

    if workspace_management_demo_mode():
        return {"error": "This feature is unavailable in demo mode."}, 403

    if not request.is_json:
        return {"error": "JSON request required."}, 415

    data = request.get_json(silent=True)

    if not isinstance(data, dict) or set(data) != {
        "table_name", "new_table_name"
    }:
        return {
            "error": "Provide table_name and new_table_name."
        }, 400

    try:
        rename_workspace_table(
            user_id=session["user_id"],
            table_name=data["table_name"],
            new_table_name=data["new_table_name"],
        )
        return {"message": "Table renamed successfully."}, 200

    except ValueError as exc:
        return {"error": str(exc)}, 400

    except PermissionError:
        return {"error": "Workspace access denied."}, 403

    except Exception:
        app.logger.exception("Rename table failed.")
        return {"error": "Could not rename table. Check server logs."}, 500


@app.route("/workspace/delete-table", methods=["POST"])
@role_required("user")
def workspace_delete_table():

    if workspace_management_demo_mode():
        return {"error": "This feature is unavailable in demo mode."}, 403

    if not request.is_json:
        return {"error": "JSON request required."}, 415

    data = request.get_json(silent=True)

    if not isinstance(data, dict) or set(data) != {"table_name"}:
        return {"error": "Provide table_name."}, 400

    try:
        delete_workspace_table(
            user_id=session["user_id"],
            table_name=data["table_name"],
        )
        return {"message": "Table deleted successfully."}, 200

    except ValueError as exc:
        return {"error": str(exc)}, 400

    except PermissionError:
        return {"error": "Workspace access denied."}, 403

    except Exception:
        app.logger.exception("Delete table failed.")
        return {"error": "Could not delete table. Check server logs."}, 500





  

@app.route("/workspace/my-tables", methods=["GET"])
@role_required("user")
def workspace_my_tables():
    if os.getenv("DEMO_MODE", "0").strip() == "1":
        return {"error": "Table listing is disabled in demo mode."}, 403

    try:
        tables = list_workspace_tables(session["user_id"])
        return {"tables": tables}, 200

    except PermissionError:
        return {"error": "Workspace access denied."}, 403

    except Exception:
        app.logger.exception("Unable to list workspace tables.")
        return {"error": "Unable to load your tables."}, 500



@app.route("/workspace/insert-record", methods=["POST"])
@role_required("user")
def workspace_insert_record():

    if os.getenv("DEMO_MODE", "0").strip() == "1":
        return {
            "error": "Record insertion is disabled in demo mode."
        }, 403

    if not request.is_json:
        return {"error": "JSON request required."}, 415

    data = request.get_json(silent=True)

    if not isinstance(data, dict):
        return {"error": "Invalid request body."}, 400

    if set(data) != {"table_name", "values"}:
        return {
            "error": "Only table_name and values are allowed."
        }, 400

    try:
        result = insert_workspace_record(
            user_id=session["user_id"],
            table_name=data["table_name"],
            values=data["values"],
        )

        return result, 201

    except ValueError as exc:
        return {"error": str(exc)}, 400

    except PermissionError:
        return {"error": "Workspace access denied."}, 403

    except Exception:
        app.logger.exception(
            "Unable to insert workspace record."
        )
        return {
            "error": "Unable to insert record. Check server logs."
        }, 500



@app.route("/workspace/view-records", methods=["GET"])
@role_required("user")
def workspace_view_records():
    if os.getenv("DEMO_MODE", "0").strip() == "1":
        return {"error": "Record viewing is disabled in demo mode."}, 403


    table_name = request.args.get("table", "")

    try:
        result = view_workspace_records(
            user_id=session["user_id"],
            table_name=table_name,
        )

        return result, 200

    except ValueError as exc:
        return {"error": str(exc)}, 400

    except PermissionError:
        return {"error": "Workspace access denied."}, 403

    except Exception:
        app.logger.exception(
            "Unable to view workspace records."
        )
        return {
            "error": "Unable to load records."
        }, 500



# --------------------------------------------------
# UPDATE / DELETE WORKSPACE RECORDS
# --------------------------------------------------

@app.route("/workspace/record-keys", methods=["GET"])
@role_required("user")
def workspace_record_keys():
    if os.getenv("DEMO_MODE", "0").strip() == "1":
        return {"error": "Primary key lookup is disabled in demo mode."}, 403

    try:
        return get_workspace_record_keys(
            session["user_id"],
            request.args.get("table", "")
        ), 200

    except ValueError as exc:
        return {"error": str(exc)}, 400

    except PermissionError:
        return {"error": "Workspace access denied."}, 403

    except Exception:
        app.logger.exception(
            "Unable to retrieve workspace primary keys"
        )
        return {"error": "Unable to retrieve primary keys."}, 500


@app.route("/workspace/update-record", methods=["POST"])
@role_required("user")
def workspace_update_record():
    if os.getenv("DEMO_MODE", "0").strip() == "1":
        return {"error": "Editing is disabled in demo mode."}, 403

    if not request.is_json:
        return {"error": "JSON request required."}, 415

    data = request.get_json(silent=True)

    if not isinstance(data, dict) or set(data) != {
        "table_name", "keys", "values"
    }:
        return {
            "error": "Provide table_name, keys and values."
        }, 400

    try:
        return modify_workspace_record(
            session["user_id"],
            data["table_name"],
            data["keys"],
            values=data["values"]
        ), 200

    except ValueError as exc:
        return {"error": str(exc)}, 400

    except PermissionError:
        return {"error": "Workspace access denied."}, 403

    except Exception:
        app.logger.exception("Workspace record update failed")
        return {"error": "Unable to update record."}, 500


@app.route("/workspace/delete-record", methods=["POST"])
@role_required("user")
def workspace_delete_record():
    if os.getenv("DEMO_MODE", "0").strip() == "1":
        return {"error": "Deleting is disabled in demo mode."}, 403

    if not request.is_json:
        return {"error": "JSON request required."}, 415

    data = request.get_json(silent=True)

    if not isinstance(data, dict) or set(data) != {
        "table_name", "keys"
    }:
        return {
            "error": "Provide table_name and keys."
        }, 400

    try:
        return modify_workspace_record(
            session["user_id"],
            data["table_name"],
            data["keys"],
            delete=True
        ), 200

    except ValueError as exc:
        return {"error": str(exc)}, 400

    except PermissionError:
        return {"error": "Workspace access denied."}, 403

    except Exception:
        app.logger.exception("Workspace record deletion failed")
        return {"error": "Unable to delete record."}, 500


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
