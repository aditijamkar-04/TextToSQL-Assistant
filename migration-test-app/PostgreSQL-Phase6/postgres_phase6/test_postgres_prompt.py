import unittest
from postgres_prompt import build_sql_prompt

class PromptTests(unittest.TestCase):
    def test_private_schema_and_postgres(self):
        p = build_sql_prompt('top salary', 7, 'Table: "workspace_7"."employees"')
        self.assertIn('"workspace_7"', p)
        self.assertIn('LIMIT', p)
        self.assertIn('not TOP', p)
        self.assertIn('CLARIFY:', p)
    def test_reject_bad_user_ids(self):
        for uid in (True, 0, -1, '1; DROP TABLE', '01', None):
            with self.subTest(uid=uid), self.assertRaises(ValueError):
                build_sql_prompt('question', uid, 'schema')
    def test_empty_question_or_schema(self):
        with self.assertRaises(ValueError):
            build_sql_prompt('', 1, 'schema')
        with self.assertRaises(ValueError):
            build_sql_prompt('question', 1, '')

if __name__ == '__main__':
    unittest.main()
