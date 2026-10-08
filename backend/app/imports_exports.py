from __future__ import annotations

import csv
import hashlib
import io
import json
import re
from collections import Counter, defaultdict
from datetime import timedelta, timezone
from uuid import uuid4
from zoneinfo import ZoneInfo

from fastapi import APIRouter, Depends, Request, Response
from pydantic import BaseModel, Field, ValidationError
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, selectinload

from .auth import AuthContext, api_error, current_context, get_db, require_admin, require_csrf
from .capacity import SHELF_CAPACITY, shelf_counts
from .models import AuditLog, ImportBatch, Location, Mold, MoldModel, MoldSet, Operation, OperationItem, StocktakeSession, User, utc_now
from .mold_metadata import METADATA_FIELDS, STANDARD_SIZES, SHOE_TYPES, MoldMetadata, metadata_dict, mold_identity, normalize_category, normalize_size, set_identity, numeric_size, size_plan


router = APIRouter(prefix="/api", tags=["imports-exports"])
REQUIRED = ("model_code", "model_name", "set_code", "default_location_code", "mold_code", "size_label", "status", "current_location_code")
FIELDS = REQUIRED + ("original_code",) + METADATA_FIELDS + ("mold_number", "shoe_type", "set_sizes")
TEMPLATE_FIELDS = ("mold_number", "shoe_type", "mold_category", "set_sizes", "size_label", "default_location_code", "status", "current_location_code", "manufacturer", "pairs_per_mold", "sole_material", "initial_quarter", "opened_on")
LIMIT_BYTES = 3_000_000
LIMIT_ROWS = 5_000
SHANGHAI = ZoneInfo("Asia/Shanghai")


class CommitInput(BaseModel):
    token: str = Field(min_length=36, max_length=60)
    sha256: str = Field(min_length=64, max_length=64)


def error(row: int, field: str, message: str) -> dict:
    return {"row": row, "field": field, "message": message}


def row_metadata(row: dict) -> MoldMetadata:
    values = {field: row.get(field) or None for field in METADATA_FIELDS}
    pairs = values["pairs_per_mold"]
    if isinstance(pairs, str) and pairs.isascii() and pairs.isdecimal():
        values["pairs_per_mold"] = int(pairs)
    return MoldMetadata(**values)


def parse_csv(raw: bytes) -> tuple[list[dict], list[dict]]:
    if not raw:
        return [], [error(1, "file", "CSV 文件为空")]
    if len(raw) > LIMIT_BYTES:
        raise api_error(413, "IMPORT_TOO_LARGE", "CSV 最大允许 3 MB")
    try:
        source = raw.decode("utf-8-sig")
    except UnicodeDecodeError:
        return [], [error(1, "file", "请将 CSV 保存为 UTF-8 编码")]
    reader = csv.DictReader(io.StringIO(source, newline=""), strict=True)
    if reader.fieldnames is None:
        return [], [error(1, "header", "缺少表头")]
    headers = [name.strip() for name in reader.fieldnames]
    common_headers = ("default_location_code", "size_label", "status", "current_location_code")
    missing = [name for name in common_headers if name not in headers]
    if not {"mold_number", "model_code"}.intersection(headers):
        missing.append("mold_number")
    extra = [name for name in headers if name not in FIELDS]
    if missing or extra or len(headers) != len(set(headers)):
        return [], [error(1, "header", f"表头不符；缺少：{','.join(missing) or '无'}；未知或重复：{','.join(extra) or '无'}")]
    reader.fieldnames = headers
    rows: list[dict] = []
    problems: list[dict] = []
    try:
        for item in reader:
            number = reader.line_num
            if len(rows) >= LIMIT_ROWS:
                return [], [error(number, "file", "每次最多导入 5,000 行")]
            if None in item:
                problems.append(error(number, "row", "列数多于表头"))
                continue
            values = {name: (item.get(name) or "").strip() for name in FIELDS}
            if not any(values.values()):
                continue
            for name in ("model_code", "mold_number", "set_code", "default_location_code", "mold_code", "current_location_code"):
                values[name] = values[name].upper()
            values["status"] = values["status"].upper()
            values["row"] = number
            if values["shoe_type"] and values["shoe_type"] not in SHOE_TYPES:
                problems.append(error(number, "shoe_type", "鞋类须为男鞋、女鞋、男童或女童"))
            standard = bool(values["mold_number"] or values["mold_category"] or not (values["set_code"] and values["mold_code"]))
            if standard:
                style_number = values["mold_number"] or values["model_code"]
                if values["mold_number"] and values["model_code"] and values["mold_number"] != values["model_code"]:
                    problems.append(error(number, "mold_number", "款号与兼容列 model_code 不一致"))
                values["model_code"] = style_number
                values["model_name"] = values["model_name"] or style_number
                try:
                    category = normalize_category(values["mold_category"] or "A模")
                    expected_set = set_identity(style_number, category)
                    values["shoe_type"] = values["shoe_type"] or "男鞋"
                    values["planned_sizes"] = list(size_plan(values["shoe_type"], re.split(r"[、,，;；/\s]+", values["set_sizes"]) if values["set_sizes"] else None))
                    size = numeric_size(values["size_label"])
                    if size not in values["planned_sizes"]:
                        raise ValueError("码数不在该套方案内，请核对鞋类或 set_sizes")
                    expected_mold = mold_identity(style_number, category, size)
                    if values["set_code"] and values["set_code"] != expected_set:
                        problems.append(error(reader.line_num, "set_code", "套身份由款号和 A/B 类别自动生成，请留空或填写 " + expected_set))
                    if values["mold_code"] and values["mold_code"] != expected_mold:
                        problems.append(error(reader.line_num, "mold_code", "单件身份由款号、A/B 和码数自动生成，请留空或填写 " + expected_mold))
                    values.update(set_code=expected_set, mold_code=expected_mold, size_label=size, mold_category=category, set_category=category)
                except ValueError as exc:
                    problems.append(error(reader.line_num, "identity", str(exc)))
            for name in REQUIRED:
                if not values[name]:
                    problems.append(error(reader.line_num, name, "必填项不能为空"))
            number = reader.line_num
            for name, maximum in (("model_code", 80), ("model_name", 120), ("set_code", 80), ("default_location_code", 80), ("mold_code", 80), ("size_label", 30), ("status", 30), ("current_location_code", 80), ("original_code", 100)):
                if len(values[name]) > maximum:
                    problems.append(error(number, name, f"长度不能超过 {maximum} 个字符"))
            if values["status"] not in {"READY", "PENDING_INSPECTION"}:
                problems.append(error(number, "status", "初始状态只能为 READY 或 PENDING_INSPECTION"))
            try:
                values["size_label"] = normalize_size(values["size_label"])
            except ValueError as exc:
                problems.append(error(number, "size_label", str(exc)))
            try:
                values.update(row_metadata(values).model_dump(mode="json"))
            except ValidationError as exc:
                for detail in exc.errors():
                    problems.append(error(number, str(detail["loc"][0]), detail["msg"]))
            rows.append(values)
    except csv.Error:
        return [], [error(reader.line_num, "file", "CSV 格式错误，请检查引号和换行")]
    if not rows:
        problems.append(error(2, "file", "没有可导入的数据行"))
    return rows, problems


def validate_rows(rows: list[dict], db: Session) -> list[dict]:
    problems: list[dict] = []
    locations = {item.code.upper(): item for item in db.scalars(select(Location)).all()}
    shelf_ids = {item.id for item in locations.values() if item.type == "SHELF"}
    occupied = shelf_counts(db, shelf_ids)
    models = {item.code.upper(): item for item in db.scalars(select(MoldModel)).all()}
    existing_sets = {code.upper() for code in db.scalars(select(MoldSet.code)).all()}
    existing_categories = {(item.model.code.upper(), item.mold_category) for item in db.scalars(select(MoldSet)).all() if item.mold_category}
    existing_molds = {code.upper() for code in db.scalars(select(Mold.code)).all()}
    frozen_locations = set(db.scalars(select(StocktakeSession.location_id).where(StocktakeSession.status.in_(["ACTIVE", "SUBMITTED"]))).all())
    set_groups: dict[str, list[dict]] = defaultdict(list)
    model_names: dict[str, str] = {}
    model_types: dict[str, str] = {}
    set_details: dict[str, tuple] = {}
    seen_mold_codes: set[str] = set()
    seen_set_sizes: set[tuple[str, str]] = set()
    for row in rows:
        number = row["row"]
        model_code, set_code, mold_code = row["model_code"], row["set_code"], row["mold_code"]
        set_groups[set_code].append(row)
        if model_code in model_names and model_names[model_code] != row["model_name"]:
            problems.append(error(number, "model_name", "同一款式在文件中的名称不一致"))
        model_names[model_code] = row["model_name"]
        existing_model = models.get(model_code)
        if existing_model and not row.get("set_category") and existing_model.name != row["model_name"]:
            problems.append(error(number, "model_name", "该款式已存在，但名称与现有档案不同"))
        shoe_type = row.get("shoe_type")
        if shoe_type:
            if model_code in model_types and model_types[model_code] != shoe_type:
                problems.append(error(number, "shoe_type", "同一款号的鞋类不一致"))
            if existing_model and existing_model.shoe_type and existing_model.shoe_type != shoe_type:
                problems.append(error(number, "shoe_type", "鞋类与已有款式不一致"))
            model_types[model_code] = shoe_type
        detail = (model_code, row["default_location_code"], row.get("set_category"), shoe_type, tuple(row.get("planned_sizes") or []))
        if set_code in set_details and set_details[set_code] != detail:
            problems.append(error(number, "set_code", "同一套的款号或默认库位不一致"))
        set_details[set_code] = detail
        if row.get("set_category") and (model_code, row["set_category"]) in existing_categories:
            problems.append(error(number, "mold_category", "该款的此 A/B 套别已存在，导入不会覆盖已有套"))
        if set_code in existing_sets:
            problems.append(error(number, "set_code", "该款类别或历史档案已存在；导入不会覆盖或补齐历史套"))
        if mold_code in seen_mold_codes or mold_code in existing_molds:
            problems.append(error(number, "mold_code", "模具编号重复或已存在"))
        seen_mold_codes.add(mold_code)
        slot = (set_code, row["size_label"])
        if slot in seen_set_sizes:
            problems.append(error(number, "size_label", "同一套内尺码重复"))
        seen_set_sizes.add(slot)
        default = locations.get(row["default_location_code"])
        current = locations.get(row["current_location_code"])
        if default is None or not default.active or default.type != "SHELF":
            problems.append(error(number, "default_location_code", "默认库位不存在、停用或不是普通库位"))
        elif default.id in frozen_locations:
            problems.append(error(number, "default_location_code", "默认库位正在盘点"))
        if current is None or not current.active:
            problems.append(error(number, "current_location_code", "当前位置不存在或已停用"))
        elif (row["status"] == "READY" and current.type != "SHELF") or (row["status"] == "PENDING_INSPECTION" and current.type not in {"SHELF", "INSPECTION"}):
            problems.append(error(number, "current_location_code", "当前位置类型与初始状态不一致"))
        elif current.id in frozen_locations:
            problems.append(error(number, "current_location_code", "当前位置正在盘点"))
        if current is not None and current.type == "SHELF":
            occupied[current.id] = occupied.get(current.id, 0) + 1
            if occupied[current.id] > SHELF_CAPACITY:
                problems.append(error(number, "current_location_code", f"库位 {current.code} 最多存放 {SHELF_CAPACITY} 个模具，含本行将达到 {occupied[current.id]} 个"))
    for group in set_groups.values():
        plan = group[0].get("planned_sizes") or list(STANDARD_SIZES)
        count = len(plan) if group[0].get("set_category") else 10
        if len(group) != count:
            for row in group:
                problems.append(error(row["row"], "size_label", f"该套方案需要 {count} 个码数，当前 {len(group)} 个"))
        if group[0].get("set_category") and {row["size_label"] for row in group} != set(plan):
            problems.append(error(group[0]["row"], "size_label", "每套必须完整包含：" + "、".join(plan)))
    return problems


def csv_response(filename: str, headers: list[str], records: list[list[object]]) -> Response:
    output = io.StringIO(newline="")
    writer = csv.writer(output)
    writer.writerow(headers)
    for record in records:
        writer.writerow([safe_cell(item) for item in record])
    return Response(content="\ufeff" + output.getvalue(), media_type="text/csv; charset=utf-8", headers={"Content-Disposition": f'attachment; filename="{filename}"', "X-Content-Type-Options": "nosniff"})


def safe_cell(value: object) -> str:
    result = "" if value is None else str(value)
    return "'" + result if result.lstrip(" \t\r\n").startswith(("=", "+", "-", "@")) else result


def local_time(value) -> str:  # type: ignore[no-untyped-def]
    if value is None:
        return ""
    aware = value.replace(tzinfo=timezone.utc) if value.tzinfo is None else value
    return aware.astimezone(SHANGHAI).strftime("%Y-%m-%d %H:%M:%S")


@router.get("/imports/template")
def import_template(context: AuthContext = Depends(current_context)) -> Response:
    require_admin(context)
    return csv_response("mold-import-template.csv", list(TEMPLATE_FIELDS), [])


@router.post("/imports/preview")
async def preview_import(request: Request, context: AuthContext = Depends(require_csrf), db: Session = Depends(get_db)) -> dict:
    require_admin(context)
    raw = await request.body()
    rows, errors = parse_csv(raw)
    if rows:
        errors.extend(validate_rows(rows, db))
    if errors:
        return {"valid": False, "row_count": len(rows), "errors": errors}
    token = str(uuid4())
    sha = hashlib.sha256(raw).hexdigest()
    batch = ImportBatch(token=token, sha256=sha, created_by_user_id=context.user.id, status="PREVIEWED", row_count=len(rows), payload_json=json.dumps(rows, ensure_ascii=False), expires_at=utc_now() + timedelta(minutes=30))
    db.add(batch)
    db.commit()
    return {"valid": True, "token": token, "sha256": sha, "row_count": len(rows), "model_count": len({row["model_code"] for row in rows}), "set_count": len({row["set_code"] for row in rows}), "expires_at": batch.expires_at.isoformat(), "errors": []}


@router.post("/imports/commit")
def commit_import(payload: CommitInput, context: AuthContext = Depends(require_csrf), db: Session = Depends(get_db)) -> dict:
    require_admin(context)
    batch = db.scalar(select(ImportBatch).where(ImportBatch.token == payload.token).with_for_update().execution_options(populate_existing=True))
    if batch is None or batch.created_by_user_id != context.user.id or batch.sha256 != payload.sha256:
        raise api_error(404, "IMPORT_PREVIEW_NOT_FOUND", "预览记录不存在或不属于当前账号")
    if batch.status == "COMMITTED":
        return json.loads(batch.result_json or "{}")
    expires = batch.expires_at.replace(tzinfo=timezone.utc) if batch.expires_at.tzinfo is None else batch.expires_at
    if expires <= utc_now():
        raise api_error(409, "IMPORT_PREVIEW_EXPIRED", "预览已超过 30 分钟，请重新预览")
    rows = json.loads(batch.payload_json)
    location_codes = sorted({row["default_location_code"] for row in rows} | {row["current_location_code"] for row in rows})
    locked_locations = db.scalars(select(Location).where(Location.code.in_(location_codes)).order_by(Location.id).with_for_update().execution_options(populate_existing=True)).all()
    if len(locked_locations) != len(location_codes):
        raise api_error(409, "IMPORT_DATA_CHANGED", "库位在预览后发生变化，请重新预览")
    problems = validate_rows(rows, db)
    if problems:
        raise api_error(409, "IMPORT_DATA_CHANGED", "预览后资料已变化，请重新预览；首个错误：" + problems[0]["message"])
    locations = {item.code.upper(): item for item in locked_locations}
    existing_models = {item.code.upper(): item for item in db.scalars(select(MoldModel)).all()}
    by_set: dict[str, list[dict]] = defaultdict(list)
    for row in rows:
        by_set[row["set_code"]].append(row)
    try:
        for row in rows:
            if row["model_code"] not in existing_models:
                model = MoldModel(code=row["model_code"], name=row["model_name"], shoe_type=row.get("shoe_type") or None)
                db.add(model)
                existing_models[row["model_code"]] = model
        for row in rows:
            model = existing_models[row["model_code"]]
            if model.shoe_type is None and row.get("shoe_type"):
                model.shoe_type = row["shoe_type"]
        db.flush()
        operation_ids: list[int] = []
        for set_code, group in by_set.items():
            first = group[0]
            mold_set = MoldSet(code=set_code, model_id=existing_models[first["model_code"]].id, mold_category=first.get("set_category"), size_labels=json.dumps(first.get("planned_sizes") or STANDARD_SIZES) if first.get("set_category") else None, default_location_id=locations[first["default_location_code"]].id)
            db.add(mold_set)
            db.flush()
            operation = Operation(request_id=str(uuid4()), payload_hash=batch.sha256, type="INITIALIZE", actor_user_id=context.user.id, target_location_id=mold_set.default_location_id, reason=f"CSV 初始建档批次 {batch.token}")
            db.add(operation)
            for row in group:
                mold = Mold(code=row["mold_code"], original_code=row["original_code"] or None, set_id=mold_set.id, size_label=row["size_label"], status=row["status"], current_location_id=locations[row["current_location_code"]].id, is_current=True, version=1, **row_metadata(row).model_dump())
                db.add(mold)
                db.flush()
                db.add(OperationItem(operation=operation, mold_id=mold.id, before_status="NOT_REGISTERED", after_status=mold.status, before_location_id=None, after_location_id=mold.current_location_id, before_custodian_id=None, after_custodian_id=None, before_version=0, after_version=1))
            db.flush()
            operation_ids.append(operation.id)
        result = {"batch_id": batch.id, "token": batch.token, "model_count": len({row["model_code"] for row in rows}), "set_count": len(by_set), "mold_count": len(rows), "operation_ids": operation_ids}
        batch.status = "COMMITTED"
        batch.committed_at = utc_now()
        batch.result_json = json.dumps(result, ensure_ascii=False)
        db.add(AuditLog(actor_user_id=context.user.id, action="IMPORT_COMMIT", entity=batch.token, after=f"{len(by_set)} sets / {len(rows)} molds", reason="CSV 初始建档"))
        db.commit()
    except IntegrityError:
        db.rollback()
        raise api_error(409, "IMPORT_CONFLICT", "提交时编号或资料发生冲突，整批未写入；请重新预览") from None
    return result


def require_exporter(context: AuthContext) -> None:
    if context.user.role not in {"ADMIN", "WORKER"}:
        raise api_error(403, "FORBIDDEN", "当前账号不能导出资料")


@router.get("/exports/inventory")
def export_inventory(context: AuthContext = Depends(current_context), db: Session = Depends(get_db)) -> Response:
    require_exporter(context)
    molds = db.scalars(select(Mold).where(Mold.is_current.is_(True)).order_by(Mold.code)).all()
    rows = [[item.code, item.original_code, item.set.model.code, item.set.model.name, item.set.model.shoe_type, item.set.code, item.size_label, item.status, item.current_location.code, item.set.default_location.code, item.custodian.name if item.custodian else "", item.version, *metadata_dict(item).values()] for item in molds]
    return csv_response("warehouse-inventory.csv", ["单件身份编号", "原编号", "模具编号（款号）", "模具名称", "鞋类", "套身份编号", "码数", "状态", "当前位置", "默认库位", "当前责任人", "版本", "模具厂家", "模具类别", "排模双数", "鞋底材质", "初始季度", "开制日期"], rows)


@router.get("/exports/operations")
def export_operations(context: AuthContext = Depends(current_context), db: Session = Depends(get_db)) -> Response:
    require_exporter(context)
    query = select(Operation).options(selectinload(Operation.items).selectinload(OperationItem.mold), selectinload(Operation.actor).selectinload(User.person), selectinload(Operation.target_location)).order_by(Operation.id)
    if context.user.role == "WORKER":
        query = query.where(Operation.actor_user_id == context.user.id)
    operations = db.scalars(query).all()
    locations = {item.id: item.code for item in db.scalars(select(Location)).all()}
    rows: list[list[object]] = []
    for operation in operations:
        actor = operation.actor.person.name if operation.actor.person else operation.actor.username
        for item in operation.items:
            rows.append([operation.id, operation.request_id, local_time(operation.created_at), operation.type, actor, operation.target_location.code, operation.reason, item.mold.code, item.before_status, item.after_status, locations.get(item.before_location_id, ""), locations.get(item.after_location_id, ""), item.before_version, item.after_version, item.note])
    return csv_response("warehouse-operations.csv", ["单据号", "请求编号", "操作时间(北京时间)", "类型", "操作人", "目标位置", "原因", "模具编号", "原状态", "新状态", "原位置", "新位置", "原版本", "新版本", "逐件说明"], rows)
