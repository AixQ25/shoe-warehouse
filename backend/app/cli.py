from __future__ import annotations

import argparse
import os
import secrets
from datetime import timedelta
from itertools import islice
from uuid import uuid4

from sqlalchemy import func, select

from .auth import hash_password
from .console_input import read_password
from .database import Base, make_engine, make_session_factory
from .models import Location, Mold, MoldModel, MoldSet, Operation, OperationItem, Person, User, utc_now


def assert_development() -> None:
    if os.getenv("WAREHOUSE_ENV", "development").lower() == "production":
        raise SystemExit("这个命令只允许用于开发环境；正式库需使用迁移和单独初始化流程")


def create_user(username: str, person_name: str | None, role: str) -> None:
    password = read_password("新账号密码（输入时显示 *）：")
    confirm = read_password("再次输入（输入时显示 *）：")
    if password != confirm or len(password) < 6:
        raise SystemExit("密码不一致，或少于 6 个字符")
    engine = make_engine()
    factory = make_session_factory(engine)
    with factory() as db:
        if db.scalar(select(User).where(User.username == username)):
            raise SystemExit("账号已存在")
        person_id = None
        if person_name:
            person = Person(name=person_name)
            db.add(person)
            db.flush()
            person_id = person.id
        db.add(User(username=username, password_hash=hash_password(password), role=role, person_id=person_id))
        db.commit()
    print(f"已创建 {role} 账号 {username}，密码未写入文件")


LEGACY_SAMPLE_NAMES = (
    "飞跃运动底", "轻云休闲底", "山峰训练底", "海风凉鞋底", "远途工作底",
    "星河跑鞋底", "远航童鞋底", "晨光休闲底", "逐风运动底", "云雀训练底",
    "磐石工作底", "踏浪凉鞋底", "飞鸟轻跑底", "原野徒步底", "月光休闲底",
)


def seed_sample(set_count: int) -> None:
    assert_development()
    engine = make_engine()
    factory = make_session_factory(engine)
    with factory() as db:
        if db.scalar(select(Mold.id).limit(1)) is not None:
            raise SystemExit("库中已有模具，拒绝重复导入样例资料")
        shelves: list[Location] = []
        for zone in "ABCDEFGHIJ":
            for rack in range(1, 6):
                for level in (3, 2, 1):
                    code = f"{zone}-{rack:02d}-{level}"
                    shelf = db.scalar(select(Location).where(Location.code == code))
                    if shelf is None:
                        shelf = Location(code=code, name=f"{zone}区 {rack}号架 {level}层", type="SHELF", zone=zone, rack=str(rack), level=str(level))
                        db.add(shelf)
                    shelves.append(shelf)
        for line in ("产线01", "产线02", "产线03"):
            if db.scalar(select(Location).where(Location.code == line)) is None:
                db.add(Location(code=line, name=line, type="LINE"))
        if db.scalar(select(Location).where(Location.code == "UNKNOWN-01")) is None:
            db.add(Location(code="UNKNOWN-01", name="未知位置", type="UNKNOWN"))
        for code, name, kind in (("INSPECTION-01", "待检区", "INSPECTION"), ("REPAIR-01", "维修区", "REPAIR"), ("SCRAP-01", "报废区", "SCRAP")):
            if db.scalar(select(Location).where(Location.code == code)) is None:
                db.add(Location(code=code, name=name, type=kind))
        db.flush()
        line_locations = [db.scalar(select(Location).where(Location.code == code)) for code in ("产线01", "产线02", "产线03")]
        inspection_location = db.scalar(select(Location).where(Location.code == "INSPECTION-01"))
        repair_location = db.scalar(select(Location).where(Location.code == "REPAIR-01"))
        custodians = []
        for name in ("张三", "李四", "王五", "赵六"):
            person = db.scalar(select(Person).where(Person.name == name))
            if person is None:
                person = Person(name=name)
                db.add(person)
            custodians.append(person)
        db.flush()
        for index, shelf in enumerate(islice(shelves, set_count)):
            model_code = f"XM-{index % 15 + 1:03d}"
            model = db.scalar(select(MoldModel).where(MoldModel.code == model_code))
            if model is None:
                model = MoldModel(code=model_code, name=model_code)
                db.add(model)
                db.flush()
            mold_set = MoldSet(code=f"SET-{index + 1:04d}", model_id=model.id, default_location_id=shelf.id)
            db.add(mold_set)
            db.flush()
            for size_index in range(10):
                issued = index < 2 or (index > 0 and index % 17 == 0) or (index % 41 == 9 and size_index in (3, 6))
                repair = not issued and index % 23 == 5 and size_index == 8
                inspection = not issued and not repair and index % 31 == 11 and size_index == 2
                status = "IN_USE" if issued else "IN_REPAIR" if repair else "PENDING_INSPECTION" if inspection else "READY"
                location_id = line_locations[index % len(line_locations)].id if issued else repair_location.id if repair else inspection_location.id if inspection else shelf.id
                db.add(Mold(code=f"M-{index * 10 + size_index + 1:06d}", set_id=mold_set.id, size_label=str(36 + size_index), status=status, current_location_id=location_id, custodian_person_id=custodians[index % len(custodians)].id if issued else None))
        db.commit()
    print(f"已导入 {set_count} 套、{set_count * 10} 个样例模具；仅用于本机开发库")


def normalize_sample_names() -> None:
    assert_development()
    engine = make_engine()
    factory = make_session_factory(engine)
    with factory() as db:
        if db.scalar(select(func.count(Mold.id))) != 1500:
            return
        changed = 0
        for index, old_name in enumerate(LEGACY_SAMPLE_NAMES, start=1):
            code = f"XM-{index:03d}"
            model = db.scalar(select(MoldModel).where(MoldModel.code == code, MoldModel.name == old_name))
            if model is not None:
                model.name = code
                changed += 1
        if changed:
            db.commit()
            print(f"已将 {changed} 个旧样例型号名称替换为现有编号")


def seed_sample_history() -> None:
    assert_development()
    engine = make_engine()
    factory = make_session_factory(engine)
    with factory() as db:
        if db.scalar(select(Operation.id).limit(1)) is not None:
            return
        actor = db.scalar(select(User).where(User.username == "admin", User.role == "ADMIN"))
        first_set = db.scalar(select(MoldSet).where(MoldSet.code == "SET-0001"))
        if actor is None or first_set is None or first_set.model.code != "XM-001" or first_set.model.name != "XM-001":
            return
        candidates = [2, 0, 3, 17, 4, 34, 6, 51, 7, 68, 8, 85, 10, 102, 12, 119, 13, 136]
        for index, set_index in enumerate(candidates):
            mold_set = db.scalar(select(MoldSet).where(MoldSet.code == f"SET-{set_index + 1:04d}"))
            if mold_set is None:
                continue
            members = db.scalars(select(Mold).where(Mold.set_id == mold_set.id, Mold.is_current.is_(True)).order_by(Mold.id)).all()
            if len(members) != 10 or any(mold.version != 1 for mold in members):
                continue
            is_issue = all(mold.status == "IN_USE" for mold in members)
            is_return = all(mold.status == "READY" for mold in members)
            if not (is_issue or is_return):
                continue
            target_id = members[0].current_location_id
            line_id = db.scalar(select(Location.id).where(Location.code == "产线01"))
            op = Operation(request_id=str(uuid4()), payload_hash="sample-local-history", type="ISSUE" if is_issue else "RETURN", actor_user_id=actor.id, target_location_id=target_id, reason="本机样例资料", created_at=utc_now() - timedelta(hours=len(candidates) - index))
            db.add(op)
            for mold in members:
                before_status = "READY" if is_issue else "IN_USE"
                before_location = mold_set.default_location_id if is_issue else line_id
                before_custodian = None if is_issue else actor.person_id
                db.add(OperationItem(operation=op, mold_id=mold.id, before_status=before_status, after_status=mold.status, before_location_id=before_location, after_location_id=mold.current_location_id, before_custodian_id=before_custodian, after_custodian_id=mold.custodian_person_id, before_version=1, after_version=2))
                mold.version = 2
        db.commit()
    print("本机样例流水已建立；仅用于本机开发库")


def bootstrap_local() -> None:
    assert_development()
    engine = make_engine()
    factory = make_session_factory(engine)
    with factory() as db:
        if db.scalar(select(User.id).limit(1)) is None:
            password = secrets.token_urlsafe(18)
            person = Person(name="本机维护员")
            db.add(person)
            db.flush()
            db.add(User(username="admin", password_hash=hash_password(password), role="ADMIN", person_id=person.id))
            db.commit()
            print(f"首次登录账号：admin  密码：{password}")
            print("请保存密码；再次运行本命令不会重置账号。")
        else:
            print("已有账号，保留现有账号和密码。")
        has_molds = db.scalar(select(Mold.id).limit(1)) is not None
    print("已有模具，保留现有库存资料。" if has_molds else "库存为空，等待导入真实资料；不会自动建立样例模具。")


def main() -> None:
    parser = argparse.ArgumentParser(description="鞋模具仓库开发初始化命令")
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("init-db", help="只在开发库建表")
    admin = sub.add_parser("create-admin", help="交互式创建系统维护员")
    admin.add_argument("--username", required=True)
    admin.add_argument("--person-name", required=True)
    worker = sub.add_parser("create-worker", help="交互式创建领用人员")
    worker.add_argument("--username", required=True)
    worker.add_argument("--person-name", required=True)
    readonly = sub.add_parser("create-readonly", help="交互式创建仓库电脑只读账号")
    readonly.add_argument("--username", required=True)
    seed = sub.add_parser("seed-sample", help="向空开发库注入样例资料")
    seed.add_argument("--sets", type=int, choices=[5, 150], default=5)
    sub.add_parser("bootstrap-local", help="首次创建本机维护员账号；不会自动建立样例资料")
    args = parser.parse_args()
    if args.command == "init-db":
        assert_development()
        engine = make_engine()
        Base.metadata.create_all(engine)
        print("开发库表已初始化；正式环境需使用迁移")
    elif args.command == "create-admin":
        create_user(args.username, args.person_name, "ADMIN")
    elif args.command == "create-worker":
        create_user(args.username, args.person_name, "WORKER")
    elif args.command == "create-readonly":
        create_user(args.username, None, "READONLY")
    elif args.command == "seed-sample":
        seed_sample(args.sets)
    elif args.command == "bootstrap-local":
        bootstrap_local()


if __name__ == "__main__":
    main()
