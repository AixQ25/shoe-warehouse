from __future__ import annotations

import os
import sqlite3
import tempfile
import threading
import unittest
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from unittest.mock import patch
from uuid import uuid4

os.environ.setdefault("DATABASE_URL", "sqlite+pysqlite:///:memory:")

import test_core as fixtures
from fastapi.testclient import TestClient
from sqlalchemy import event, func, select

from app import operations
from app.database import make_engine, make_session_factory
from app.main import create_app
from app.models import Mold, MoldModel, MoldSet, StocktakeSession


class ReviewRegressionTest(unittest.TestCase):
    def setUp(self) -> None:
        self.fixture = fixtures.CoreFlowTest()
        self.fixture.setUp()
        self.csrf = self.fixture.login(self.fixture.worker, "zhangsan", "StrongWorkerPass-123")
        admin_csrf = self.fixture.login(self.fixture.admin, "admin", "StrongAdminPass-123")
        device = self.fixture.worker.post("/api/devices/register", json={"label": "并发回归测试"}, headers={"X-CSRF-Token": self.csrf}).json()
        self.fixture.admin.post(f"/api/devices/{device['id']}/authorize", headers={"X-CSRF-Token": admin_csrf})
        self.directory = tempfile.TemporaryDirectory(prefix="warehouse-regression-")
        path = Path(self.directory.name) / "test.sqlite3"
        raw = self.fixture.engine.raw_connection()
        try:
            with sqlite3.connect(path) as target:
                raw.driver_connection.backup(target)
        finally:
            raw.close()
        self.engine = make_engine("sqlite+pysqlite:///" + path.as_posix())
        self.factory = make_session_factory(self.engine)
        self.app = create_app(self.engine)
        self.clients = [TestClient(self.app), TestClient(self.app)]
        for client in self.clients:
            client.cookies.update(self.fixture.worker.cookies)

    def tearDown(self) -> None:
        for client in self.clients:
            client.close()
        self.engine.dispose()
        self.directory.cleanup()
        self.fixture.tearDown()

    def move(self, client, mold_id, target, request_id=None):
        return client.post("/api/operations", json={"request_id": request_id or str(uuid4()), "type": "MOVE", "target_location_id": target, "items": [{"mold_id": mold_id, "expected_version": 1}]}, headers={"X-CSRF-Token": self.csrf})

    def test_concurrent_distinct_molds_cannot_overfill_shelf(self) -> None:
        with self.factory() as db:
            model = MoldModel(code="EXTRA", name="额外测试套")
            db.add(model)
            db.flush()
            group = MoldSet(code="EXTRA", model_id=model.id, default_location_id=self.fixture.shelf_b)
            db.add(group)
            db.flush()
            for index in range(9):
                db.add(Mold(code=f"EXTRA-{index}", set_id=group.id, size_label=str(index), status="READY", current_location_id=self.fixture.shelf_b))
            db.commit()
        checked, release, second_validated = threading.Event(), threading.Event(), threading.Event()
        original = operations.ensure_shelf_capacity

        def pause_after_check(*args, **kwargs):
            original(*args, **kwargs)
            if not checked.is_set():
                checked.set()
                if not release.wait(5):
                    raise AssertionError("测试未释放首个请求")
            else:
                second_validated.set()

        with patch.object(operations, "ensure_shelf_capacity", pause_after_check), ThreadPoolExecutor(2) as pool:
            first = pool.submit(self.move, self.clients[0], 1, self.fixture.shelf_b)
            self.assertTrue(checked.wait(5))
            second = pool.submit(self.move, self.clients[1], 2, self.fixture.shelf_b)
            try:
                self.assertFalse(second_validated.wait(0.2))
            finally:
                release.set()
            results = [first.result(timeout=5), second.result(timeout=5)]
        self.assertEqual([item.status_code for item in results], [200, 409])
        self.assertEqual(results[1].json()["detail"]["error_code"], "LOCATION_FULL")
        with self.factory() as db:
            self.assertEqual(db.scalar(select(func.count(Mold.id)).where(Mold.current_location_id == self.fixture.shelf_b)), 10)

    def test_stocktake_snapshot_waits_for_in_flight_movement(self) -> None:
        checked, release = threading.Event(), threading.Event()
        original = operations.ensure_shelf_capacity

        def pause_after_check(*args, **kwargs):
            original(*args, **kwargs)
            checked.set()
            if not release.wait(5):
                raise AssertionError("测试未释放流转请求")

        with patch.object(operations, "ensure_shelf_capacity", pause_after_check), ThreadPoolExecutor(2) as pool:
            movement = pool.submit(self.move, self.clients[0], 1, self.fixture.shelf_b)
            self.assertTrue(checked.wait(5))
            stocktake = pool.submit(self.clients[1].post, "/api/stocktakes", json={"location_id": self.fixture.shelf_a}, headers={"X-CSRF-Token": self.csrf})
            try:
                with self.assertRaises(TimeoutError):
                    stocktake.result(timeout=0.2)
            finally:
                release.set()
            self.assertEqual(movement.result(timeout=5).status_code, 200)
            response = stocktake.result(timeout=5)
        self.assertEqual(response.status_code, 200, response.text)
        self.assertNotIn(1, [item["mold_id"] for item in response.json()["expected"]])
        frozen = self.move(self.clients[0], 2, self.fixture.shelf_b)
        self.assertEqual(frozen.status_code, 409)
        self.assertEqual(frozen.json()["detail"]["error_code"], "LOCATION_STOCKTAKE_FROZEN")

    def test_concurrent_same_request_returns_one_document(self) -> None:
        request_id = str(uuid4())
        with ThreadPoolExecutor(2) as pool:
            results = list(pool.map(lambda client: self.move(client, 1, self.fixture.shelf_b, request_id), self.clients))
        self.assertEqual([item.status_code for item in results], [200, 200])
        self.assertEqual(results[0].json()["id"], results[1].json()["id"])
        with self.factory() as db:
            self.assertEqual(db.get(Mold, 1).version, 2)

    def test_busy_database_returns_retryable_response_without_mutation(self) -> None:
        @event.listens_for(self.engine, "connect")
        def short_wait(connection, _record):
            connection.execute("PRAGMA busy_timeout=30")

        with self.engine.connect() as connection:
            connection.exec_driver_sql("BEGIN IMMEDIATE")
            response = self.move(self.clients[0], 1, self.fixture.shelf_b)
            connection.rollback()
        self.assertEqual(response.status_code, 503)
        self.assertEqual(response.headers["retry-after"], "1")
        self.assertEqual(response.json()["detail"]["error_code"], "DATABASE_BUSY")
        with self.factory() as db:
            self.assertEqual(db.get(Mold, 1).version, 1)

    def test_lowercase_stocktake_scan_matches_existing_mold(self) -> None:
        with self.factory() as db:
            db.get(Mold, 1).code = "m-lower"
            db.commit()
        headers = {"X-CSRF-Token": self.csrf}
        session = self.clients[0].post("/api/stocktakes", json={"location_id": self.fixture.shelf_a}, headers=headers).json()
        path = f"/api/stocktakes/{session['id']}/scan"
        self.clients[0].post(path, json={"raw_code": "LOC:A-01-1"}, headers=headers)
        response = self.clients[0].post(path, json={"raw_code": "MOLD:m-lower"}, headers=headers)
        self.assertEqual(response.json()["result"], "EXPECTED")
        self.assertNotIn("m-lower", response.json()["stocktake"]["missing_codes"])

    def test_old_open_stocktake_remains_visible(self) -> None:
        response = self.clients[0].post("/api/stocktakes", json={"location_id": self.fixture.shelf_a}, headers={"X-CSRF-Token": self.csrf})
        with self.factory() as db:
            for _ in range(50):
                db.add(StocktakeSession(location_id=self.fixture.shelf_b, status="CANCELLED", created_by_user_id=2))
            db.commit()
        listed = self.clients[0].get("/api/stocktakes").json()
        self.assertIn(response.json()["id"], [item["id"] for item in listed])

    def test_https_login_and_device_cookies_are_secure(self) -> None:
        with TestClient(self.app, base_url="https://testserver") as client:
            login = client.post("/api/auth/login", json={"username": "zhangsan", "password": "StrongWorkerPass-123"})
            self.assertEqual(login.status_code, 200)
            self.assertTrue(all("; Secure" in value for value in login.headers.get_list("set-cookie")))
            device = client.post("/api/devices/register", json={"label": "HTTPS"}, headers={"X-CSRF-Token": login.json()["csrf_token"]})
            self.assertEqual(device.status_code, 200)
            self.assertIn("; Secure", device.headers["set-cookie"])
