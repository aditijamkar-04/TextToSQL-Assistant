import os

import pyodbc
from dotenv import load_dotenv

load_dotenv()


def get_connection():
    """Connect to the TextToSQL_DB SQL Server database."""

    server = os.getenv("DB_SERVER")
    database = os.getenv("DB_NAME")
    username = os.getenv("DB_USER")
    password = os.getenv("DB_PASSWORD")
    driver = os.getenv("DB_DRIVER")

    required = {
        "DB_SERVER": server,
        "DB_NAME": database,
        "DB_USER": username,
        "DB_PASSWORD": password,
        "DB_DRIVER": driver,
    }

    missing = [
        key for key, value in required.items()
        if not value
    ]

    if missing:
        raise ValueError(
            f"Missing environment variables: {', '.join(missing)}"
        )

    connection_string = (
        f"DRIVER={{{driver}}};"
        f"SERVER={server};"
        f"DATABASE={database};"
        f"UID={username};"
        f"PWD={password};"
        "Encrypt=yes;"
        "TrustServerCertificate=yes;"
        "Connection Timeout=10;"
    )

    return pyodbc.connect(connection_string)