
import unittest

from sql_service import validate_sql


class TestSQLValidation(unittest.TestCase):

    # --------------------------------------------------
    # 1. Valid SELECT queries
    # --------------------------------------------------

    def test_accepts_select_queries(self):
        queries = [
            "SELECT * FROM Employees",
            "select * from Employees",
            "SeLeCt * FrOm Employees",
            "SELECT EmployeeID, EmployeeName FROM dbo.Employees",
            "SELECT * FROM Employees WHERE Salary > 50000",
        ]

        for query in queries:
            with self.subTest(query=query):
                self.assertTrue(validate_sql(query))

    def test_accepts_join_query(self):
        query = """
            SELECT e.EmployeeName, d.DepartmentName
            FROM dbo.Employees AS e
            JOIN dbo.Departments AS d
                ON e.DepartmentID = d.DepartmentID
        """
        self.assertTrue(validate_sql(query))

    def test_accepts_cte_query(self):
        query = """
            WITH HighEarners AS (
                SELECT EmployeeName, Salary
                FROM dbo.Employees
                WHERE Salary > 50000
            )
            SELECT * FROM HighEarners
        """
        self.assertTrue(validate_sql(query))

    def test_accepts_sql_keywords_inside_string(self):
        queries = [
            "SELECT 'DELETE' AS ExampleText",
            "SELECT 'DROP TABLE Employees' AS ExampleText",
            "SELECT 'xp_cmdshell' AS ExampleText",
        ]

        for query in queries:
            with self.subTest(query=query):
                self.assertTrue(validate_sql(query))

    def test_accepts_trailing_semicolon(self):
        self.assertEqual(
            validate_sql("SELECT * FROM Employees;"),
            "SELECT * FROM Employees",
        )

    # --------------------------------------------------
    # 2. Reject destructive or non-SELECT statements
    # --------------------------------------------------

    def test_rejects_non_select_statements(self):
        queries = [
            "DELETE FROM Employees",
            "delete FROM Employees",
            "DeLeTe FROM Employees",
            "UPDATE Employees SET Salary = 100",
            "INSERT INTO Employees VALUES (106, 'Test', 1, 50000)",
            "DROP TABLE Employees",
            "ALTER TABLE Employees ADD TestColumn INT",
            "CREATE TABLE TestTable (ID INT)",
            "TRUNCATE TABLE Employees",
            "MERGE INTO Employees AS target USING Employees AS source "
            "ON target.EmployeeID = source.EmployeeID "
            "WHEN MATCHED THEN DELETE;",
        ]

        for query in queries:
            with self.subTest(query=query):
                with self.assertRaises(ValueError):
                    validate_sql(query)

    def test_rejects_multiple_statements(self):
        queries = [
            "SELECT * FROM Employees; DROP TABLE Employees",
            "SELECT 1; SELECT 2",
            "SELECT 1; DELETE FROM Employees",
        ]

        for query in queries:
            with self.subTest(query=query):
                with self.assertRaises(ValueError):
                    validate_sql(query)

    def test_rejects_select_into(self):
        queries = [
            "SELECT * INTO BackupEmployees FROM Employees",
            "select * into BackupEmployees from Employees",
        ]

        for query in queries:
            with self.subTest(query=query):
                with self.assertRaises(ValueError):
                    validate_sql(query)

    # --------------------------------------------------
    # 3. Reject risky SQL Server functions
    # --------------------------------------------------

    def test_rejects_risky_sql_server_functions(self):
        queries = [
            "SELECT OPENROWSET('SQLNCLI', 'test', 'SELECT 1')",
            "SELECT OPENDATASOURCE('SQLNCLI', 'test').SomeTable",
            "SELECT OPENQUERY(MyServer, 'SELECT 1')",
            "SELECT xp_cmdshell('whoami')",
            "select XP_CMDSHELL('whoami')",
        ]

        for query in queries:
            with self.subTest(query=query):
                with self.assertRaises(ValueError):
                    validate_sql(query)

    # --------------------------------------------------
    # 4. Reject empty or invalid SQL
    # --------------------------------------------------

    def test_rejects_empty_queries(self):
        queries = ["", "   ", "\n\t", None]

        for query in queries:
            with self.subTest(query=query):
                with self.assertRaises(ValueError):
                    validate_sql(query)

    def test_rejects_malformed_sql(self):
        queries = [
            "SELECT FROM WHERE",
            "SELECT * FORM Employees",
            "SELECT * FROM",
        ]

        for query in queries:
            with self.subTest(query=query):
                with self.assertRaises(ValueError):
                    validate_sql(query)


if __name__ == "__main__":
    unittest.main(verbosity=2)
