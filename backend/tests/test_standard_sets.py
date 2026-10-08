from __future__ import annotations

import csv
import io
import os
import unittest

os.environ.setdefault("DATABASE_URL", "sqlite+pysqlite:///:memory:")

import test_core as core
from sqlalchemy import func, select

from app.imports_exports import TEMPLATE_FIELDS
from app.mold_metadata import STANDARD_SIZES, standard_size
from app.models import Location, Mold, MoldModel, MoldSet, Operation, OperationItem, StocktakeSession


class StandardSetTest(unittest.TestCase):
    setUp = core.CoreFlowTest.setUp
    tearDown = core.CoreFlowTest.tearDown
    login = core.CoreFlowTest.login

    def headers(self):
        return {"X-CSRF-Token": self.login(self.admin, "admin", "StrongAdminPass-123")}

    def create(self, headers, category="A模", location=None, number="QD-264301"):
        return self.admin.post("/api/mold-sets", json={"mold_number": number, "mold_category": category, "default_location_id": location or self.shelf_b, "manufacturer": "弘晟", "pairs_per_mold": 1, "sole_material": "MD", "opened_on": "2026.3.16", "initial_quarter": "26Q4"}, headers=headers)

    def test_one_form_creates_ten_sizes_and_initialization_atomically(self):
        headers = self.headers()
        result = self.create(headers, number=" qd-264301 ")
        self.assertEqual(result.status_code, 200, result.text)
        self.assertEqual(result.json()["sizes"], list(STANDARD_SIZES))
        page = self.admin.get("/api/molds?q=QD-264301").json()
        self.assertEqual(page["total"], 10)
        self.assertEqual({item["size_label"] for item in page["items"]}, set(STANDARD_SIZES))
        self.assertTrue(all(item["mold_number"] == "QD-264301" and item["mold_category"] == "A模" and item["manufacturer"] == "弘晟" for item in page["items"]))
        with self.factory() as db:
            operation = db.scalar(select(Operation).where(Operation.type == "INITIALIZE"))
            self.assertEqual(len(operation.items), 10)
            self.assertTrue(all(item.before_status == "NOT_REGISTERED" and item.after_version == 1 for item in operation.items))
        self.assertEqual(self.admin.get("/api/molds?q=A模").json()["total"], 10)

    def test_a_b_and_half_sizes_have_distinct_qrs_and_duplicate_set_is_rejected(self):
        headers = self.headers()
        self.assertEqual(self.create(headers).status_code, 200)
        with self.factory() as db:
            shelf = Location(code="B-01-1", name="测试库位", type="SHELF")
            db.add(shelf); db.commit(); shelf_id = shelf.id
        self.assertEqual(self.create(headers, "B", shelf_id).status_code, 200)
        duplicate = self.create(headers)
        self.assertEqual(duplicate.status_code, 409, duplicate.text)
        codes = ["QD-264301-A-40", "QD-264301-A-40.5", "QD-264301-B-40.5"]
        labels = self.admin.post("/api/labels/preview", json={"kind": "MOLD", "codes": codes}, headers=headers).json()["labels"]
        self.assertEqual({item["mold_number"] for item in labels}, {"QD-264301"})
        self.assertEqual({item["qr_content"] for item in labels}, {"MOLD:" + code for code in codes})
        ids = {self.admin.post("/api/scan/resolve", json={"raw_code": "mold:" + code.lower()}, headers=headers).json()["mold"]["id"] for code in codes}
        self.assertEqual(len(ids), 3)
        self.assertEqual(self.admin.get("/api/molds?q=QD-264301").json()["total"], 20)

    def test_full_or_frozen_location_leaves_no_partial_model_or_set(self):
        headers = self.headers()
        self.assertEqual(self.create(headers, location=self.shelf_a).status_code, 409)
        with self.factory() as db:
            self.assertIsNone(db.scalar(select(MoldModel.id).where(MoldModel.code == "QD-264301")))
            self.assertEqual(db.scalar(select(func.count()).select_from(Mold)), 10)
            self.assertEqual(db.scalar(select(func.count()).select_from(Operation)), 0)
            db.add(StocktakeSession(location_id=self.shelf_b, status="ACTIVE", created_by_user_id=1)); db.commit()
        self.assertEqual(self.create(headers).status_code, 409)
        with self.factory() as db:
            self.assertEqual(db.scalar(select(func.count()).select_from(MoldSet)), 1)
            self.assertIsNone(db.scalar(select(MoldModel.id).where(MoldModel.code == "QD-264301")))

    def test_category_is_set_identity_and_cannot_be_changed_on_one_mold(self):
        headers = self.headers()
        self.assertEqual(self.create(headers).status_code, 200)
        mold = self.admin.get("/api/molds?q=QD-264301-A-42.5").json()["items"][0]
        for category in ("B模", None):
            result = self.admin.patch(f"/api/molds/{mold['id']}/metadata", json={"expected_version": 1, "reason": "测试修改类别", "mold_category": category}, headers=headers)
            self.assertEqual(result.status_code, 422, result.text)
        result = self.admin.patch(f"/api/molds/{mold['id']}/metadata", json={"expected_version": 1, "reason": "补录厂家资料", "manufacturer": "新厂家"}, headers=headers)
        self.assertEqual(result.status_code, 200, result.text)
        self.assertEqual(result.json()["mold_category"], "A模")
        for category in ("C模", None):
            self.assertEqual(self.create(headers, category).status_code, 422)
        worker_headers = {"X-CSRF-Token": self.login(self.worker, "zhangsan", "StrongWorkerPass-123")}
        self.assertEqual(self.worker.post("/api/mold-sets", json={"mold_number": "X", "default_location_id": self.shelf_b}, headers=worker_headers).status_code, 403)

    def csv_bytes(self, sizes=STANDARD_SIZES):
        output = io.StringIO(newline="")
        writer = csv.DictWriter(output, fieldnames=TEMPLATE_FIELDS)
        writer.writeheader()
        for size in sizes:
            writer.writerow({"mold_number": "QD-264301", "mold_category": "A模", "size_label": size, "status": "READY", "current_location_code": "A-01-2", "default_location_code": "A-01-2"})
        return output.getvalue().encode()

    def test_new_csv_auto_identity_fixed_sizes_and_idempotent_commit(self):
        headers = self.headers()
        for sizes in (STANDARD_SIZES[:-1], ["38"] + list(STANDARD_SIZES[1:]), list(STANDARD_SIZES[:-1]) + ["42.50"]):
            result = self.admin.post("/api/imports/preview", content=self.csv_bytes(sizes), headers={**headers, "Content-Type": "text/csv"})
            self.assertFalse(result.json()["valid"], result.text)
        preview = self.admin.post("/api/imports/preview", content=self.csv_bytes(), headers={**headers, "Content-Type": "text/csv"}).json()
        self.assertTrue(preview["valid"], preview)
        body = {"token": preview["token"], "sha256": preview["sha256"]}
        first = self.admin.post("/api/imports/commit", json=body, headers=headers)
        self.assertEqual(first.status_code, 200, first.text)
        self.assertEqual(first.json(), self.admin.post("/api/imports/commit", json=body, headers=headers).json())
        self.assertEqual(self.admin.get("/api/molds?q=QD-264301").json()["total"], 10)
        self.assertEqual(self.create(headers).status_code, 409)
        with self.factory() as db:
            self.assertEqual(db.scalar(select(func.count()).select_from(OperationItem)), 10)

    def test_half_sizes_are_canonical_and_huge_or_nonfinite_values_rejected(self):
        self.assertEqual(standard_size("42.50#"), "42.5")
        for size in ("NaN", "Infinity", "1e999999999", "38", "44.75"):
            with self.assertRaises(ValueError):
                standard_size(size)
