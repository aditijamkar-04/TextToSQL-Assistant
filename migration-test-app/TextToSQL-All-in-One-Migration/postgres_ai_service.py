"""Opt-in PostgreSQL AI service. Not connected to Flask routes.

The caller must verify the authenticated user and retrieve the correct
per-user reader password from encrypted server-side storage.
"""
from groq_client import generate_ai_response
from postgres_prompt import build_sql_prompt
from postgres_workspace_core import get_schema_columns
from postgres_restricted_query import execute_restricted_select
from postgres_query_guard import validate_workspace_select


def describe_workspace(user_id):
    rows = get_schema_columns(user_id)
    if not rows:
        return None
    lines = []
    previous = None
    for table, column, data_type, length in rows:
        if table != previous:
            lines.append(f'Table: "workspace_{int(user_id)}"."{table}"')
            previous = table
        kind = str(data_type).upper()
        if length is not None and kind in ('CHARACTER VARYING', 'CHARACTER'):
            kind += f'({length})'
        lines.append(f'- "{column}" {kind}')
    return '\n'.join(lines)


def ask_postgres(question, user_id, reader_password):
    if not isinstance(question, str) or not question.strip():
        raise ValueError('Please enter a question.')
    schema_inventory = describe_workspace(user_id)
    if not schema_inventory:
        return {'status': 'clarification_needed', 'message': 'Your private workspace has no tables yet.'}
    prompt = build_sql_prompt(question, user_id, schema_inventory)
    answer = generate_ai_response(prompt, max_tokens=1200).strip()
    if answer.upper().startswith('CLARIFY:'):
        return {'status': 'clarification_needed', 'message': answer[8:].strip()}
    if answer.startswith('```'):
        import re
        answer = re.sub(r'^```(?:sql)?\s*|\s*```$', '', answer, flags=re.I).strip()
    schema = f'workspace_{int(user_id)}'
    safe_sql = validate_workspace_select(answer, schema)
    result = execute_restricted_select(safe_sql, user_id, reader_password)
    return {'status': 'success', 'question': question, 'sql': safe_sql,
            'columns': result['columns'], 'rows': result['rows']}
