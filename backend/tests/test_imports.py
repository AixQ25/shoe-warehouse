from __future__ import annotations

import csv
import io
import os
import unittest

os.environ.setdefault("DATABASE_URL", "sqlite+pysqlite:///:memory:")

from fastapi.testclient import TestClient
from sqlalchemy import create_engine, event, func, select
from sqlalchemy.pool import StaticPool

from app.auth import hash_password
from app.database import Base, make_session_factory
from app.imports_exports import FIELDS
from app.main import create_app
from app.models import ImportBatch, LabelPrintBatch, Location, Mold, MoldModel, MoldSet, Operation, OperationItem, Person, StocktakeSession, User


class ImportExportTest(unittest.TestCase):
    def setUp(self) -> None:
        self.engine = create_engine("sqlite+pysqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)

        @event.listens_for(self.engine, "connect")
        def fk_on(connection, _record):
            connection.execute("PRAGMA foreign_keys=ON")

        Base.metadata.create_all(self.engine)
        self.factory = make_session_factory(self.engine)
        with self.factory() as db:
            admin_person = Person(name="维护员")
            worker_person = Person(name="领用人")
            db.add_all([admin_person, worker_person])
            db.flush()
            db.add_all([
                User(username="admin", password_hash=hash_password("ImportAdminPass-123"), role="ADMIN", person_id=admin_person.id),
                User(username="worker", password_hash=hash_password("ImportWorkerPass-123"), role="WORKER", person_id=worker_person.id),
                User(username="viewer", password_hash=hash_password("ImportViewerPass-123"), role="READONLY"),
                Location(code="A-01-1", name="A区1架1层", type="SHELF", zone="A", rack="1", level="1"),
                Location(code="A-01-2", name="A区1架2层", type="SHELF", zone="A", rack="1", level="2"),
                Location(code="INSPECTION-01", name="待检区", type="INSPECTION"),
            ])
            db.commit()
        self.app = create_app(self.engine)
        self.admin = TestClient(self.app)
        self.worker = TestClient(self.app)
        self.viewer = TestClient(self.app)
        self.admin_csrf = self.login(self.admin, "admin", "ImportAdminPass-123")

    def tearDown(self) -> None:
        self.admin.close()
        self.worker.close()
        self.viewer.close()
        self.engine.dispose()

    def login(self, client: TestClient, username: str, password: str) -> str:
        response = client.post("/api/auth/login", json={"username": username, "password": password})
        self.assertEqual(response.status_code, 200, response.text)
        return response.json()["csrf_token"]

    def sample_csv(self, *, duplicate_size: bool = False, bad_location: bool = False) -> bytes:
        output = io.StringIO(newline="")
        writer = csv.writer(output)
        writer.writerow(FIELDS)
        for index in range(10):
            writer.writerow(["XM-001", "=HYPERLINK(\"bad\")", "SET-0001", "A-01-1", f"M-{index + 1:06d}", str(36 if duplicate_size and index == 9 else 36 + index), "READY", "NOT-FOUND" if bad_location and index == 2 else "A-01-1", ""])
        return output.getvalue().encode("utf-8")

    def preview(self, raw: bytes):
        return self.admin.post("/api/imports/preview", content=raw, headers={"X-CSRF-Token": self.admin_csrf, "Content-Type": "text/csv"})

    def test_preview_commit_idempotency_initialization_and_safe_export(self) -> None:
        template = self.admin.get("/api/imports/template")
        self.assertEqual(template.status_code, 200, template.text)
        self.assertTrue(template.content.startswith(b"\xef\xbb\xbf"))
        raw = self.sample_csv()
        preview = self.preview(raw)
        self.assertEqual(preview.status_code, 200, preview.text)
        self.assertTrue(preview.json()["valid"], preview.text)
        self.assertEqual((preview.json()["row_count"], preview.json()["set_count"]), (10, 1))
        with self.factory() as db:
            self.assertEqual(db.scalar(select(func.count()).select_from(Mold)), 0)
            self.assertEqual(db.scalar(select(func.count()).select_from(ImportBatch)), 1)
        payload = {"token": preview.json()["token"], "sha256": preview.json()["sha256"]}
        committed = self.admin.post("/api/imports/commit", json=payload, headers={"X-CSRF-Token": self.admin_csrf})
        self.assertEqual(committed.status_code, 200, committed.text)
        self.assertEqual(committed.json()["mold_count"], 10)
        repeated = self.admin.post("/api/imports/commit", json=payload, headers={"X-CSRF-Token": self.admin_csrf})
        self.assertEqual(repeated.status_code, 200, repeated.text)
        self.assertEqual(repeated.json(), committed.json())
        with self.factory() as db:
            self.assertEqual(db.scalar(select(func.count()).select_from(Mold)), 10)
            self.assertEqual(db.scalar(select(func.count()).select_from(Operation)), 1)
            first = db.scalar(select(OperationItem).order_by(OperationItem.id))
            self.assertEqual((first.before_status, first.before_location_id, first.before_version, first.after_version), ("NOT_REGISTERED", None, 0, 1))
        inventory = self.admin.get("/api/exports/inventory")
        self.assertEqual(inventory.status_code, 200)
        self.assertIn("'=HYPERLINK", inventory.content.decode("utf-8-sig"))
        operations = self.admin.get("/api/exports/operations")
        exported_rows = list(csv.reader(io.StringIO(operations.content.decode("utf-8-sig"))))
        self.assertEqual(len(exported_rows), 11)
        self.assertEqual(exported_rows[1][3], "INITIALIZE")
        self.assertRegex(exported_rows[1][2], r"\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}")
        self.login(self.worker, "worker", "ImportWorkerPass-123")
        self.assertEqual(len(list(csv.reader(io.StringIO(self.worker.get("/api/exports/operations").content.decode("utf-8-sig"))))), 1)
        self.login(self.viewer, "viewer", "ImportViewerPass-123")
        self.assertEqual(self.viewer.get("/api/exports/inventory").status_code, 403)

    def test_import_rejects_shelf_over_capacity_in_preview_and_commit(self) -> None:
        raw = self.sample_csv()
        first = self.preview(raw).json()
        self.assertTrue(first["valid"])
        with self.factory() as db:
            shelf_id = db.scalar(select(Location.id).where(Location.code == "A-01-1"))
            model = MoldModel(code="XM-001", name='=HYPERLINK("bad")')
            db.add(model)
            db.flush()
            mold_set = MoldSet(code="SET-OTHER", model_id=model.id, default_location_id=shelf_id)
            db.add(mold_set)
            db.flush()
            db.add(Mold(code="M-OTHER", set_id=mold_set.id, size_label="35", status="READY", current_location_id=shelf_id, version=1))
            db.commit()
        stale_commit = self.admin.post("/api/imports/commit", json={"token": first["token"], "sha256": first["sha256"]}, headers={"X-CSRF-Token": self.admin_csrf})
        self.assertEqual(stale_commit.status_code, 409, stale_commit.text)
        self.assertEqual(self.preview(raw).json()["valid"], False)
        with self.factory() as db:
            self.assertEqual(db.scalar(select(func.count()).select_from(Mold)), 1)

    def test_row_errors_and_changed_database_reject_entire_batch(self) -> None:
        invalid = self.preview(self.sample_csv(duplicate_size=True, bad_location=True))
        self.assertEqual(invalid.status_code, 200, invalid.text)
        self.assertFalse(invalid.json()["valid"])
        self.assertIn("size_label", {item["field"] for item in invalid.json()["errors"]})
        self.assertIn("current_location_code", {item["field"] for item in invalid.json()["errors"]})
        with self.factory() as db:
            self.assertEqual(db.scalar(select(func.count()).select_from(ImportBatch)), 0)
        preview = self.preview(self.sample_csv()).json()
        with self.factory() as db:
            model = MoldModel(code="XM-001", name='=HYPERLINK("bad")')
            db.add(model)
            db.flush()
            shelf_id = db.scalar(select(Location.id).where(Location.code == "A-01-1"))
            db.add(MoldSet(code="SET-0001", model_id=model.id, default_location_id=shelf_id))
            db.commit()
        rejected = self.admin.post("/api/imports/commit", json={"token": preview["token"], "sha256": preview["sha256"]}, headers={"X-CSRF-Token": self.admin_csrf})
        self.assertEqual(rejected.status_code, 409, rejected.text)
        with self.factory() as db:
            self.assertEqual(db.scalar(select(func.count()).select_from(Mold)), 0)

    def test_frozen_location_rejected_in_preview(self) -> None:
        with self.factory() as db:
            shelf_id = db.scalar(select(Location.id).where(Location.code == "A-01-1"))
            admin_id = db.scalar(select(User.id).where(User.username == "admin"))
            db.add(StocktakeSession(location_id=shelf_id, status="ACTIVE", created_by_user_id=admin_id))
            db.commit()
        preview = self.preview(self.sample_csv())
        self.assertFalse(preview.json()["valid"])
        self.assertTrue(any("正在盘点" in item["message"] for item in preview.json()["errors"]))

    def test_label_preview_and_reprint_record_keep_identity(self) -> None:
        preview = self.preview(self.sample_csv()).json()
        self.admin.post("/api/imports/commit", json={"token": preview["token"], "sha256": preview["sha256"]}, headers={"X-CSRF-Token": self.admin_csrf})
        selection = {"kind": "MOLD", "codes": ["M-000001", "M-000002"]}
        labels = self.admin.post("/api/labels/preview", json=selection)
        self.assertEqual(labels.status_code, 200, labels.text)
        self.assertEqual([item["qr_content"] for item in labels.json()["labels"]], ["MOLD:M-000001", "MOLD:M-000002"])
        self.assertEqual(self.admin.post("/api/labels/preview", json={"kind": "LOCATION", "codes": ["A-01-1"]}).json()["labels"][0]["qr_content"], "LOC:A-01-1")
        request = {**selection, "request_id": "d3c417a0-8dd8-497d-8416-8985529d0060", "purpose": "REPRINT", "reason": "标签磨损"}
        headers = {"X-CSRF-Token": self.admin_csrf}
        first = self.admin.post("/api/labels/print-record", json=request, headers=headers)
        self.assertEqual(first.status_code, 200, first.text)
        self.assertEqual(self.admin.post("/api/labels/print-record", json=request, headers=headers).json(), first.json())
        self.assertEqual(self.admin.post("/api/labels/print-record", json={**request, "reason": "标签遗失"}, headers=headers).status_code, 409)
        self.assertEqual(self.admin.post("/api/labels/print-record", json={**request, "request_id": "ad782b54-cb03-45da-b471-5e74ce634276", "reason": ""}, headers=headers).status_code, 422)
        self.assertEqual(self.admin.get("/api/labels/print-records").json()[0]["codes"], selection["codes"])
        with self.factory() as db:
            self.assertEqual(db.scalar(select(func.count()).select_from(LabelPrintBatch)), 1)
            self.assertEqual(db.scalar(select(func.count()).select_from(Mold)), 10)
        self.login(self.worker, "worker", "ImportWorkerPass-123")
        self.assertEqual(self.worker.post("/api/labels/preview", json=selection).status_code, 200)
        self.assertEqual(self.worker.get("/api/labels/print-records").json(), [])
        self.login(self.viewer, "viewer", "ImportViewerPass-123")
        self.assertEqual(self.viewer.post("/api/labels/preview", json=selection).status_code, 403)

    def test_lowercase_mold_code_can_be_printed_and_scanned(self) -> None:
        preview = self.preview(self.sample_csv()).json()
        response = self.admin.post("/api/imports/commit", json={"token": preview["token"], "sha256": preview["sha256"]}, headers={"X-CSRF-Token": self.admin_csrf})
        self.assertEqual(response.status_code, 200, response.text)
        with self.factory() as db:
            mold = db.scalar(select(Mold).where(Mold.code == "M-000001"))
            mold.code = "t1"
            db.commit()

        selection = {"kind": "MOLD", "codes": ["t1"]}
        labels = self.admin.post("/api/labels/preview", json=selection)
        self.assertEqual(labels.status_code, 200, labels.text)
        self.assertEqual(labels.json()["labels"][0]["qr_content"], "MOLD:t1")
        scan = self.admin.post("/api/scan/resolve", json={"raw_code": "MOLD:t1"})
        self.assertEqual(scan.status_code, 200, scan.text)
        self.assertEqual(scan.json()["mold"]["code"], "t1")

        request = {**selection, "request_id": "4e3cd25b-3216-499a-bdd0-ec2ff2490b63", "purpose": "INITIAL"}
        headers = {"X-CSRF-Token": self.admin_csrf}
        first = self.admin.post("/api/labels/print-record", json=request, headers=headers)
        self.assertEqual(first.status_code, 200, first.text)
        retry = self.admin.post("/api/labels/print-record", json=request, headers=headers)
        self.assertEqual(retry.status_code, 200, retry.text)
        self.assertEqual(retry.json(), first.json())


if __name__ == "__main__":
    unittest.main()
