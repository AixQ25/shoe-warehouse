from __future__ import annotations

import csv
import io
import json
import os
import tempfile
import unittest
from pathlib import Path

os.environ.setdefault("DATABASE_URL", "sqlite+pysqlite:///:memory:")

import test_core as core
from alembic import command
from alembic.config import Config
from sqlalchemy import create_engine, select, text

from app.database import make_session_factory
from app.imports_exports import TEMPLATE_FIELDS, REQUIRED
from app.mold_metadata import METADATA_FIELDS, STANDARD_SIZES
from app.models import AuditLog, ImportBatch, Mold, StocktakeSession


EXAMPLE = {"manufacturer": "弘晟", "mold_category": "A模", "pairs_per_mold": 1, "sole_material": "MD", "initial_quarter": "26Q4", "opened_on": "2026.3.16"}


class MoldLabelTest(unittest.TestCase):
    setUp = core.CoreFlowTest.setUp
    tearDown = core.CoreFlowTest.tearDown
    login = core.CoreFlowTest.login

    def headers(self):
        return {"X-CSRF-Token": self.login(self.admin, "admin", "StrongAdminPass-123")}

    def test_create_example_and_preserve_qr_identity(self):
        headers = self.headers()
        new_set = self.admin.post("/api/sets", json={"code": "QD-SET", "model_id": 1, "default_location_id": self.shelf_b}, headers=headers).json()
        result = self.admin.post("/api/molds", json={"code": "QD-264301", "set_id": new_set["id"], "size_label": "42#", "current_location_id": self.shelf_b, **EXAMPLE}, headers=headers)
        self.assertEqual(result.status_code, 200, result.text)
        mold = result.json()
        self.assertEqual(mold["size_label"], "42")
        self.assertEqual(mold["opened_on"], "2026-03-16")
        labels = self.admin.post("/api/labels/preview", json={"kind": "MOLD", "codes": ["QD-264301"]}, headers=headers).json()["labels"]
        self.assertEqual(labels[0]["qr_content"], "MOLD:QD-264301")
        self.assertEqual(labels[0]["manufacturer"], "弘晟")
        scanned = self.admin.post("/api/scan/resolve", json={"raw_code": "mold:qd-264301"}, headers=headers)
        self.assertEqual(scanned.status_code, 200, scanned.text)
        self.assertEqual(scanned.json()["mold"]["id"], mold["id"])
        duplicate = self.admin.post("/api/molds", json={"code": "QD-264302", "set_id": new_set["id"], "size_label": "42", "current_location_id": self.shelf_b}, headers=headers)
        self.assertEqual(duplicate.status_code, 409)

    def test_metadata_update_audit_version_and_permissions(self):
        headers = self.headers()
        before = self.admin.get("/api/molds/1").json()
        payload = {**EXAMPLE, "initial_quarter": " 26q4 ", "expected_version": before["version"], "reason": "补录标签资料"}
        updated = self.admin.patch("/api/molds/1/metadata", json=payload, headers=headers)
        self.assertEqual(updated.status_code, 200, updated.text)
        self.assertEqual(updated.json()["version"], before["version"] + 1)
        self.assertEqual(updated.json()["initial_quarter"], "26Q4")
        for field in ("code", "size_label", "current_location_id", "status", "custodian_person_id"):
            self.assertEqual(updated.json()[field], before[field])
        self.assertEqual(self.admin.patch("/api/molds/1/metadata", json=payload, headers=headers).status_code, 409)
        with self.factory() as db:
            audit = db.scalar(select(AuditLog).where(AuditLog.action == "MOLD_METADATA"))
            self.assertEqual(json.loads(audit.after)["manufacturer"], "弘晟")
            self.assertIsNone(json.loads(audit.before)["manufacturer"])
        worker_csrf = self.login(self.worker, "zhangsan", "StrongWorkerPass-123")
        self.assertEqual(self.worker.patch("/api/molds/1/metadata", json={**payload, "expected_version": 2}, headers={"X-CSRF-Token": worker_csrf}).status_code, 403)
        cleared = self.admin.patch("/api/molds/1/metadata", json={"manufacturer": None, "expected_version": 2, "reason": "纠正厂家资料"}, headers=headers)
        self.assertEqual(cleared.status_code, 200, cleared.text)
        self.assertIsNone(cleared.json()["manufacturer"])
        self.assertEqual(cleared.json()["sole_material"], "MD")

    def test_validation_and_frozen_stocktake(self):
        headers = self.headers()
        for fields in ({"pairs_per_mold": 0}, {"pairs_per_mold": 1.5}, {"pairs_per_mold": True}, {"initial_quarter": "26Q5"}, {"opened_on": "2026.2.30"}, {"opened_on": "2026-03-16T00:00:00"}, {"manufacturer": "弘晟\n其他文字"}, {"code": "改号"}, {"reason": "   "}):
            with self.subTest(fields=fields):
                result = self.admin.patch("/api/molds/1/metadata", json={"expected_version": 1, "reason": "资料校验测试", **fields}, headers=headers)
                self.assertEqual(result.status_code, 422, result.text)
        with self.factory() as db:
            db.add(StocktakeSession(location_id=self.shelf_a, status="ACTIVE", created_by_user_id=1))
            db.commit()
        frozen = self.admin.patch("/api/molds/1/metadata", json={**EXAMPLE, "expected_version": 1, "reason": "补录标签资料"}, headers=headers)
        self.assertEqual(frozen.status_code, 409, frozen.text)
        self.assertEqual(self.admin.get("/api/molds/1").json()["version"], 1)

    def test_old_label_and_old_csv_remain_supported(self):
        headers = self.headers()
        labels = self.admin.post("/api/labels/preview", json={"kind": "MOLD", "codes": ["M-000001"]}, headers=headers).json()["labels"]
        self.assertEqual(labels[0]["qr_content"], "MOLD:M-000001")
        self.assertIsNone(labels[0]["manufacturer"])
        self.assertIsNone(labels[0]["pairs_per_mold"])
        output = io.StringIO(newline="")
        writer = csv.DictWriter(output, fieldnames=REQUIRED + ("original_code",))
        writer.writeheader()
        for index in range(10):
            writer.writerow(dict(zip(REQUIRED, ["NEW-MODEL", "新型号", "NEW-SET", "A-01-2", f"NEW-{index}", str(36 + index), "READY", "A-01-2"])))
        preview = self.admin.post("/api/imports/preview", content=output.getvalue().encode(), headers={**headers, "Content-Type": "text/csv"})
        self.assertTrue(preview.json()["valid"], preview.text)
        # A preview saved by the previous release has none of the new keys.
        with self.factory() as db:
            batch = db.scalar(select(ImportBatch).where(ImportBatch.token == preview.json()["token"]))
            rows = json.loads(batch.payload_json)
            for row in rows:
                for field in METADATA_FIELDS:
                    row.pop(field, None)
            batch.payload_json = json.dumps(rows, ensure_ascii=False)
            db.commit()
        committed = self.admin.post("/api/imports/commit", json={"token": preview.json()["token"], "sha256": preview.json()["sha256"]}, headers=headers)
        self.assertEqual(committed.status_code, 200, committed.text)

    def test_metadata_csv_roundtrip_and_validation(self):
        headers = self.headers()
        def csv_bytes(pairs="1"):
            output = io.StringIO(newline="")
            writer = csv.DictWriter(output, fieldnames=TEMPLATE_FIELDS)
            writer.writeheader()
            for size in STANDARD_SIZES:
                writer.writerow({"mold_number": "QD-264301", "size_label": size, "default_location_code": "A-01-2", "status": "READY", "current_location_code": "A-01-2", **EXAMPLE, "pairs_per_mold": pairs})
            return output.getvalue().encode()
        bad = self.admin.post("/api/imports/preview", content=csv_bytes("一模一双"), headers={**headers, "Content-Type": "text/csv"})
        self.assertFalse(bad.json()["valid"])
        self.assertTrue(any(item["field"] == "pairs_per_mold" for item in bad.json()["errors"]))
        preview = self.admin.post("/api/imports/preview", content=csv_bytes(), headers={**headers, "Content-Type": "text/csv"})
        self.assertTrue(preview.json()["valid"], preview.text)
        commit = self.admin.post("/api/imports/commit", json={"token": preview.json()["token"], "sha256": preview.json()["sha256"]}, headers=headers)
        self.assertEqual(commit.status_code, 200, commit.text)
        rows = list(csv.DictReader(io.StringIO(self.admin.get("/api/exports/inventory").content.decode("utf-8-sig"))))
        mold = next(item for item in rows if item["单件身份编号"] == "QD-264301-A-39")
        self.assertEqual((mold["模具厂家"], mold["排模双数"], mold["开制日期"]), ("弘晟", "1", "2026-03-16"))


class LabelMigrationTest(unittest.TestCase):
    def test_upgrade_preserves_old_mold_and_downgrade_protects_metadata(self):
        project = Path(__file__).resolve().parents[1]
        with tempfile.TemporaryDirectory(prefix="mold-label-migration-") as directory:
            prior_url = os.environ.get("DATABASE_URL")
            os.environ["DATABASE_URL"] = "sqlite+pysqlite:///" + (Path(directory) / "test.sqlite3").as_posix()
            config = Config(str(project / "alembic.ini"))
            config.set_main_option("script_location", str(project / "migrations"))
            engine = None
            try:
                command.upgrade(config, "a42c7e9d105b")
                engine = create_engine(os.environ["DATABASE_URL"])
                with engine.begin() as connection:
                    connection.execute(text("INSERT INTO locations (id, code, name, type, active) VALUES (1, 'A-01-1', '测试库位', 'SHELF', 1)"))
                    connection.execute(text("INSERT INTO mold_models (id, code, name) VALUES (1, 'OLD', '旧型号')"))
                    connection.execute(text("INSERT INTO mold_sets (id, code, model_id, default_location_id, active) VALUES (1, 'OLD-SET', 1, 1, 1)"))
                    connection.execute(text("INSERT INTO molds (id, code, set_id, size_label, status, current_location_id, is_current, version) VALUES (1, 'OLD-001', 1, '42#', 'READY', 1, 1, 7)"))
                    connection.execute(text("INSERT INTO users (id, username, password_hash, role, active) VALUES (1, 'migration-test', 'isolated-test-placeholder', 'ADMIN', 1)"))
                    connection.execute(text("INSERT INTO operations (id, request_id, payload_hash, type, actor_user_id, target_location_id, created_at) VALUES (1, 'old-request', 'old-hash', 'MOVE', 1, 1, '2026-03-16 12:00:00')"))
                    connection.execute(text("INSERT INTO operation_items (id, operation_id, mold_id, before_status, after_status, before_location_id, after_location_id, before_version, after_version) VALUES (1, 1, 1, 'READY', 'READY', 1, 1, 6, 7)"))
                command.upgrade(config, "head")
                with make_session_factory(engine)() as db:
                    mold = db.get(Mold, 1)
                    self.assertEqual((mold.code, mold.size_label, mold.version, mold.current_location_id), ("OLD-001", "42#", 7, 1))
                    self.assertIsNone(mold.manufacturer)
                    self.assertEqual(db.execute(text("SELECT before_version, after_version FROM operation_items WHERE mold_id=1")).one(), (6, 7))
                command.downgrade(config, "a42c7e9d105b")
                command.upgrade(config, "head")
                with make_session_factory(engine)() as db:
                    db.get(Mold, 1).manufacturer = "弘晟"
                    db.commit()
                with self.assertRaisesRegex(RuntimeError, "不能直接回退"):
                    command.downgrade(config, "a42c7e9d105b")
            finally:
                if engine is not None:
                    engine.dispose()
                if prior_url is None:
                    os.environ.pop("DATABASE_URL", None)
                else:
                    os.environ["DATABASE_URL"] = prior_url
