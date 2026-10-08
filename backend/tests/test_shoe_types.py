from __future__ import annotations

import csv
import io
import json
import os
import unittest
from uuid import uuid4

os.environ.setdefault("DATABASE_URL", "sqlite+pysqlite:///:memory:")
import test_core as core
from sqlalchemy import select
from app.imports_exports import TEMPLATE_FIELDS
from app.models import Location, Mold, MoldModel, MoldSet, Operation
from app.mold_metadata import SIZE_PRESETS, LITTLE_KIDS_SIZES, numeric_size


class ShoeTypeTest(unittest.TestCase):
    setUp = core.CoreFlowTest.setUp
    tearDown = core.CoreFlowTest.tearDown
    login = core.CoreFlowTest.login

    def headers(self):
        return {"X-CSRF-Token": self.login(self.admin, "admin", "StrongAdminPass-123")}

    def create(self, headers, **changes):
        body = {"mold_number": "TEST", "shoe_type": "女鞋", "mold_category": "A模", "default_location_id": self.shelf_b}
        body.update(changes)
        return self.admin.post("/api/mold-sets", json=body, headers=headers)

    def test_four_classifications_have_distinct_reference_plans(self):
        headers = self.headers()
        for index, (kind, sizes) in enumerate(SIZE_PRESETS.items()):
            location = self.admin.post("/api/locations", json={"type": "SHELF", "zone": "T", "rack": "1", "level": str(index + 1)}, headers=headers).json()["id"]
            response = self.create(headers, mold_number=f"TEST-{index}", shoe_type=kind, default_location_id=location)
            self.assertEqual(response.status_code, 200, response.text)
            self.assertEqual(response.json()["sizes"], list(sizes))
            self.assertEqual(response.json()["created_count"], 10)
            self.assertTrue(response.json()["complete"])
            molds = self.admin.get(f"/api/molds?q=TEST-{index}").json()["items"]
            self.assertTrue(all(item["shoe_type"] == kind for item in molds))
        self.assertEqual(self.admin.get("/api/molds?q=女童").json()["total"], 10)
        self.assertEqual(SIZE_PRESETS["男童"], SIZE_PRESETS["女童"])

    def test_single_then_whole_fills_only_missing_and_retains_existing_metadata(self):
        headers = self.headers()
        first = self.create(headers, mode="SINGLE", size_label="35.50#", manufacturer="原厂家")
        self.assertEqual(first.status_code, 200, first.text)
        self.assertEqual((first.json()["created_count"], first.json()["expected_size_count"], first.json()["complete"]), (1, 10, False))
        self.assertEqual(self.create(headers, mode="SINGLE", size_label="35.5").status_code, 409)
        whole = self.create(headers, manufacturer="补齐厂家")
        self.assertEqual(whole.status_code, 200, whole.text)
        self.assertEqual((whole.json()["created_count"], whole.json()["size_count"], whole.json()["complete"]), (9, 10, True))
        molds = self.admin.get("/api/molds?q=TEST").json()["items"]
        original = next(item for item in molds if item["size_label"] == "35.5")
        self.assertEqual((original["manufacturer"], original["version"]), ("原厂家", 1))
        self.assertTrue(all(item["manufacturer"] == "补齐厂家" for item in molds if item["id"] != original["id"]))
        self.assertEqual(self.create(headers).status_code, 409)
        with self.factory() as db:
            self.assertEqual(sorted(len(op.items) for op in db.scalars(select(Operation)).all()), [1, 9])

    def test_custom_plan_single_locations_and_complete_return_use_plan(self):
        headers = self.headers()
        plan = ["25", "26", "27.5"]
        first = self.create(headers, shoe_type="男童", size_labels=plan, mode="SINGLE", size_label="25")
        self.assertEqual(first.status_code, 200, first.text)
        location = self.admin.post("/api/locations", json={"type": "SHELF", "zone": "T", "rack": "2", "level": "1"}, headers=headers).json()["id"]
        rest = self.create(headers, shoe_type="男童", default_location_id=location)
        self.assertEqual(rest.status_code, 200, rest.text)
        self.assertEqual((rest.json()["created_count"], rest.json()["expected_size_count"], rest.json()["complete"]), (2, 3, True))
        members = self.admin.get("/api/molds?q=TEST").json()["items"]
        self.assertTrue(all(item["default_location_id"] == self.shelf_b for item in members))
        self.assertEqual({item["current_location_id"] for item in members}, {self.shelf_b, location})
        matrix = next(item for item in self.admin.get("/api/set-matrix").json() if item["model_code"] == "TEST")
        self.assertTrue(matrix["complete"])
        self.assertEqual(matrix["expected_size_count"], 3)
        csrf = self.login(self.worker, "zhangsan", "StrongWorkerPass-123")
        worker_headers = {"X-CSRF-Token": csrf}
        device = self.worker.post("/api/devices/register", json={"label": "隔离验证"}, headers=worker_headers).json()["id"]
        self.assertEqual(self.admin.post(f"/api/devices/{device}/authorize", headers=headers).status_code, 200)
        def submit(kind, target, version):
            return self.worker.post("/api/operations", json={"request_id": str(uuid4()), "type": kind, "target_location_id": target, "items": [{"mold_id": item["id"], "expected_version": version} for item in members]}, headers=worker_headers)
        issued = submit("ISSUE", self.line, 1)
        self.assertEqual(issued.status_code, 200, issued.text)
        returned = submit("RETURN", location, 2)
        self.assertEqual(returned.status_code, 200, returned.text)
        self.assertTrue(all(item["default_location_id"] == location for item in self.admin.get("/api/molds?q=TEST").json()["items"]))
        correction = self.admin.post(f"/api/operations/{returned.json()['id']}/corrections", json={"request_id": str(uuid4()), "reason": "验证三码整套归还保护"}, headers=headers)
        self.assertEqual(correction.status_code, 409, correction.text)
        self.assertEqual(correction.json()["detail"]["error_code"], "FULL_SET_RETURN_REVIEW")

    def test_invalid_plan_type_and_capacity_reject_without_partial_write(self):
        headers = self.headers()
        for fields in ({"size_labels": ["35.5", "35.50"]}, {"size_labels": ["35.25"]}, {"shoe_type": "其他"}, {"mode": "SINGLE"}, {"mode": "SINGLE", "size_label": "25"}, {"mold_number": "X" * 73, "size_labels": ["999.5"]}):
            response = self.create(headers, **fields)
            self.assertEqual(response.status_code, 422, response.text)
        response = self.create(headers, size_labels=[str(size) for size in range(20, 31)])
        self.assertEqual(response.status_code, 409, response.text)
        with self.factory() as db:
            self.assertIsNone(db.scalar(select(MoldModel).where(MoldModel.code == "TEST")))
            self.assertEqual(len(db.scalars(select(Mold)).all()), 10)
        self.assertEqual(self.create(headers, mode="SINGLE", size_label="35.5").status_code, 200)
        self.assertEqual(self.create(headers, shoe_type="男童", mold_category="B模").status_code, 409)
        self.assertEqual(self.create(headers, size_labels=["35", "36"]).status_code, 409)
        self.assertEqual(self.create(headers, mode="SINGLE", size_label="36").status_code, 200)

    def test_custom_child_csv_is_complete_and_exports_classification(self):
        headers = self.headers()
        output = io.StringIO(newline="")
        writer = csv.DictWriter(output, fieldnames=TEMPLATE_FIELDS)
        writer.writeheader()
        for size in LITTLE_KIDS_SIZES:
            writer.writerow({"mold_number": "CHILD", "shoe_type": "女童", "mold_category": "B模", "set_sizes": "、".join(LITTLE_KIDS_SIZES), "size_label": size, "status": "READY", "current_location_code": "A-01-2", "default_location_code": "A-01-2"})
        preview = self.admin.post("/api/imports/preview", content=output.getvalue().encode(), headers={**headers, "Content-Type": "text/csv"}).json()
        self.assertTrue(preview["valid"], preview)
        committed = self.admin.post("/api/imports/commit", json={"token": preview["token"], "sha256": preview["sha256"]}, headers=headers)
        self.assertEqual(committed.status_code, 200, committed.text)
        with self.factory() as db:
            mold_set = db.scalar(select(MoldSet).where(MoldSet.code == "CHILD-B"))
            self.assertEqual(json.loads(mold_set.size_labels), list(LITTLE_KIDS_SIZES))
            self.assertEqual(mold_set.model.shoe_type, "女童")
        exported = list(csv.DictReader(io.StringIO(self.admin.get("/api/exports/inventory").content.decode("utf-8-sig"))))
        self.assertEqual({row["鞋类"] for row in exported if row["模具编号（款号）"] == "CHILD"}, {"女童"})
        self.assertEqual(numeric_size("31.50＃"), "31.5")
