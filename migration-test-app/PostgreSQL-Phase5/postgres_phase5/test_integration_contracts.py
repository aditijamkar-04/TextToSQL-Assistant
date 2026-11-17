"""Offline interface checks for Phase 3/4 modules and original Flask routes.
Does not require a database, credentials, or third-party dependencies.
"""
import ast
from pathlib import Path
import unittest

ROOT = Path(__file__).resolve().parent

def functions(path):
    tree = ast.parse(path.read_text(encoding='utf-8-sig'))
    return {n.name: n for n in tree.body if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))}

def args(node):
    return [a.arg for a in node.args.args]

class IntegrationContracts(unittest.TestCase):
    def test_crud_signatures(self):
        original = functions(ROOT/'original_workspace_tables.py')
        replacement = functions(ROOT/'postgres_workspace_tables.py')
        for name in ('create_workspace_table', 'list_workspace_tables', 'insert_workspace_record',
                     'view_workspace_records', 'modify_workspace_record', 'get_workspace_record_keys'):
            self.assertIn(name, replacement)
            self.assertEqual(args(original[name]), args(replacement[name]), name)

    def test_sql_executor_not_owner(self):
        tree = ast.parse((ROOT/'postgres_restricted_query.py').read_text())
        fn = functions(ROOT/'postgres_restricted_query.py')['execute_restricted_select']
        calls = [n for n in ast.walk(fn) if isinstance(n, ast.Call)]
        self.assertTrue(any(isinstance(n.func, ast.Name) and n.func.id == '_reader_dsn' for n in calls))
        self.assertFalse(any(isinstance(n.func, ast.Name) and n.func.id == '_owner_url' for n in calls))

    def test_guard_uses_postgres(self):
        src = (ROOT/'postgres_query_guard.py').read_text()
        self.assertIn('postgres', src.lower())

    def test_no_live_credentials(self):
        for p in (ROOT/'postgres_workspace_tables.py', ROOT/'postgres_restricted_query.py', ROOT/'postgres_workspace_core.py'):
            self.assertNotIn('sk-proj-', p.read_text())

if __name__ == '__main__':
    unittest.main(verbosity=2)
