
import requests

OLLAMA_URL = "http://localhost:11434/api/generate"


def test_ollama():
    prompt = """
    Write a SQL Server query to display
    EmployeeID, EmployeeName, and Salary
    from dbo.Employees where Salary > 50000.

    Return only the SQL query.
    """

    payload = {
        "model": "qwen2.5-coder:3b",
        "prompt": prompt,
        "stream": False,
    }

    try:
        response = requests.post(
            OLLAMA_URL,
            json=payload,
            timeout=120,
        )
        response.raise_for_status()

        result = response.json()
        print("Generated SQL:")
        print(result["response"])

    except requests.RequestException as error:
        print("Could not connect to Ollama:", error)


if __name__ == "__main__":
    test_ollama()
