from __future__ import annotations

import os
import unittest
from unittest.mock import patch

from app.database import database_url


class DatabaseConfigTest(unittest.TestCase):
    def test_postgres_password_with_url_characters(self) -> None:
        with patch.dict(os.environ, {"DATABASE_URL": "", "POSTGRES_HOST": "db", "POSTGRES_USER": "warehouse", "POSTGRES_PASSWORD": "a@b:/c", "POSTGRES_DB": "warehouse"}):
            url = database_url()
            self.assertEqual(url.password, "a@b:/c")
            self.assertEqual(url.host, "db")
            self.assertIn("a%40b%3A%2Fc", url.render_as_string(hide_password=False))

    def test_production_does_not_fall_back_to_local_sqlite(self) -> None:
        with patch.dict(os.environ, {"DATABASE_URL": "", "POSTGRES_HOST": "", "WAREHOUSE_ENV": "production"}):
            with self.assertRaisesRegex(RuntimeError, "PostgreSQL"):
                database_url()

    def test_development_requires_explicit_database(self) -> None:
        with patch.dict(os.environ, {"DATABASE_URL": "", "POSTGRES_HOST": "", "WAREHOUSE_ENV": "development"}):
            with self.assertRaisesRegex(RuntimeError, "DATABASE_URL"):
                database_url()


if __name__ == "__main__":
    unittest.main()
