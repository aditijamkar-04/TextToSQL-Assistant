import unittest
from postgres_workspace_core import workspace_schema, grant_reader_schema

class WorkspaceCoreTests(unittest.TestCase):
    def test_valid(self):
        self.assertEqual(workspace_schema(1), 'workspace_1')
        self.assertEqual(workspace_schema('123'), 'workspace_123')

    def test_invalid(self):
        for value in (0, -1, True, None, 'abc', '01', '1; DROP SCHEMA public', 1.5):
            with self.subTest(value=value), self.assertRaises(ValueError):
                workspace_schema(value)

    def test_shared_reader_is_not_allowed(self):
        with self.assertRaises(RuntimeError):
            grant_reader_schema(1)

if __name__ == '__main__':
    unittest.main()
