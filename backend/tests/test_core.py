from __future__ import annotations

import os
import unittest
from uuid import uuid4

os.environ.setdefault("DATABASE_URL", "sqlite+pysqlite:///:memory:")

from fastapi.testclient import TestClient
from sqlalchemy import create_engine, event, select
from sqlalchemy.pool import StaticPool

from app.auth import hash_password
from app.database import Base, make_session_factory
from app.main import create_app
from app.models import Location, Mold, MoldModel, MoldSet, Operation, Person, StocktakeAdjustment, User


class CoreFlowTest(unittest.TestCase):
    def setUp(self) -> None:
        self.engine = create_engine("sqlite+pysqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)

        @event.listens_for(self.engine, "connect")
        def fk_on(connection, _record):
            connection.execute("PRAGMA foreign_keys=ON")

        Base.metadata.create_all(self.engine)
        self.factory = make_session_factory(self.engine)
        with self.factory() as db:
            admin_person = Person(name="维护员")
            worker_person = Person(name="张三")
            receiver_person = Person(name="李四")
            db.add_all([admin_person, worker_person, receiver_person])
            db.flush()
            db.add_all([
                User(username="admin", password_hash=hash_password("StrongAdminPass-123"), role="ADMIN", person_id=admin_person.id),
                User(username="zhangsan", password_hash=hash_password("StrongWorkerPass-123"), role="WORKER", person_id=worker_person.id),
                User(username="lisi", password_hash=hash_password("StrongReceiverPass-123"), role="WORKER", person_id=receiver_person.id),
                User(username="warehouse-view", password_hash=hash_password("StrongReadonlyPass-123"), role="READONLY"),
            ])
            shelf_a = Location(code="A-01-1", name="A区1号架1层", type="SHELF", zone="A", rack="1", level="1")
            shelf_b = Location(code="A-01-2", name="A区1号架2层", type="SHELF", zone="A", rack="1", level="2")
            line = Location(code="产线01", name="产线01", type="LINE")
            line_two = Location(code="产线02", name="产线02", type="LINE")
            unknown = Location(code="UNKNOWN-01", name="未知位置", type="UNKNOWN")
            inspection = Location(code="INSPECTION-01", name="待检区", type="INSPECTION")
            repair = Location(code="REPAIR-01", name="维修区", type="REPAIR")
            scrap = Location(code="SCRAP-01", name="报废区", type="SCRAP")
            db.add_all([shelf_a, shelf_b, line, line_two, unknown, inspection, repair, scrap])
            db.flush()
            model = MoldModel(code="XM-001", name="测试鞋底")
            db.add(model)
            db.flush()
            mold_set = MoldSet(code="SET-0001", model_id=model.id, default_location_id=shelf_a.id)
            db.add(mold_set)
            db.flush()
            for index in range(10):
                db.add(Mold(code=f"M-{index + 1:06d}", set_id=mold_set.id, size_label=str(36 + index), status="READY", current_location_id=shelf_a.id, version=1))
            db.commit()
            self.shelf_a = shelf_a.id
            self.shelf_b = shelf_b.id
            self.line = line.id
            self.line_two = line_two.id
            self.unknown = unknown.id
            self.inspection = inspection.id
            self.repair = repair.id
            self.scrap = scrap.id
        self.app = create_app(self.engine)
        self.worker = TestClient(self.app)
        self.admin = TestClient(self.app)

    def tearDown(self) -> None:
        self.worker.close()
        self.admin.close()
        self.engine.dispose()

    def login(self, client: TestClient, username: str, password: str) -> str:
        response = client.post("/api/auth/login", json={"username": username, "password": password})
        self.assertEqual(response.status_code, 200, response.text)
        return response.json()["csrf_token"]

    def submit(self, kind: str, target: int, ids: list[int], versions: list[int], csrf: str, request_id: str | None = None):
        return self.worker.post("/api/operations", json={"request_id": request_id or str(uuid4()), "type": kind, "target_location_id": target, "items": [{"mold_id": mold_id, "expected_version": version} for mold_id, version in zip(ids, versions)]}, headers={"X-CSRF-Token": csrf})

    def transition(self, client: TestClient, mold_id: int, action: str, version: int, target: int, csrf: str, found_status: str | None = None, request_id: str | None = None):
        return client.post(f"/api/molds/{mold_id}/transition", json={"request_id": request_id or str(uuid4()), "action": action, "expected_version": version, "target_location_id": target, "reason": "现场核对后办理状态流转", "found_status": found_status}, headers={"X-CSRF-Token": csrf})

    def test_shelf_identity_is_generated_and_other_locations_need_names(self) -> None:
        csrf = self.login(self.admin, "admin", "StrongAdminPass-123")
        headers = {"X-CSRF-Token": csrf}
        created = self.admin.post("/api/locations", json={"type": "SHELF", "zone": " a ", "rack": "01", "level": "3"}, headers=headers)
        self.assertEqual(created.status_code, 200, created.text)
        self.assertEqual(created.json()["code"], "A-01-3")
        location = next(item for item in self.admin.get("/api/locations").json() if item["id"] == created.json()["id"])
        self.assertEqual((location["name"], location["zone"], location["rack"], location["level"]), ("A区1号架3层", "A", "1", "3"))
        duplicate = self.admin.post("/api/locations", json={"type": "SHELF", "zone": "A", "rack": "1", "level": "03"}, headers=headers)
        self.assertEqual(duplicate.status_code, 409)
        missing_name = self.admin.post("/api/locations", json={"type": "LINE", "code": "产线03"}, headers=headers)
        self.assertEqual(missing_name.status_code, 422)

    def test_unused_location_can_be_deleted_but_referenced_location_cannot(self) -> None:
        admin_csrf = self.login(self.admin, "admin", "StrongAdminPass-123")
        worker_csrf = self.login(self.worker, "zhangsan", "StrongWorkerPass-123")
        headers = {"X-CSRF-Token": admin_csrf}
        created = self.admin.post("/api/locations", json={"type": "SHELF", "zone": "B", "rack": "1", "level": "1"}, headers=headers)
        self.assertEqual(created.status_code, 200, created.text)
        location_id = created.json()["id"]
        self.assertEqual(self.worker.delete(f"/api/locations/{location_id}", headers={"X-CSRF-Token": worker_csrf}).status_code, 403)
        self.assertEqual(self.admin.delete(f"/api/locations/{self.shelf_a}", headers=headers).status_code, 409)
        self.assertEqual(self.admin.delete("/api/locations/999999", headers=headers).status_code, 404)

        with self.factory() as db:
            mold = db.scalar(select(Mold).order_by(Mold.id))
            assert mold is not None
            mold.current_location_id = location_id
            db.commit()
        self.assertEqual(self.admin.delete(f"/api/locations/{location_id}", headers=headers).status_code, 409)

        with self.factory() as db:
            mold = db.scalar(select(Mold).order_by(Mold.id))
            assert mold is not None
            mold.current_location_id = self.shelf_a
            actor = db.scalar(select(User).where(User.username == "admin"))
            assert actor is not None
            operation = Operation(request_id=str(uuid4()), payload_hash="location-delete-test", type="MOVE", actor_user_id=actor.id, target_location_id=location_id)
            db.add(operation)
            db.commit()
            operation_id = operation.id
        self.assertEqual(self.admin.delete(f"/api/locations/{location_id}", headers=headers).status_code, 409)

        with self.factory() as db:
            db.delete(db.get(Operation, operation_id))
            db.commit()
        deleted = self.admin.delete(f"/api/locations/{location_id}", headers=headers)
        self.assertEqual(deleted.status_code, 200, deleted.text)
        self.assertFalse(any(item["id"] == location_id for item in self.admin.get("/api/locations").json()))
        recreated = self.admin.post("/api/locations", json={"type": "SHELF", "zone": "B", "rack": "1", "level": "1"}, headers=headers)
        self.assertEqual(recreated.status_code, 200, recreated.text)

    def test_new_basic_records_can_be_deleted_in_dependency_order(self) -> None:
        csrf = self.login(self.admin, "admin", "StrongAdminPass-123")
        headers = {"X-CSRF-Token": csrf}
        person = self.admin.post("/api/people", json={"name": "误录人员", "employee_code": "ERR-01"}, headers=headers)
        self.assertEqual(person.status_code, 200, person.text)
        account = self.admin.post("/api/auth/users", json={"username": "wrong-account", "password": "StrongWrongPass-123", "role": "WORKER", "person_id": person.json()["id"]}, headers=headers)
        self.assertEqual(account.status_code, 200, account.text)
        worker_csrf = self.login(self.worker, "wrong-account", "StrongWrongPass-123")
        self.assertEqual(self.worker.post("/api/devices/register", json={"label": "误录账号设备"}, headers={"X-CSRF-Token": worker_csrf}).status_code, 200)
        self.assertEqual(self.admin.delete(f"/api/people/{person.json()['id']}", headers=headers).status_code, 409)
        self.assertEqual(self.admin.delete(f"/api/auth/users/{account.json()['id']}", headers=headers).status_code, 200)
        self.assertEqual(self.worker.get("/api/auth/me").status_code, 401)
        self.assertEqual(self.admin.delete(f"/api/people/{person.json()['id']}", headers=headers).status_code, 200)
        self.assertEqual(self.admin.delete(f"/api/auth/users/{self.admin.get('/api/auth/me').json()['id']}", headers=headers).status_code, 409)

        model = self.admin.post("/api/models", json={"code": "WRONG-MODEL", "name": "误录型号"}, headers=headers)
        self.assertEqual(model.status_code, 200, model.text)
        mold_set = self.admin.post("/api/sets", json={"code": "WRONG-SET", "model_id": model.json()["id"], "default_location_id": self.shelf_b}, headers=headers)
        self.assertEqual(mold_set.status_code, 200, mold_set.text)
        self.assertEqual(self.admin.delete(f"/api/models/{model.json()['id']}", headers=headers).status_code, 409)
        self.assertEqual(self.admin.delete(f"/api/sets/{mold_set.json()['id']}", headers=headers).status_code, 200)
        self.assertEqual(self.admin.delete(f"/api/models/{model.json()['id']}", headers=headers).status_code, 200)
        self.assertEqual(self.admin.post("/api/models", json={"code": "WRONG-MODEL", "name": "改正型号"}, headers=headers).status_code, 200)

        device = self.admin.post("/api/devices/register", json={"label": "误录设备"}, headers=headers)
        self.assertEqual(device.status_code, 200, device.text)
        self.assertEqual(self.admin.delete(f"/api/devices/{device.json()['id']}", headers=headers).status_code, 200)

    def test_manual_mold_entry_can_be_undone_before_business_use(self) -> None:
        csrf = self.login(self.admin, "admin", "StrongAdminPass-123")
        headers = {"X-CSRF-Token": csrf}
        with self.factory() as db:
            model_id = db.scalar(select(MoldModel.id).limit(1))
        mold_set = self.admin.post("/api/sets", json={"code": "SET-ERROR", "model_id": model_id, "default_location_id": self.shelf_b}, headers=headers)
        self.assertEqual(mold_set.status_code, 200, mold_set.text)
        payload = {"code": "M-ERROR", "set_id": mold_set.json()["id"], "size_label": "40", "status": "READY", "current_location_id": self.shelf_b}
        mold = self.admin.post("/api/molds", json=payload, headers=headers)
        self.assertEqual(mold.status_code, 200, mold.text)
        self.assertEqual(self.admin.delete(f"/api/sets/{mold_set.json()['id']}", headers=headers).status_code, 409)
        deleted = self.admin.delete(f"/api/molds/{mold.json()['id']}", headers=headers)
        self.assertEqual(deleted.status_code, 200, deleted.text)
        self.assertEqual(self.admin.post("/api/molds", json=payload, headers=headers).status_code, 200)
        self.assertEqual(self.admin.delete(f"/api/molds/{self.admin.get('/api/molds?limit=1').json()['items'][0]['id']}", headers=headers).status_code, 409)

    def test_admin_account_and_default_location_maintenance(self) -> None:
        admin_csrf = self.login(self.admin, "admin", "StrongAdminPass-123")
        readonly_csrf = self.login(self.worker, "warehouse-view", "StrongReadonlyPass-123")
        self.assertEqual(self.worker.get("/api/auth/users").status_code, 403)
        self.assertEqual(self.worker.patch("/api/sets/1/default-location", json={"location_id": self.shelf_b, "reason": "整理货架"}, headers={"X-CSRF-Token": readonly_csrf}).status_code, 403)

        person = self.admin.post("/api/people", json={"name": "王五", "employee_code": "E-005"}, headers={"X-CSRF-Token": admin_csrf})
        self.assertEqual(person.status_code, 200, person.text)
        self.assertEqual(self.admin.post("/api/auth/users", json={"username": "wangwu", "password": "12345", "role": "WORKER", "person_id": person.json()["id"]}, headers={"X-CSRF-Token": admin_csrf}).status_code, 422)
        created = self.admin.post("/api/auth/users", json={"username": "wangwu", "password": "123456", "role": "WORKER", "person_id": person.json()["id"]}, headers={"X-CSRF-Token": admin_csrf})
        self.assertEqual(created.status_code, 200, created.text)
        self.assertEqual(self.admin.post("/api/auth/users", json={"username": "duplicate", "password": "123456", "role": "WORKER", "person_id": person.json()["id"]}, headers={"X-CSRF-Token": admin_csrf}).status_code, 409)
        self.assertNotIn("password", str(self.admin.get("/api/auth/users").json()))

        worker = TestClient(self.app)
        try:
            worker_csrf = self.login(worker, "wangwu", "123456")
            device = worker.post("/api/devices/register", json={"label": "王五手机"}, headers={"X-CSRF-Token": worker_csrf})
            self.assertEqual(device.status_code, 200, device.text)
            self.assertEqual(self.admin.post(f"/api/devices/{device.json()['id']}/authorize", headers={"X-CSRF-Token": admin_csrf}).status_code, 200)
            disabled = self.admin.patch(f"/api/auth/users/{created.json()['id']}/active", json={"active": False, "reason": "人员离岗"}, headers={"X-CSRF-Token": admin_csrf})
            self.assertEqual(disabled.status_code, 200, disabled.text)
            self.assertEqual(worker.get("/api/auth/me").status_code, 401)
            self.assertEqual(self.admin.patch(f"/api/auth/users/{created.json()['id']}/active", json={"active": True, "reason": "人员返岗"}, headers={"X-CSRF-Token": admin_csrf}).status_code, 200)
            self.login(worker, "wangwu", "123456")
            self.assertFalse(worker.get("/api/devices/current").json()["authorized"])
            self.assertEqual(self.admin.post(f"/api/auth/users/{created.json()['id']}/reset-password", json={"password": "54321", "reason": "本人申请重置"}, headers={"X-CSRF-Token": admin_csrf}).status_code, 422)
            reset = self.admin.post(f"/api/auth/users/{created.json()['id']}/reset-password", json={"password": "654321", "reason": "本人申请重置"}, headers={"X-CSRF-Token": admin_csrf})
            self.assertEqual(reset.status_code, 200, reset.text)
            self.assertEqual(worker.get("/api/auth/me").status_code, 401)
            self.assertEqual(worker.post("/api/auth/login", json={"username": "wangwu", "password": "123456"}).status_code, 401)
            self.login(worker, "wangwu", "654321")
        finally:
            worker.close()

        changed = self.admin.patch("/api/sets/1/default-location", json={"location_id": self.shelf_b, "reason": "整套安排到新架"}, headers={"X-CSRF-Token": admin_csrf})
        self.assertEqual(changed.status_code, 200, changed.text)
        with self.factory() as db:
            self.assertEqual(db.get(MoldSet, 1).default_location_id, self.shelf_b)
            self.assertTrue(all(mold.current_location_id == self.shelf_a for mold in db.scalars(select(Mold)).all()))
        self.assertTrue(any(item["action"] == "SET_DEFAULT_LOCATION" for item in self.admin.get("/api/auth/audit").json()))

    def test_manual_mold_creation_records_initialization(self) -> None:
        csrf = self.login(self.admin, "admin", "StrongAdminPass-123")
        mold_set = self.admin.post("/api/sets", json={"code": "SET-0002", "model_id": 1, "default_location_id": self.shelf_b}, headers={"X-CSRF-Token": csrf})
        self.assertEqual(mold_set.status_code, 200, mold_set.text)
        created = self.admin.post("/api/molds", json={"code": "M-000011", "set_id": mold_set.json()["id"], "size_label": "36", "status": "READY", "current_location_id": self.shelf_b}, headers={"X-CSRF-Token": csrf})
        self.assertEqual(created.status_code, 200, created.text)
        operations = self.admin.get("/api/operations").json()
        self.assertEqual(len(operations), 1)
        self.assertEqual(operations[0]["type"], "INITIALIZE")
        self.assertEqual(operations[0]["items"][0]["before_status"], "NOT_REGISTERED")
        self.assertEqual(operations[0]["items"][0]["after_status"], "READY")
        self.assertEqual(operations[0]["items"][0]["before_version"], 0)

    def test_shelf_capacity_blocks_creation_move_and_return_until_space_is_free(self) -> None:
        admin_csrf = self.login(self.admin, "admin", "StrongAdminPass-123")
        worker_csrf = self.login(self.worker, "zhangsan", "StrongWorkerPass-123")
        admin_headers = {"X-CSRF-Token": admin_csrf}
        mold_set = self.admin.post("/api/sets", json={"code": "SET-0002", "model_id": 1, "default_location_id": self.shelf_a}, headers=admin_headers).json()
        mold_payload = {"code": "M-000011", "set_id": mold_set["id"], "size_label": "36", "status": "READY", "current_location_id": self.shelf_a}
        full = self.admin.post("/api/molds", json=mold_payload, headers=admin_headers)
        self.assertEqual(full.status_code, 409, full.text)
        self.assertEqual(full.json()["detail"]["error_code"], "LOCATION_FULL")
        created = self.admin.post("/api/molds", json={**mold_payload, "current_location_id": self.shelf_b}, headers=admin_headers)
        self.assertEqual(created.status_code, 200, created.text)

        registered = self.worker.post("/api/devices/register", json={"label": "容量测试设备"}, headers={"X-CSRF-Token": worker_csrf})
        self.assertEqual(registered.status_code, 200, registered.text)
        self.assertEqual(self.admin.post(f"/api/devices/{registered.json()['id']}/authorize", headers=admin_headers).status_code, 200)
        blocked_move = self.submit("MOVE", self.shelf_a, [created.json()["id"]], [1], worker_csrf)
        self.assertEqual(blocked_move.status_code, 409, blocked_move.text)
        self.assertEqual(blocked_move.json()["detail"]["error_code"], "LOCATION_FULL")
        self.assertEqual(self.submit("ISSUE", self.line, [1], [1], worker_csrf).status_code, 200)
        moved = self.submit("MOVE", self.shelf_a, [created.json()["id"]], [1], worker_csrf)
        self.assertEqual(moved.status_code, 200, moved.text)
        blocked_return = self.submit("RETURN", self.shelf_a, [1], [2], worker_csrf)
        self.assertEqual(blocked_return.status_code, 409, blocked_return.text)
        self.assertEqual(blocked_return.json()["detail"]["error_code"], "LOCATION_FULL")
        self.assertEqual(self.submit("MOVE", self.shelf_b, [created.json()["id"]], [2], worker_csrf).status_code, 200)
        self.assertEqual(self.submit("RETURN", self.shelf_a, [1], [2], worker_csrf).status_code, 200)
        with self.factory() as db:
            self.assertEqual(len(db.scalars(select(Mold).where(Mold.current_location_id == self.shelf_a, Mold.is_current.is_(True))).all()), 10)

    def test_existing_overfull_shelf_can_shrink_but_cannot_grow(self) -> None:
        worker_csrf = self.login(self.worker, "zhangsan", "StrongWorkerPass-123")
        admin_csrf = self.login(self.admin, "admin", "StrongAdminPass-123")
        registered = self.worker.post("/api/devices/register", json={"label": "超量清理设备"}, headers={"X-CSRF-Token": worker_csrf})
        self.admin.post(f"/api/devices/{registered.json()['id']}/authorize", headers={"X-CSRF-Token": admin_csrf})
        with self.factory() as db:
            second_set = MoldSet(code="SET-0002", model_id=1, default_location_id=self.shelf_a)
            db.add(second_set)
            db.flush()
            db.add(Mold(code="M-000011", set_id=second_set.id, size_label="36", status="READY", current_location_id=self.shelf_a, version=1))
            db.commit()
        self.assertEqual(self.submit("ISSUE", self.line, [11], [1], worker_csrf).status_code, 200)
        blocked_return = self.submit("RETURN", self.shelf_a, [11], [2], worker_csrf)
        self.assertEqual(blocked_return.status_code, 409, blocked_return.text)
        self.assertEqual(blocked_return.json()["detail"]["error_code"], "LOCATION_FULL")

    def test_exception_recovery_and_correction_obey_shelf_capacity(self) -> None:
        admin_csrf = self.login(self.admin, "admin", "StrongAdminPass-123")
        worker_csrf = self.login(self.worker, "zhangsan", "StrongWorkerPass-123")
        headers = {"X-CSRF-Token": admin_csrf}
        mold_set = self.admin.post("/api/sets", json={"code": "SET-0002", "model_id": 1, "default_location_id": self.shelf_a}, headers=headers).json()
        pending = self.admin.post("/api/molds", json={"code": "M-000011", "set_id": mold_set["id"], "size_label": "36", "status": "PENDING_INSPECTION", "current_location_id": self.inspection}, headers=headers)
        self.assertEqual(pending.status_code, 200, pending.text)
        blocked = self.transition(self.admin, pending.json()["id"], "INSPECTION_PASS", 1, self.shelf_a, admin_csrf)
        self.assertEqual(blocked.status_code, 409, blocked.text)
        self.assertEqual(blocked.json()["detail"]["error_code"], "LOCATION_FULL")

        registered = self.worker.post("/api/devices/register", json={"label": "更正测试设备"}, headers={"X-CSRF-Token": worker_csrf})
        self.admin.post(f"/api/devices/{registered.json()['id']}/authorize", headers=headers)
        issued = self.submit("ISSUE", self.line, [1], [1], worker_csrf)
        self.assertEqual(issued.status_code, 200, issued.text)
        self.assertEqual(self.transition(self.admin, pending.json()["id"], "INSPECTION_PASS", 1, self.shelf_a, admin_csrf).status_code, 200)
        correction = self.admin.post(f"/api/operations/{issued.json()['id']}/corrections", json={"request_id": str(uuid4()), "reason": "尝试冲销已满库位"}, headers=headers)
        self.assertEqual(correction.status_code, 409, correction.text)
        self.assertEqual(correction.json()["detail"]["error_code"], "LOCATION_FULL")


    def test_admin_compensating_correction_and_subsequent_movement_guard(self) -> None:
        worker_csrf = self.login(self.worker, "zhangsan", "StrongWorkerPass-123")
        admin_csrf = self.login(self.admin, "admin", "StrongAdminPass-123")
        registered = self.worker.post("/api/devices/register", json={"label": "张三手机"}, headers={"X-CSRF-Token": worker_csrf})
        self.assertEqual(registered.status_code, 200, registered.text)
        self.assertEqual(self.admin.post(f"/api/devices/{registered.json()['id']}/authorize", headers={"X-CSRF-Token": admin_csrf}).status_code, 200)
        issued = self.submit("ISSUE", self.line, [1], [1], worker_csrf)
        self.assertEqual(issued.status_code, 200, issued.text)
        url = f"/api/operations/{issued.json()['id']}/corrections"
        payload = {"request_id": str(uuid4()), "reason": "领用单据录错，现场核对后冲销"}
        self.assertEqual(self.worker.post(url, json=payload, headers={"X-CSRF-Token": worker_csrf}).status_code, 403)
        corrected = self.admin.post(url, json=payload, headers={"X-CSRF-Token": admin_csrf})
        self.assertEqual(corrected.status_code, 200, corrected.text)
        self.assertEqual(corrected.json()["type"], "CORRECTION")
        self.assertEqual(corrected.json()["correction_of_operation_id"], issued.json()["id"])
        self.assertEqual(corrected.json()["items"][0]["after_version"], 3)
        repeated = self.admin.post(url, json=payload, headers={"X-CSRF-Token": admin_csrf})
        self.assertEqual(repeated.status_code, 200, repeated.text)
        self.assertEqual(repeated.json()["id"], corrected.json()["id"])
        self.assertEqual(self.admin.post(url, json={**payload, "request_id": str(uuid4())}, headers={"X-CSRF-Token": admin_csrf}).status_code, 409)
        with self.factory() as db:
            mold = db.get(Mold, 1)
            self.assertEqual((mold.status, mold.current_location_id, mold.custodian_person_id, mold.version), ("READY", self.shelf_a, None, 3))
        later = self.submit("ISSUE", self.line, [2], [1], worker_csrf)
        self.assertEqual(later.status_code, 200, later.text)
        returned = self.submit("RETURN", self.shelf_a, [2], [2], worker_csrf)
        self.assertEqual(returned.status_code, 200, returned.text)
        rejected = self.admin.post(f"/api/operations/{later.json()['id']}/corrections", json={"request_id": str(uuid4()), "reason": "尝试更正已有后续操作的单据"}, headers={"X-CSRF-Token": admin_csrf})
        self.assertEqual(rejected.status_code, 409, rejected.text)
        self.assertEqual(rejected.json()["detail"]["error_code"], "SUBSEQUENT_MOVEMENT")

    def test_device_authorization_idempotency_and_full_set_return(self) -> None:
        worker_csrf = self.login(self.worker, "zhangsan", "StrongWorkerPass-123")
        admin_csrf = self.login(self.admin, "admin", "StrongAdminPass-123")
        registration = self.worker.post("/api/devices/register", json={"label": "张三的安卓手机"}, headers={"X-CSRF-Token": worker_csrf})
        self.assertEqual(registration.status_code, 200, registration.text)
        self.assertEqual(self.worker.get("/api/devices/current").json()["authorized"], False)
        pending = self.submit("ISSUE", self.line, [1], [1], worker_csrf)
        self.assertEqual(pending.status_code, 403, pending.text)
        self.assertEqual(self.admin.get("/api/devices").json()[0]["person"], "张三")

        authorized = self.admin.post(f"/api/devices/{registration.json()['id']}/authorize", headers={"X-CSRF-Token": admin_csrf})
        self.assertEqual(authorized.status_code, 200, authorized.text)
        self.assertEqual(self.worker.get("/api/devices/current").json()["authorized"], True)
        first_key = str(uuid4())
        issue = self.submit("ISSUE", self.line, [1, 2], [1, 1], worker_csrf, first_key)
        self.assertEqual(issue.status_code, 200, issue.text)
        self.assertEqual(len(issue.json()["items"]), 2)
        self.assertEqual(issue.json()["actor_name"], "张三")
        self.assertEqual(issue.json()["target_location_code"], "产线01")
        self.assertEqual(issue.json()["items"][0]["mold_code"], "M-000001")
        self.assertTrue(issue.json()["created_at"].endswith("+00:00"))
        repeated = self.submit("ISSUE", self.line, [1, 2], [1, 1], worker_csrf, first_key)
        self.assertEqual(repeated.status_code, 200, repeated.text)
        self.assertEqual(repeated.json()["id"], issue.json()["id"])
        changed = self.submit("ISSUE", self.line, [1], [1], worker_csrf, first_key)
        self.assertEqual(changed.status_code, 409, changed.text)
        stale = self.submit("ISSUE", self.line, [3], [99], worker_csrf)
        self.assertEqual(stale.status_code, 409, stale.text)

        partial_return = self.submit("RETURN", self.shelf_b, [1, 2], [2, 2], worker_csrf)
        self.assertEqual(partial_return.status_code, 200, partial_return.text)
        with self.factory() as db:
            self.assertEqual(db.scalar(select(MoldSet.default_location_id).where(MoldSet.code == "SET-0001")), self.shelf_a)
            self.assertEqual(db.scalar(select(Mold.version).where(Mold.id == 1)), 3)

        remaining = self.submit("ISSUE", self.line, list(range(3, 11)), [1] * 8, worker_csrf)
        self.assertEqual(remaining.status_code, 200, remaining.text)
        reissue = self.submit("ISSUE", self.line, [1, 2], [3, 3], worker_csrf)
        self.assertEqual(reissue.status_code, 200, reissue.text)
        full_return = self.submit("RETURN", self.shelf_b, list(range(1, 11)), [4, 4] + [2] * 8, worker_csrf)
        self.assertEqual(full_return.status_code, 200, full_return.text)
        with self.factory() as db:
            self.assertEqual(db.scalar(select(MoldSet.default_location_id).where(MoldSet.code == "SET-0001")), self.shelf_b)
            current = db.scalars(select(Mold).order_by(Mold.id)).all()
            self.assertTrue(all(mold.status == "READY" and mold.current_location_id == self.shelf_b and mold.custodian_person_id is None for mold in current))

        revoked = self.admin.post(f"/api/devices/{registration.json()['id']}/revoke", headers={"X-CSRF-Token": admin_csrf})
        self.assertEqual(revoked.status_code, 200, revoked.text)
        self.assertEqual(self.worker.get("/api/devices/current").json()["authorized"], False)
        denied = self.submit("ISSUE", self.line, [1], [5], worker_csrf)
        self.assertEqual(denied.status_code, 403, denied.text)

    def test_worker_history_only_shows_own_operations(self) -> None:
        self.login(self.worker, "zhangsan", "StrongWorkerPass-123")
        self.login(self.admin, "admin", "StrongAdminPass-123")
        with self.factory() as db:
            admin = db.scalar(select(User).where(User.username == "admin"))
            worker = db.scalar(select(User).where(User.username == "zhangsan"))
            db.add_all([
                Operation(request_id=str(uuid4()), payload_hash="a" * 64, type="MOVE", actor_user_id=admin.id, target_location_id=self.shelf_b),
                Operation(request_id=str(uuid4()), payload_hash="b" * 64, type="ISSUE", actor_user_id=worker.id, target_location_id=self.line),
            ])
            db.commit()
        mine = self.worker.get("/api/operations")
        self.assertEqual(mine.status_code, 200, mine.text)
        self.assertEqual(len(mine.json()), 1)
        self.assertEqual(mine.json()[0]["actor_name"], "张三")
        all_records = self.admin.get("/api/operations")
        self.assertEqual(len(all_records.json()), 2)
        admin_record = next(record for record in all_records.json() if record["actor_name"] == "维护员")
        forbidden = self.worker.get(f"/api/operations/{admin_record['id']}")
        self.assertEqual(forbidden.status_code, 403, forbidden.text)

    def test_readonly_catalog_and_write_denial(self) -> None:
        viewer = TestClient(self.app)
        try:
            csrf = self.login(viewer, "warehouse-view", "StrongReadonlyPass-123")
            locations = viewer.get("/api/locations")
            self.assertEqual(locations.status_code, 200, locations.text)
            self.assertEqual(len(locations.json()), 8)
            page = viewer.get("/api/molds?offset=2&limit=3")
            self.assertEqual(page.status_code, 200, page.text)
            self.assertEqual(page.json()["total"], 10)
            self.assertEqual([item["code"] for item in page.json()["items"]], ["M-000003", "M-000004", "M-000005"])
            blocked = viewer.post("/api/locations", json={"type": "SHELF", "zone": "C", "rack": "1", "level": "1"}, headers={"X-CSRF-Token": csrf})
            self.assertEqual(blocked.status_code, 403, blocked.text)
            self.assertEqual(viewer.get("/api/operations").status_code, 200)
        finally:
            viewer.close()

    def test_move_transfer_and_return_by_another_person(self) -> None:
        worker_csrf = self.login(self.worker, "zhangsan", "StrongWorkerPass-123")
        admin_csrf = self.login(self.admin, "admin", "StrongAdminPass-123")
        receiver = TestClient(self.app)
        try:
            receiver_csrf = self.login(receiver, "lisi", "StrongReceiverPass-123")
            for client, csrf, label in [(self.worker, worker_csrf, "张三手机"), (receiver, receiver_csrf, "李四手机")]:
                registered = client.post("/api/devices/register", json={"label": label}, headers={"X-CSRF-Token": csrf})
                self.assertEqual(registered.status_code, 200, registered.text)
                approved = self.admin.post(f"/api/devices/{registered.json()['id']}/authorize", headers={"X-CSRF-Token": admin_csrf})
                self.assertEqual(approved.status_code, 200, approved.text)

            moved = self.submit("MOVE", self.shelf_b, [1], [1], worker_csrf)
            self.assertEqual(moved.status_code, 200, moved.text)
            with self.factory() as db:
                self.assertEqual(db.get(Mold, 1).current_location_id, self.shelf_b)
                self.assertEqual(db.scalar(select(MoldSet.default_location_id)), self.shelf_a)

            issued = self.submit("ISSUE", self.line, [1], [2], worker_csrf)
            self.assertEqual(issued.status_code, 200, issued.text)
            transferred = receiver.post("/api/operations", json={"request_id": str(uuid4()), "type": "TRANSFER", "target_location_id": self.line_two, "items": [{"mold_id": 1, "expected_version": 3}]}, headers={"X-CSRF-Token": receiver_csrf})
            self.assertEqual(transferred.status_code, 200, transferred.text)
            self.assertNotEqual(transferred.json()["items"][0]["before_custodian_id"], transferred.json()["items"][0]["after_custodian_id"])
            returned = self.submit("RETURN", self.shelf_b, [1], [4], worker_csrf)
            self.assertEqual(returned.status_code, 200, returned.text)
            with self.factory() as db:
                mold = db.get(Mold, 1)
                self.assertEqual((mold.status, mold.current_location_id, mold.custodian_person_id), ("READY", self.shelf_b, None))
                self.assertEqual(db.scalar(select(MoldSet.default_location_id)), self.shelf_a)
        finally:
            receiver.close()

    def test_mixed_return_is_atomic_and_keeps_each_abnormal_reason(self) -> None:
        worker_csrf = self.login(self.worker, "zhangsan", "StrongWorkerPass-123")
        admin_csrf = self.login(self.admin, "admin", "StrongAdminPass-123")
        headers = {"X-CSRF-Token": worker_csrf}
        registered = self.worker.post("/api/devices/register", json={"label": "混合归还手机"}, headers=headers)
        self.assertEqual(self.admin.post(f"/api/devices/{registered.json()['id']}/authorize", headers={"X-CSRF-Token": admin_csrf}).status_code, 200)
        self.assertEqual(self.submit("ISSUE", self.line, [1, 2, 3], [1, 1, 1], worker_csrf).status_code, 200)
        items = [
            {"mold_id": 1, "expected_version": 2},
            {"mold_id": 2, "expected_version": 2, "return_condition": "PENDING_INSPECTION", "exception_location_id": self.inspection, "note": "表面有裂纹"},
            {"mold_id": 3, "expected_version": 2, "return_condition": "IN_REPAIR", "exception_location_id": self.repair, "note": "连接件损坏"},
        ]
        request = {"request_id": str(uuid4()), "type": "RETURN", "target_location_id": self.shelf_b, "items": items}
        invalid = self.worker.post("/api/operations", json={**request, "items": [items[0], {**items[1], "note": ""}, items[2]]}, headers=headers)
        self.assertEqual(invalid.status_code, 422, invalid.text)
        wrong_place = self.worker.post("/api/operations", json={**request, "items": [items[0], items[1], {**items[2], "exception_location_id": self.shelf_a}]}, headers=headers)
        self.assertEqual(wrong_place.status_code, 422, wrong_place.text)
        with self.factory() as db:
            self.assertTrue(all(db.get(Mold, mold_id).status == "IN_USE" for mold_id in (1, 2, 3)))
        result = self.worker.post("/api/operations", json=request, headers=headers)
        self.assertEqual(result.status_code, 200, result.text)
        self.assertEqual([item["after_status"] for item in result.json()["items"]], ["READY", "PENDING_INSPECTION", "IN_REPAIR"])
        self.assertEqual([item["after_location_id"] for item in result.json()["items"]], [self.shelf_b, self.inspection, self.repair])
        self.assertEqual(result.json()["items"][1]["note"], "表面有裂纹")
        self.assertEqual(self.worker.post("/api/operations", json=request, headers=headers).json()["id"], result.json()["id"])
        with self.factory() as db:
            self.assertEqual(db.scalar(select(MoldSet.default_location_id).where(MoldSet.code == "SET-0001")), self.shelf_a)
            self.assertTrue(all(db.get(Mold, mold_id).custodian_person_id is None for mold_id in (1, 2, 3)))
        self.assertIn("表面有裂纹", self.worker.get("/api/exports/operations").content.decode("utf-8-sig"))
        self.assertEqual(self.submit("ISSUE", self.line, [4, 5], [1, 1], worker_csrf).status_code, 200)
        abnormal_only = self.worker.post("/api/operations", json={"request_id": str(uuid4()), "type": "RETURN", "target_location_id": self.inspection, "items": [
            {"mold_id": 4, "expected_version": 2, "return_condition": "PENDING_INSPECTION", "exception_location_id": self.inspection, "note": "发现裂纹"},
            {"mold_id": 5, "expected_version": 2, "return_condition": "IN_REPAIR", "exception_location_id": self.repair, "note": "锁扣损坏"},
        ]}, headers=headers)
        self.assertEqual(abnormal_only.status_code, 200, abnormal_only.text)
        self.assertEqual(abnormal_only.json()["target_location_id"], self.inspection)

    def test_stocktake_freeze_scan_and_close(self) -> None:
        worker_csrf = self.login(self.worker, "zhangsan", "StrongWorkerPass-123")
        admin_csrf = self.login(self.admin, "admin", "StrongAdminPass-123")
        headers = {"X-CSRF-Token": worker_csrf}
        admin_headers = {"X-CSRF-Token": admin_csrf}
        registered = self.worker.post("/api/devices/register", json={"label": "盘点手机"}, headers=headers)
        self.assertEqual(registered.status_code, 200, registered.text)
        self.assertEqual(self.admin.post(f"/api/devices/{registered.json()['id']}/authorize", headers=admin_headers).status_code, 200)

        created = self.worker.post("/api/stocktakes", json={"location_id": self.shelf_a}, headers=headers)
        self.assertEqual(created.status_code, 200, created.text)
        stocktake_id = created.json()["id"]
        self.assertEqual(len(created.json()["expected"]), 10)
        self.assertEqual(created.json()["missing_codes"], [f"M-{index:06d}" for index in range(1, 11)])
        self.assertEqual(self.worker.post("/api/stocktakes", json={"location_id": self.shelf_a}, headers=headers).status_code, 409)
        create_during_freeze = self.admin.post("/api/molds", json={"code": "M-999998", "set_id": 1, "size_label": "46", "status": "READY", "current_location_id": self.shelf_a}, headers=admin_headers)
        self.assertEqual(create_during_freeze.status_code, 409, create_during_freeze.text)
        self.assertEqual(create_during_freeze.json()["detail"]["error_code"], "LOCATION_STOCKTAKE_FROZEN")
        blocked = self.submit("ISSUE", self.line, [1], [1], worker_csrf)
        self.assertEqual(blocked.status_code, 409, blocked.text)
        self.assertEqual(blocked.json()["detail"]["error_code"], "LOCATION_STOCKTAKE_FROZEN")
        self.assertEqual(self.worker.post(f"/api/stocktakes/{stocktake_id}/scan", json={"raw_code": "MOLD:M-000001"}, headers=headers).status_code, 409)
        self.assertEqual(self.worker.post(f"/api/stocktakes/{stocktake_id}/scan", json={"raw_code": "LOC:A-01-2"}, headers=headers).status_code, 409)
        verified = self.worker.post(f"/api/stocktakes/{stocktake_id}/scan", json={"raw_code": "LOC:A-01-1"}, headers=headers)
        self.assertEqual(verified.status_code, 200, verified.text)
        self.assertTrue(verified.json()["stocktake"]["location_verified"])
        unknown = self.worker.post(f"/api/stocktakes/{stocktake_id}/scan", json={"raw_code": "M-999999"}, headers=headers)
        self.assertEqual(unknown.json()["result"], "UNKNOWN")
        unknown_scan_id = unknown.json()["stocktake"]["scans"][0]["id"]
        for index in range(1, 11):
            scanned = self.worker.post(f"/api/stocktakes/{stocktake_id}/scan", json={"raw_code": f"MOLD:M-{index:06d}"}, headers=headers)
            self.assertEqual(scanned.status_code, 200, scanned.text)
            self.assertEqual(scanned.json()["result"], "EXPECTED")
        duplicate = self.worker.post(f"/api/stocktakes/{stocktake_id}/scan", json={"raw_code": "M-000001"}, headers=headers)
        self.assertEqual(duplicate.json()["kind"], "ALREADY_SCANNED")
        removed = self.worker.delete(f"/api/stocktakes/{stocktake_id}/scans/{unknown_scan_id}", headers=headers)
        self.assertEqual(removed.status_code, 200, removed.text)
        self.assertEqual(removed.json()["unexpected_codes"], [])
        submitted = self.worker.post(f"/api/stocktakes/{stocktake_id}/submit", headers=headers)
        self.assertEqual(submitted.status_code, 200, submitted.text)
        self.assertEqual(submitted.json()["missing_codes"], [])
        self.assertEqual(self.submit("MOVE", self.shelf_b, [1], [1], worker_csrf).status_code, 409)
        closed = self.admin.post(f"/api/stocktakes/{stocktake_id}/close", headers=admin_headers)
        self.assertEqual(closed.status_code, 200, closed.text)
        self.assertEqual(closed.json()["status"], "CLOSED")
        self.assertEqual(self.submit("ISSUE", self.line, [1], [1], worker_csrf).status_code, 200)

    def test_stocktake_difference_requires_admin_cancel(self) -> None:
        worker_csrf = self.login(self.worker, "zhangsan", "StrongWorkerPass-123")
        admin_csrf = self.login(self.admin, "admin", "StrongAdminPass-123")
        headers = {"X-CSRF-Token": worker_csrf}
        admin_headers = {"X-CSRF-Token": admin_csrf}
        registered = self.worker.post("/api/devices/register", json={"label": "盘点手机"}, headers=headers)
        self.admin.post(f"/api/devices/{registered.json()['id']}/authorize", headers=admin_headers)
        stocktake = self.worker.post("/api/stocktakes", json={"location_id": self.shelf_a}, headers=headers).json()
        self.worker.post(f"/api/stocktakes/{stocktake['id']}/scan", json={"raw_code": "LOC:A-01-1"}, headers=headers)
        self.worker.post(f"/api/stocktakes/{stocktake['id']}/scan", json={"raw_code": "M-000001"}, headers=headers)
        submitted = self.worker.post(f"/api/stocktakes/{stocktake['id']}/submit", headers=headers)
        self.assertEqual(submitted.status_code, 200, submitted.text)
        self.assertEqual(len(submitted.json()["missing_codes"]), 9)
        self.assertEqual(self.admin.post(f"/api/stocktakes/{stocktake['id']}/close", headers=admin_headers).status_code, 409)
        self.assertEqual(self.worker.post(f"/api/stocktakes/{stocktake['id']}/cancel", json={"reason": "不完整"}, headers=headers).status_code, 403)
        cancelled = self.admin.post(f"/api/stocktakes/{stocktake['id']}/cancel", json={"reason": "现场盘点中断，重新安排"}, headers=admin_headers)
        self.assertEqual(cancelled.status_code, 200, cancelled.text)
        self.assertEqual(cancelled.json()["status"], "CANCELLED")
        self.assertEqual(self.submit("ISSUE", self.line, [1], [1], worker_csrf).status_code, 200)

    def test_stocktake_reconciles_missing_and_wrong_location_with_operations(self) -> None:
        worker_csrf = self.login(self.worker, "zhangsan", "StrongWorkerPass-123")
        admin_csrf = self.login(self.admin, "admin", "StrongAdminPass-123")
        headers = {"X-CSRF-Token": worker_csrf}
        admin_headers = {"X-CSRF-Token": admin_csrf}
        registered = self.worker.post("/api/devices/register", json={"label": "盘点手机"}, headers=headers)
        self.admin.post(f"/api/devices/{registered.json()['id']}/authorize", headers=admin_headers)
        with self.factory() as db:
            model_id = db.scalar(select(MoldModel.id).where(MoldModel.code == "XM-001"))
            other_set = MoldSet(code="SET-0002", model_id=model_id, default_location_id=self.shelf_b)
            db.add(other_set)
            db.flush()
            db.add(Mold(code="M-000011", set_id=other_set.id, size_label="36", status="READY", current_location_id=self.shelf_b, version=1))
            db.commit()

        created = self.worker.post("/api/stocktakes", json={"location_id": self.shelf_a}, headers=headers).json()
        stocktake_id = created["id"]
        self.worker.post(f"/api/stocktakes/{stocktake_id}/scan", json={"raw_code": "LOC:A-01-1"}, headers=headers)
        for index in range(1, 10):
            self.worker.post(f"/api/stocktakes/{stocktake_id}/scan", json={"raw_code": f"M-{index:06d}"}, headers=headers)
        wrong = self.worker.post(f"/api/stocktakes/{stocktake_id}/scan", json={"raw_code": "M-000011"}, headers=headers)
        self.assertEqual(wrong.json()["result"], "WRONG_LOCATION")
        self.worker.post(f"/api/stocktakes/{stocktake_id}/submit", headers=headers)

        wrong_request = {"request_id": str(uuid4()), "type": "CONFIRM_WRONG_LOCATION", "mold_id": 11, "expected_version": 1, "reason": "现场确认在A区一号架"}
        other_stocktake = self.worker.post("/api/stocktakes", json={"location_id": self.shelf_b}, headers=headers)
        self.assertEqual(other_stocktake.status_code, 200, other_stocktake.text)
        frozen_elsewhere = self.admin.post(f"/api/stocktakes/{stocktake_id}/resolve", json=wrong_request, headers=admin_headers)
        self.assertEqual(frozen_elsewhere.status_code, 409, frozen_elsewhere.text)
        self.assertEqual(frozen_elsewhere.json()["detail"]["error_code"], "OTHER_LOCATION_FROZEN")
        self.assertEqual(self.admin.post(f"/api/stocktakes/{other_stocktake.json()['id']}/cancel", json={"reason": "验证并解除另一库位冻结"}, headers=admin_headers).status_code, 200)
        full_shelf = self.admin.post(f"/api/stocktakes/{stocktake_id}/resolve", json=wrong_request, headers=admin_headers)
        self.assertEqual(full_shelf.status_code, 409, full_shelf.text)
        self.assertEqual(full_shelf.json()["detail"]["error_code"], "LOCATION_FULL")

        missing_request = {"request_id": str(uuid4()), "type": "MARK_UNVERIFIED", "mold_id": 10, "expected_version": 1, "target_location_id": self.unknown, "reason": "现场查找后未找到模具"}
        stale_missing = self.admin.post(f"/api/stocktakes/{stocktake_id}/resolve", json={**missing_request, "request_id": str(uuid4()), "expected_version": 99}, headers=admin_headers)
        self.assertEqual(stale_missing.status_code, 409, stale_missing.text)
        adjusted_missing = self.admin.post(f"/api/stocktakes/{stocktake_id}/resolve", json=missing_request, headers=admin_headers)
        self.assertEqual(adjusted_missing.status_code, 200, adjusted_missing.text)
        self.assertEqual(adjusted_missing.json()["stocktake"]["missing_codes"], [])
        adjusted_wrong = self.admin.post(f"/api/stocktakes/{stocktake_id}/resolve", json=wrong_request, headers=admin_headers)
        self.assertEqual(adjusted_wrong.status_code, 200, adjusted_wrong.text)
        self.assertEqual(adjusted_wrong.json()["stocktake"]["unexpected_codes"], [])
        repeated = self.admin.post(f"/api/stocktakes/{stocktake_id}/resolve", json=wrong_request, headers=admin_headers)
        self.assertEqual(repeated.status_code, 200, repeated.text)
        self.assertEqual(repeated.json()["operation"]["id"], adjusted_wrong.json()["operation"]["id"])
        self.assertEqual(self.admin.post(f"/api/stocktakes/{stocktake_id}/resolve", json={**wrong_request, "reason": "另一原因"}, headers=admin_headers).status_code, 409)
        closed = self.admin.post(f"/api/stocktakes/{stocktake_id}/close", headers=admin_headers)
        self.assertEqual(closed.status_code, 200, closed.text)
        with self.factory() as db:
            wrong_mold = db.get(Mold, 11)
            missing_mold = db.get(Mold, 10)
            self.assertEqual((wrong_mold.current_location_id, wrong_mold.status), (self.shelf_a, "READY"))
            self.assertEqual((missing_mold.current_location_id, missing_mold.status), (self.unknown, "UNVERIFIED"))
            adjustments = db.scalars(select(StocktakeAdjustment).where(StocktakeAdjustment.session_id == stocktake_id)).all()
            self.assertEqual(len(adjustments), 2)
            self.assertTrue(all(db.get(Operation, item.operation_id).type == "STOCKTAKE_ADJUST" for item in adjustments))
        found = self.transition(self.admin, 10, "FOUND", 2, self.inspection, admin_csrf, found_status="PENDING_INSPECTION")
        self.assertEqual(found.status_code, 200, found.text)
        self.assertEqual(found.json()["mold"]["status"], "PENDING_INSPECTION")
        full_shelf = self.transition(self.admin, 10, "INSPECTION_PASS", 3, self.shelf_a, admin_csrf)
        self.assertEqual(full_shelf.status_code, 409, full_shelf.text)
        self.assertEqual(full_shelf.json()["detail"]["error_code"], "LOCATION_FULL")
        passed = self.transition(self.admin, 10, "INSPECTION_PASS", 3, self.shelf_b, admin_csrf)
        self.assertEqual(passed.status_code, 200, passed.text)
        self.assertEqual(passed.json()["mold"]["status"], "READY")

    def test_exception_repair_and_scrap_flow(self) -> None:
        worker_csrf = self.login(self.worker, "zhangsan", "StrongWorkerPass-123")
        admin_csrf = self.login(self.admin, "admin", "StrongAdminPass-123")
        registered = self.worker.post("/api/devices/register", json={"label": "作业手机"}, headers={"X-CSRF-Token": worker_csrf})
        self.admin.post(f"/api/devices/{registered.json()['id']}/authorize", headers={"X-CSRF-Token": admin_csrf})
        self.assertEqual(self.submit("ISSUE", self.line, [1], [1], worker_csrf).status_code, 200)
        wrong_target = self.transition(self.worker, 1, "RETURN_FOR_INSPECTION", 2, self.repair, worker_csrf)
        self.assertEqual(wrong_target.status_code, 409, wrong_target.text)
        pending = self.transition(self.worker, 1, "RETURN_FOR_INSPECTION", 2, self.inspection, worker_csrf)
        self.assertEqual(pending.status_code, 200, pending.text)
        self.assertEqual(pending.json()["mold"]["custodian"], None)
        repair = self.transition(self.worker, 1, "SEND_REPAIR", 3, self.repair, worker_csrf)
        self.assertEqual(repair.status_code, 200, repair.text)
        completed = self.transition(self.worker, 1, "REPAIR_COMPLETE", 4, self.inspection, worker_csrf)
        self.assertEqual(completed.status_code, 200, completed.text)
        passed = self.transition(self.worker, 1, "INSPECTION_PASS", 5, self.shelf_b, worker_csrf)
        self.assertEqual(passed.status_code, 200, passed.text)
        scrap_key = str(uuid4())
        scrap = self.transition(self.admin, 1, "SCRAP", 6, self.scrap, admin_csrf, request_id=scrap_key)
        self.assertEqual(scrap.status_code, 200, scrap.text)
        self.assertEqual(scrap.json()["mold"]["status"], "SCRAPPED")
        repeated = self.transition(self.admin, 1, "SCRAP", 6, self.scrap, admin_csrf, request_id=scrap_key)
        self.assertEqual(repeated.status_code, 200, repeated.text)
        self.assertEqual(repeated.json()["operation"]["id"], scrap.json()["operation"]["id"])
        replacement = self.admin.post("/api/molds", json={"code": "M-000011", "set_id": 1, "size_label": "36", "status": "READY", "current_location_id": self.shelf_a}, headers={"X-CSRF-Token": admin_csrf})
        self.assertEqual(replacement.status_code, 200, replacement.text)
        self.assertEqual(replacement.json()["size_label"], "36")
        with self.factory() as db:
            self.assertEqual(db.get(Mold, 1).is_current, False)


if __name__ == "__main__":
    unittest.main()
