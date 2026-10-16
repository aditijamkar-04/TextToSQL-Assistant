
import re
import requests

from sql_service import execute_sql


import os

OLLAMA_URL = os.getenv(
    "OLLAMA_URL",
    "http://localhost:11434/api/generate",
).strip()
MODEL = "qwen2.5-coder:3b"


DATABASE_SCHEMA = """
SQL Server database: TextToSQL_DB

Table: dbo.Employees
- EmployeeID INT
- EmployeeName VARCHAR(100)
- DepartmentID INT
- Salary DECIMAL(10,2)

Table: dbo.Departments
- DepartmentID INT
- DepartmentName VARCHAR(100)

Relationship:
Employees.DepartmentID = Departments.DepartmentID

Sample department names: IT, HR, Finance.

Use SQL Server (T-SQL) syntax.
"""


def generate_sql(question):
    """Interpret a natural-language question and generate SQL."""

    if not question or not question.strip():
        raise ValueError("Please enter a question.")

    prompt = f"""
You are an intelligent Text-to-SQL assistant.

Understand what the user MEANS, not just the exact words used.

The user may:
- Use uppercase, lowercase, or mixed capitalization.
- Write incomplete sentences or omit common words.
- Use synonyms such as earns, salary, pay, or income.
- Make minor spelling or grammar mistakes.
- Describe database fields in everyday language.

Use the database schema below to infer the user's intent.

{DATABASE_SCHEMA}


RULES:
1. Generate SQL Server (T-SQL) syntax only.
2. Generate exactly one read-only SELECT query.
3. Use TOP (n) to limit rows, never LIMIT.
4. Never use OFFSET ... LIMIT syntax.
5. For the highest-paid employee, use TOP (1) and ORDER BY Salary DESC.
6. For department questions, define every table alias in FROM or JOIN before using it.
7. Use only the tables and columns in the supplied database schema.
8. Do not ask for clarification if the user's intent is reasonably clear.
9. Return only SQL, or CLARIFY: followed by a question.

Examples:

Question: show employees from HR
SQL:
SELECT e.EmployeeID, e.EmployeeName, e.Salary,
       d.DepartmentName
FROM dbo.Employees AS e
JOIN dbo.Departments AS d
  ON e.DepartmentID = d.DepartmentID
WHERE LOWER(d.DepartmentName) = 'hr';

Question: show highest salary
SQL:
SELECT MAX(Salary) AS HighestSalary
FROM dbo.Employees;

Question: who has highest salary
SQL:
SELECT TOP 1 EmployeeID, EmployeeName, Salary
FROM dbo.Employees
ORDER BY Salary DESC;

Question: who earns most money in IT
SQL:
SELECT TOP 1 e.EmployeeID, e.EmployeeName, e.Salary,
       d.DepartmentName
FROM dbo.Employees AS e
JOIN dbo.Departments AS d
  ON e.DepartmentID = d.DepartmentID
WHERE LOWER(d.DepartmentName) = 'it'
ORDER BY e.Salary DESC;


Question: show all department names
SQL:
SELECT DepartmentName
FROM dbo.Departments;

User question:
{question}

Return the SQL query or a CLARIFY question.
"""

    response = requests.post(
        OLLAMA_URL,
        json={
            "model": MODEL,
            "prompt": prompt,
            "stream": False,
            "options": {"temperature": 0},
        },
        timeout=180,
    )
    response.raise_for_status()

    answer = response.json()["response"].strip()

    if answer.upper().startswith("CLARIFY:"):
        return {
            "status": "clarification_needed",
            "message": answer[len("CLARIFY:"):].strip(),
        }

    # Remove Markdown code fences if the model adds them.
    answer = re.sub(
        r"^\s*```(?:sql|tsql)?\s*",
        "",
        answer,
        flags=re.IGNORECASE,
    )
    answer = re.sub(r"\s*```\s*$", "", answer).strip()

    # Extract a SELECT statement if the model adds an introduction.
    match = re.search(r"\bSELECT\b", answer, re.IGNORECASE)
    if not match:
        raise ValueError("The AI did not return a SQL SELECT query.")

    sql = answer[match.start():].strip()

    return {
        "status": "sql_generated",
        "sql": sql,
    }


def ask_database(question):
    """Generate SQL and execute it after validation."""

    generated = generate_sql(question)

    if generated["status"] == "clarification_needed":
        return generated

    result = execute_sql(generated["sql"])

    return {
        "status": "success",
        "question": question,
        "sql": generated["sql"],
        "columns": result["columns"],
        "rows": result["rows"],
    }


if __name__ == "__main__":
    print("Text-to-SQL Assistant")
    print("Type 'exit' to quit.\n")

    while True:
        question = input("Ask your database: ").strip()

        if question.lower() in {"exit", "quit"}:
            break

        try:
            result = ask_database(question)

            if result["status"] == "clarification_needed":
                print("AI:", result["message"])
                continue

            print("\nGenerated SQL:")
            print(result["sql"])

            print("\nResults:")
            print(" | ".join(result["columns"]))

            for row in result["rows"]:
                print(" | ".join(
                    str(value) for value in row
                ))

            print(f"\nRows returned: {len(result['rows'])}")

        except (ValueError, requests.RequestException) as error:
            print("\nCould not process the question:", error)

        except Exception as error:
            print("\nQuery failed:", error)

        print()
