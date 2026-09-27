from __future__ import annotations

import sqlite3
import tempfile
import unittest
from contextlib import closing
from pathlib import Path

from pilot_storage import backup_database, import_database, inspect_database


class PilotStorageTest(unittest.TestCase):
    def test_import_preserves_existing_account_and_rejects_overwrite(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / "office.sqlite3"
            target = root / "usb" / "warehouse.sqlite3"
            backups = root / "local-backups"
            with closing(sqlite3.connect(source)) as db:
                db.executescript("""
                    CREATE TABLE users (username TEXT PRIMARY KEY, password_hash TEXT NOT NULL);
                    CREATE TABLE people (id INTEGER PRIMARY KEY);
                    CREATE TABLE locations (id INTEGER PRIMARY KEY);
                    CREATE TABLE molds (id INTEGER PRIMARY KEY);
                    CREATE TABLE alembic_version (version_num TEXT PRIMARY KEY);
                    INSERT INTO users VALUES ('admin', 'saved-password-hash');
                    INSERT INTO locations VALUES (1);
                    INSERT INTO molds VALUES (1);
                    INSERT INTO alembic_version VALUES ('current');
                """)
                db.commit()
            result = import_database(source, target, backups)
            self.assertEqual(result["accounts"], 1)
            self.assertEqual(result["molds"], 1)
            self.assertEqual(inspect_database(target), inspect_database(source))
            self.assertEqual(inspect_database(Path(result["backup"])), inspect_database(source))
            with closing(sqlite3.connect(target)) as db:
                self.assertEqual(db.execute("SELECT password_hash FROM users WHERE username='admin'").fetchone()[0], "saved-password-hash")
            self.assertEqual(inspect_database(backup_database(target, backups)), inspect_database(source))
            with self.assertRaisesRegex(RuntimeError, "绝不覆盖"):
                import_database(source, target, backups)

    def test_missing_database_never_creates_new_file(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            missing = Path(directory) / "missing.sqlite3"
            with self.assertRaisesRegex(RuntimeError, "找不到数据库"):
                inspect_database(missing)
            self.assertFalse(missing.exists())


if __name__ == "__main__":
    unittest.main()
