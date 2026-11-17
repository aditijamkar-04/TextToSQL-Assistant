"""Offline staging audit; no Neon connection or mutation."""
import ast
import pathlib
import unittest

ROOT = pathlib.Path(__file__).resolve().parent

class StagingAudit(unittest.TestCase):
    def test_all_python_files_parse(self):
        for name in ('app.py', 'auth_db.py', 'groq_client.py', 'text_to_sql.py',
                     'postgres_workspace_core.py', 'postgres_workspace_tables.py',
                     'postgres_query_guard.py', 'postgres_restricted_query.py',
                     'postgres_prompt.py'):
            with self.subTest(name=name):
                ast.parse((ROOT / name).read_text(encoding='utf-8-sig'))

    def test_flask_route_compatibility(self):
        def signatures(path):
            tree=ast.parse((ROOT/path).read_text(encoding='utf-8-sig'))
            return {n.name: len(n.args.args) for n in tree.body if isinstance(n, ast.FunctionDef)}
        old=signatures('workspace_tables.py')
        new=signatures('postgres_workspace_tables.py')
        for name in ('create_workspace_table','list_workspace_tables',
                     'insert_workspace_record','view_workspace_records',
                     'modify_workspace_record','get_workspace_record_keys'):
            with self.subTest(name=name):
                self.assertIn(name, new)
                if name == "create_workspace_table":
                    self.assertEqual(old[name] + 1, new[name])
                else:
                    self.assertEqual(old[name], new[name])

    def test_restricted_sql_uses_non_owner_credentials(self):
        source=(ROOT/'postgres_restricted_query.py').read_text(encoding='utf-8')
        self.assertIn('_reader_dsn(role, password)', source)
        self.assertIn('SET TRANSACTION READ ONLY', source)
        self.assertIn('current_user', source)

    def test_no_automatic_deployment_switch(self):
        source=(ROOT/'app.py').read_text(encoding='utf-8-sig')
        self.assertNotIn('postgres_restricted_query', source)

if __name__ == '__main__':
    unittest.main(verbosity=2)
