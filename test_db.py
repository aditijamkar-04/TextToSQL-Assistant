from db import get_connection


def test_connection():
    connection = None

    try:
        connection = get_connection()
        print("Connected to SQL Server successfully!")

        cursor = connection.cursor()

        cursor.execute("""
            SELECT @@SERVERNAME AS ServerName,
                   DB_NAME() AS DatabaseName;
        """)

        row = cursor.fetchone()
        print("Server:", row.ServerName)
        print("Database:", row.DatabaseName)

        cursor.execute("""
            SELECT EmployeeID, EmployeeName, Salary
            FROM dbo.Employees
            ORDER BY EmployeeID;
        """)

        rows = cursor.fetchall()

        print("\nEmployee records:")

        for row in rows:
            print(
                f"ID: {row.EmployeeID}, "
                f"Name: {row.EmployeeName}, "
                f"Salary: {row.Salary}"
            )

        print(f"\nTotal employees: {len(rows)}")

    except Exception as error:
        print("Connection or query failed:")
        print(error)

    finally:
        if connection is not None:
            connection.close()
            print("\nDatabase connection closed.")


if __name__ == "__main__":
    test_connection()