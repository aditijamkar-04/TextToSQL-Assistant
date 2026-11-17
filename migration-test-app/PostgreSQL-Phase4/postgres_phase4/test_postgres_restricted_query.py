import unittest
from postgres_restricted_query import names, execute_restricted_select

class OfflineTests(unittest.TestCase):
    def test_names(self):
        self.assertEqual(names(12), ('workspace_12', 'workspace_reader_12'))
        for bad in [0, -1, True, '1x', '01', None]:
            with self.subTest(bad=bad), self.assertRaises(ValueError):
                names(bad)

    def test_rejects_other_workspace_without_database(self):
        with self.assertRaises(ValueError):
            execute_restricted_select('SELECT * FROM workspace_2.data', 1, 'test')

    def test_rejects_public_without_database(self):
        with self.assertRaises(ValueError):
            execute_restricted_select('SELECT * FROM public.users', 1, 'test')

    def test_rejects_function_without_database(self):
        with self.assertRaises(ValueError):
            execute_restricted_select('SELECT pg_sleep(1) FROM workspace_1.data', 1, 'test')

if __name__ == '__main__':
    unittest.main()
