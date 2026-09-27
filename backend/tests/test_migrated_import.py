from __future__ import annotations

import csv
import io
import os
import tempfile
import unittest
from pathlib import Path

os.environ.setdefault("DATABASE_URL", "sqlite+pysqlite:///:memory:")

from alembic import command
from alembic.config import Config
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, func, select

from app.auth import hash_password
from app.database import make_session_factory
from app.imports_exports import FIELDS
from app.main import create_app
from app.models import LabelPrintBatch, Location, Mold, OperationItem, Person, User
from pilot_storage import import_database


class MigratedImportTest(unittest.TestCase):
    def test_portable_database_keeps_password_after_reopening(self) -> None:
        project = Path(__file__).resolve().parents[1]
        with tempfile.TemporaryDirectory(prefix="codex-mold-portable-") as directory:
            source = Path(directory) / "office.sqlite3"
            target = Path(directory) / "usb" / "warehouse.sqlite3"
            prior_url = os.environ.get("DATABASE_URL")
            os.environ["DATABASE_URL"] = "sqlite+pysqlite:///" + source.as_posix()
            config = Config(str(project / "alembic.ini"))
            config.set_main_option("script_location", str(project / "migrations"))
            try:
                command.upgrade(config, "head")
                original = create_engine(os.environ["DATABASE_URL"])
                with make_session_factory(original)() as db:
                    person = Person(name="原办公室维护员")
                    db.add(person)
                    db.flush()
                    db.add(User(username="admin", password_hash=hash_password("SavedOfficePass-123"), role="ADMIN", person_id=person.id))
                    db.commit()
                original.dispose()
                import_database(source, target, Path(directory) / "backups")
                for _ in range(2):
                    reopened = create_engine("sqlite+pysqlite:///" + target.as_posix())
                    try:
                        with TestClient(create_app(reopened)) as client:
                            login = client.post("/api/auth/login", json={"username": "admin", "password": "SavedOfficePass-123"})
                            self.assertEqual(login.status_code, 200, login.text)
                    finally:
                        reopened.dispose()
            finally:
                if prior_url is None:
                    os.environ.pop("DATABASE_URL", None)
                else:
                    os.environ["DATABASE_URL"] = prior_url

    def test_import_and_label_record_on_migrated_schema(self) -> None:
        project = Path(__file__).resolve().parents[1]
        with tempfile.TemporaryDirectory(prefix="codex-mold-schema-") as directory:
            database = Path(directory) / "warehouse.sqlite3"
            prior_url = os.environ.get("DATABASE_URL")
            os.environ["DATABASE_URL"] = "sqlite+pysqlite:///" + database.as_posix()
            config = Config(str(project / "alembic.ini"))
            config.set_main_option("script_location", str(project / "migrations"))
            try:
                command.upgrade(config, "head")
                engine = create_engine(os.environ["DATABASE_URL"])
                factory = make_session_factory(engine)
                with factory() as db:
                    person = Person(name="维护员")
                    db.add(person)
                    db.flush()
                    db.add_all([
                        User(username="admin", password_hash=hash_password("MigratedTestPass-123"), role="ADMIN", person_id=person.id),
                        Location(code="A-01-1", name="A区1架1层", type="SHELF", zone="A", rack="1", level="1"),
                    ])
                    db.commit()
                with TestClient(create_app(engine)) as client:
                    login = client.post("/api/auth/login", json={"username": "admin", "password": "MigratedTestPass-123"})
                    self.assertEqual(login.status_code, 200, login.text)
                    headers = {"X-CSRF-Token": login.json()["csrf_token"]}
                    output = io.StringIO(newline="")
                    writer = csv.writer(output)
                    writer.writerow(FIELDS)
                    for index in range(10):
                        writer.writerow(["XM-1", "测试模具", "SET-1", "A-01-1", f"M-{index + 1:06d}", str(36 + index), "READY", "A-01-1", ""])
                    preview = client.post("/api/imports/preview", content=output.getvalue().encode("utf-8"), headers={**headers, "Content-Type": "text/csv"})
                    self.assertEqual(preview.status_code, 200, preview.text)
                    self.assertTrue(preview.json()["valid"], preview.text)
                    committed = client.post("/api/imports/commit", json={"token": preview.json()["token"], "sha256": preview.json()["sha256"]}, headers=headers)
                    self.assertEqual(committed.status_code, 200, committed.text)
                    record = client.post("/api/labels/print-record", json={"request_id": "5dcbab16-4ab2-499a-9d07-15d588746f91", "kind": "MOLD", "codes": ["M-000001"], "purpose": "REPRINT", "reason": "标签磨损"}, headers=headers)
                    self.assertEqual(record.status_code, 200, record.text)
                with factory() as db:
                    self.assertEqual(db.scalar(select(func.count()).select_from(Mold)), 10)
                    self.assertIsNone(db.scalar(select(OperationItem).order_by(OperationItem.id)).before_location_id)
                    self.assertEqual(db.scalar(select(func.count()).select_from(LabelPrintBatch)), 1)
                engine.dispose()
                command.downgrade(config, "873c18a14a94")
                with self.assertRaisesRegex(RuntimeError, "不能直接回退"):
                    command.downgrade(config, "-1")
            finally:
                if prior_url is None:
                    os.environ.pop("DATABASE_URL", None)
                else:
                    os.environ["DATABASE_URL"] = prior_url


if __name__ == "__main__":
    unittest.main()
