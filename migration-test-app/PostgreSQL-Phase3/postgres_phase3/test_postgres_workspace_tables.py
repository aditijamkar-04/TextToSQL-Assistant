import unittest
from psycopg import sql
from postgres_workspace_tables import build_create_table_sql, _schema, _id

class TestOfflineValidation(unittest.TestCase):
    def test_user_schema(self):
        self.assertEqual(_schema(4), 'workspace_4')
        for bad in [0, -1, True, '1; DROP TABLE users', '1.0']:
            with self.subTest(bad=bad), self.assertRaises(ValueError):
                _schema(bad)

    def test_identifiers(self):
        self.assertEqual(_id('Employees_2'), 'Employees_2')
        for bad in ['a.b', 'x";DROP TABLE users;--', 'x' * 64, '']:
            with self.subTest(bad=bad), self.assertRaises(ValueError):
                _id(bad)

    def test_composable_sql_and_type_mapping(self):
        q = build_create_table_sql(1, 'Employees', [
            {'name':'Name', 'type':'NVARCHAR(100)'},
            {'name':'Joined', 'type':'DATETIME2'},
        ])
        self.assertIsInstance(q, sql.Composable)

    def test_reject_duplicate_and_injected_type(self):
        with self.assertRaises(ValueError):
            build_create_table_sql(1, 'Employees', [{'name':'a','type':'INT'}, {'name':'A','type':'INT'}])
        with self.assertRaises(ValueError):
            build_create_table_sql(1, 'Employees', [{'name':'a','type':'INT); DROP TABLE users;--'}])

if __name__ == '__main__':
    unittest.main()
