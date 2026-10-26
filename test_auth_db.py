import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import auth_db


class TestAuthDatabaseConfiguration(unittest.TestCase):
    def test_sqlite_is_the_default_backend(self):
        with patch.dict("os.environ", {}, clear=False):
            self.assertTrue(
                hasattr(auth_db, "get_auth_connection")
            )

    def test_password_hashing_helpers_are_available(self):
        password = "Test-Password-123!"
        password_hash = auth_db.generate_password_hash(password)

        self.assertNotEqual(password, password_hash)
        self.assertTrue(
            auth_db.check_password_hash(password_hash, password)
        )


if __name__ == "__main__":
    unittest.main(verbosity=2)
