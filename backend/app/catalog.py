from __future__ import annotations

from collections import defaultdict
import hashlib
import json
from typing import Literal
from uuid import uuid4

from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field, model_validator
from sqlalchemy import func, or_, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, selectinload

from .auth import AuthContext, api_error, current_context, get_db, require_admin, require_csrf
from .models import AuditLog, AuthorizedDevice, LabelPrintBatch, Location, LoginSession, Mold, MoldModel, MoldSet, Operation, OperationItem, Person, StocktakeAdjustment, StocktakeExpected, StocktakeScan, StocktakeSession, User, utc_now

router = APIRouter(prefix="/api", tags=["catalog"])


class PersonInput(BaseModel):
    name: str = Field(min_length=1, max_length=80)
    employee_code: str | None = Field(default=None, max_length=50)


class LocationInput(BaseModel):
    code: str | None = Field(default=None, max_length=80)
    name: str | None = Field(default=None, max_length=120)
    type: Literal["SHELF", "LINE", "INSPECTION", "REPAIR", "SCRAP", "UNKNOWN"]
    zone: str | None = Field(default=None, max_length=20)
    rack: str | None = Field(default=None, max_length=20)
    level: str | None = Field(default=None, max_length=20)

    @model_validator(mode="after")
    def resolve_identity(self) -> "LocationInput":
        if self.type == "SHELF":
            zone = (self.zone or "").strip().upper()
            rack = (self.rack or "").strip()
            level = (self.level or "").strip()
            if not zone or not zone.isalnum() or not rack.isdecimal() or not level.isdecimal():
                raise ValueError("普通库位须填写区域、数字货架和数字层")
            rack_number, level_number = int(rack), int(level)
            if rack_number < 1 or level_number < 1:
                raise ValueError("货架和层须为正整数")
            self.zone = zone
            self.rack = str(rack_number)
            self.level = str(level_number)
            self.code = f"{zone}-{rack_number:02d}-{level_number}"
            self.name = f"{zone}区{rack_number}号架{level_number}层"
        else:
            self.code = (self.code or "").strip()
            self.name = (self.name or "").strip()
            if not self.code or not self.name:
                raise ValueError("编号和名称不能为空")
        return self


class ModelInput(BaseModel):
    code: str = Field(min_length=1, max_length=80)
    name: str = Field(min_length=1, max_length=120)
    notes: str | None = None


class SetInput(BaseModel):
    code: str = Field(min_length=1, max_length=80)
    model_id: int = Field(gt=0)
    default_location_id: int = Field(gt=0)


class MoldInput(BaseModel):
    code: str = Field(min_length=1, max_length=80)
    set_id: int = Field(gt=0)
    size_label: str = Field(min_length=1, max_length=30)
    original_code: str | None = Field(default=None, max_length=100)
    status: Literal["READY", "PENDING_INSPECTION"] = "READY"
    current_location_id: int = Field(gt=0)


class ScanInput(BaseModel):
    raw_code: str = Field(min_length=1, max_length=200)


class DefaultLocationInput(BaseModel):
    location_id: int = Field(gt=0)
    reason: str = Field(min_length=3, max_length=300)


class PersonActiveInput(BaseModel):
    active: bool
    reason: str = Field(min_length=3, max_length=300)


def mold_dict(mold: Mold) -> dict:
    return {
        "id": mold.id,
        "code": mold.code,
        "original_code": mold.original_code,
        "set_id": mold.set_id,
        "set_code": mold.set.code,
        "model_code": mold.set.model.code,
        "name": mold.set.model.name,
        "size_label": mold.size_label,
        "status": mold.status,
        "current_location_id": mold.current_location_id,
        "current_location": mold.current_location.code,
        "default_location_id": mold.set.default_location_id,
        "default_location": mold.set.default_location.code,
        "custodian_person_id": mold.custodian_person_id,
        "custodian": mold.custodian.name if mold.custodian else None,
        "version": mold.version,
    }


def save_or_conflict(db: Session, code: str, message: str) -> None:
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        raise api_error(409, code, message) from None


def flush_or_conflict(db: Session, code: str, message: str) -> None:
    try:
        db.flush()
    except IntegrityError:
        db.rollback()
        raise api_error(409, code, message) from None


@router.get("/people")
def list_people(_context: AuthContext = Depends(current_context), db: Session = Depends(get_db)) -> list[dict]:
    return [{"id": item.id, "name": item.name, "employee_code": item.employee_code, "active": item.active} for item in db.scalars(select(Person).order_by(Person.id)).all()]


@router.post("/people")
def create_person(payload: PersonInput, context: AuthContext = Depends(require_csrf), db: Session = Depends(get_db)) -> dict:
    require_admin(context)
    person = Person(name=payload.name.strip(), employee_code=payload.employee_code)
    db.add(person)
    flush_or_conflict(db, "PERSON_CONFLICT", "人员编号已存在")
    db.add(AuditLog(actor_user_id=context.user.id, action="PERSON_CREATE", entity=str(person.id), after=person.name))
    save_or_conflict(db, "PERSON_CONFLICT", "人员编号已存在")
    return {"id": person.id, "name": person.name}


@router.delete("/people/{person_id}")
def delete_person(person_id: int, context: AuthContext = Depends(require_csrf), db: Session = Depends(get_db)) -> dict:
    require_admin(context)
    person = db.scalar(select(Person).where(Person.id == person_id).with_for_update())
    if person is None:
        raise api_error(404, "PERSON_NOT_FOUND", "人员不存在")
    if db.scalar(select(User.id).where(User.person_id == person_id).limit(1)) is not None:
        raise api_error(409, "PERSON_IN_USE", "人员已关联账号，请先处理账号")
    if db.scalar(select(Mold.id).where(Mold.custodian_person_id == person_id).limit(1)) is not None or db.scalar(select(OperationItem.id).where(or_(OperationItem.before_custodian_id == person_id, OperationItem.after_custodian_id == person_id)).limit(1)) is not None:
        raise api_error(409, "PERSON_IN_USE", "人员已关联模具或流转记录，不能删除")
    db.delete(person)
    db.add(AuditLog(actor_user_id=context.user.id, action="PERSON_DELETE", entity=str(person_id), before=person.name))
    save_or_conflict(db, "PERSON_IN_USE", "人员已被业务记录引用，不能删除")
    return {"id": person_id, "name": person.name}


@router.patch("/people/{person_id}/active")
def set_person_active(person_id: int, payload: PersonActiveInput, context: AuthContext = Depends(require_csrf), db: Session = Depends(get_db)) -> dict:
    require_admin(context)
    if context.user.person_id == person_id and not payload.active:
        raise api_error(409, "CANNOT_DISABLE_SELF", "不能停用当前维护员对应的人员")
    person = db.scalar(select(Person).where(Person.id == person_id).with_for_update())
    if person is None:
        raise api_error(404, "PERSON_NOT_FOUND", "人员不存在")
    if person.active == payload.active:
        raise api_error(409, "PERSON_UNCHANGED", "人员状态没有变化")
    before = "启用" if person.active else "停用"
    person.active = payload.active
    if not payload.active:
        account = db.scalar(select(User).where(User.person_id == person_id))
        if account is not None:
            for login in db.scalars(select(LoginSession).where(LoginSession.user_id == account.id, LoginSession.revoked_at.is_(None))).all():
                login.revoked_at = utc_now()
            for device in db.scalars(select(AuthorizedDevice).where(AuthorizedDevice.user_id == account.id, AuthorizedDevice.revoked_at.is_(None))).all():
                device.authorized = False
                device.revoked_at = utc_now()
    db.add(AuditLog(actor_user_id=context.user.id, action="PERSON_ACTIVE", entity=str(person_id), before=before, after="启用" if payload.active else "停用", reason=payload.reason.strip()))
    db.commit()
    return {"id": person.id, "active": person.active}


@router.get("/locations")
def list_locations(_context: AuthContext = Depends(current_context), db: Session = Depends(get_db)) -> list[dict]:
    return [{"id": item.id, "code": item.code, "name": item.name, "type": item.type, "zone": item.zone, "rack": item.rack, "level": item.level, "active": item.active} for item in db.scalars(select(Location).order_by(Location.code)).all()]


@router.post("/locations")
def create_location(payload: LocationInput, context: AuthContext = Depends(require_csrf), db: Session = Depends(get_db)) -> dict:
    require_admin(context)
    location = Location(**payload.model_dump())
    db.add(location)
    flush_or_conflict(db, "LOCATION_CONFLICT", "位置编号已存在")
    db.add(AuditLog(actor_user_id=context.user.id, action="LOCATION_CREATE", entity=location.code, after=location.name))
    save_or_conflict(db, "LOCATION_CONFLICT", "位置编号已存在")
    return {"id": location.id, "code": location.code}


@router.delete("/locations/{location_id}")
def delete_location(location_id: int, context: AuthContext = Depends(require_csrf), db: Session = Depends(get_db)) -> dict:
    require_admin(context)
    location = db.scalar(select(Location).where(Location.id == location_id).with_for_update())
    if location is None:
        raise api_error(404, "LOCATION_NOT_FOUND", "位置不存在")
    references = (
        (MoldSet, MoldSet.default_location_id == location_id, "模具套的默认库位"),
        (Mold, Mold.current_location_id == location_id, "模具的当前位置"),
        (StocktakeSession, StocktakeSession.location_id == location_id, "盘点记录"),
        (Operation, Operation.target_location_id == location_id, "流转记录"),
    )
    for model, condition, description in references:
        if db.scalar(select(model.id).where(condition).limit(1)) is not None:
            raise api_error(409, "LOCATION_IN_USE", f"位置已被{description}引用，不能删除")
    if db.scalar(select(OperationItem.id).where(or_(OperationItem.before_location_id == location_id, OperationItem.after_location_id == location_id)).limit(1)) is not None:
        raise api_error(409, "LOCATION_IN_USE", "位置已被流转记录引用，不能删除")
    if any(location.code.upper() in (code.upper() for code in json.loads(record.codes_json)) for record in db.scalars(select(LabelPrintBatch).where(LabelPrintBatch.kind == "LOCATION")).all()):
        raise api_error(409, "LOCATION_IN_USE", "位置已打印标签，不能删除")
    db.delete(location)
    db.add(AuditLog(actor_user_id=context.user.id, action="LOCATION_DELETE", entity=location.code, before=location.name))
    save_or_conflict(db, "LOCATION_IN_USE", "位置已被业务记录引用，不能删除")
    return {"id": location_id, "code": location.code}


@router.get("/models")
def list_models(_context: AuthContext = Depends(current_context), db: Session = Depends(get_db)) -> list[dict]:
    return [{"id": item.id, "code": item.code, "name": item.name, "notes": item.notes} for item in db.scalars(select(MoldModel).order_by(MoldModel.code)).all()]


@router.post("/models")
def create_model(payload: ModelInput, context: AuthContext = Depends(require_csrf), db: Session = Depends(get_db)) -> dict:
    require_admin(context)
    model = MoldModel(**payload.model_dump())
    db.add(model)
    flush_or_conflict(db, "MODEL_CONFLICT", "型号编号已存在")
    db.add(AuditLog(actor_user_id=context.user.id, action="MODEL_CREATE", entity=model.code, after=model.name))
    save_or_conflict(db, "MODEL_CONFLICT", "型号编号已存在")
    return {"id": model.id, "code": model.code}


@router.delete("/models/{model_id}")
def delete_model(model_id: int, context: AuthContext = Depends(require_csrf), db: Session = Depends(get_db)) -> dict:
    require_admin(context)
    model = db.scalar(select(MoldModel).where(MoldModel.id == model_id).with_for_update())
    if model is None:
        raise api_error(404, "MODEL_NOT_FOUND", "型号不存在")
    if db.scalar(select(MoldSet.id).where(MoldSet.model_id == model_id).limit(1)) is not None:
        raise api_error(409, "MODEL_IN_USE", "型号已关联模具套，请先处理模具套")
    db.delete(model)
    db.add(AuditLog(actor_user_id=context.user.id, action="MODEL_DELETE", entity=model.code, before=model.name))
    save_or_conflict(db, "MODEL_IN_USE", "型号已被业务资料引用，不能删除")
    return {"id": model_id, "code": model.code}


@router.get("/sets")
def list_sets(_context: AuthContext = Depends(current_context), db: Session = Depends(get_db)) -> list[dict]:
    sets = db.scalars(select(MoldSet).order_by(MoldSet.code)).all()
    molds = db.scalars(select(Mold).where(Mold.is_current.is_(True))).all()
    by_set: dict[int, list[Mold]] = defaultdict(list)
    for mold in molds:
        by_set[mold.set_id].append(mold)
    return [{"id": item.id, "code": item.code, "model_code": item.model.code, "name": item.model.name, "default_location": item.default_location.code, "size_count": len(by_set[item.id]), "complete": len(by_set[item.id]) == 10, "active": item.active} for item in sets]


@router.post("/sets")
def create_set(payload: SetInput, context: AuthContext = Depends(require_csrf), db: Session = Depends(get_db)) -> dict:
    require_admin(context)
    model = db.get(MoldModel, payload.model_id)
    location = db.get(Location, payload.default_location_id)
    if model is None or location is None or not location.active or location.type != "SHELF":
        raise api_error(422, "SET_REFERENCE_INVALID", "型号或默认库位无效")
    mold_set = MoldSet(**payload.model_dump())
    db.add(mold_set)
    flush_or_conflict(db, "SET_CONFLICT", "套号已存在")
    db.add(AuditLog(actor_user_id=context.user.id, action="SET_CREATE", entity=mold_set.code, after=location.code))
    save_or_conflict(db, "SET_CONFLICT", "套号已存在")
    return {"id": mold_set.id, "code": mold_set.code, "complete": False}


@router.delete("/sets/{set_id}")
def delete_set(set_id: int, context: AuthContext = Depends(require_csrf), db: Session = Depends(get_db)) -> dict:
    require_admin(context)
    mold_set = db.scalar(select(MoldSet).where(MoldSet.id == set_id).with_for_update())
    if mold_set is None:
        raise api_error(404, "SET_NOT_FOUND", "模具套不存在")
    if db.scalar(select(Mold.id).where(Mold.set_id == set_id).limit(1)) is not None:
        raise api_error(409, "SET_IN_USE", "模具套已有单模具，请先处理单模具")
    db.delete(mold_set)
    db.add(AuditLog(actor_user_id=context.user.id, action="SET_DELETE", entity=mold_set.code, before=mold_set.default_location.code))
    save_or_conflict(db, "SET_IN_USE", "模具套已被业务资料引用，不能删除")
    return {"id": set_id, "code": mold_set.code}


@router.patch("/sets/{set_id}/default-location")
def change_default_location(set_id: int, payload: DefaultLocationInput, context: AuthContext = Depends(require_csrf), db: Session = Depends(get_db)) -> dict:
    require_admin(context)
    mold_set = db.scalar(select(MoldSet).where(MoldSet.id == set_id).with_for_update())
    target = db.get(Location, payload.location_id)
    if mold_set is None:
        raise api_error(404, "SET_NOT_FOUND", "模具套不存在")
    if target is None or not target.active or target.type != "SHELF":
        raise api_error(422, "LOCATION_INVALID", "默认库位必须是有效普通库位")
    if mold_set.default_location_id == target.id:
        raise api_error(409, "DEFAULT_UNCHANGED", "默认库位没有变化")
    before = mold_set.default_location.code
    mold_set.default_location_id = target.id
    db.add(AuditLog(actor_user_id=context.user.id, action="SET_DEFAULT_LOCATION", entity=mold_set.code, before=before, after=target.code, reason=payload.reason.strip()))
    db.commit()
    return {"id": mold_set.id, "code": mold_set.code, "default_location": target.code, "physical_location_unchanged": True}


@router.get("/molds")
def list_molds(q: str = "", status: str | None = None, offset: int = 0, limit: int = 50, _context: AuthContext = Depends(current_context), db: Session = Depends(get_db)) -> dict:
    if offset < 0 or limit < 1 or limit > 100:
        raise api_error(422, "BAD_PAGINATION", "分页参数无效")
    query = select(Mold).where(Mold.is_current.is_(True))
    if status:
        query = query.where(Mold.status == status)
    if q:
        pattern = f"%{q.strip()}%"
        query = query.join(Mold.set).join(MoldSet.model).where(or_(Mold.code.ilike(pattern), MoldSet.code.ilike(pattern), MoldModel.code.ilike(pattern), MoldModel.name.ilike(pattern), Mold.size_label.ilike(pattern)))
    total = db.scalar(select(func.count()).select_from(query.subquery())) or 0
    page = db.scalars(query.options(selectinload(Mold.set).selectinload(MoldSet.model), selectinload(Mold.set).selectinload(MoldSet.default_location), selectinload(Mold.current_location), selectinload(Mold.custodian)).order_by(Mold.id).offset(offset).limit(limit)).all()
    return {"total": total, "items": [mold_dict(item) for item in page]}


@router.get("/molds/{mold_id}")
def mold_detail(mold_id: int, _context: AuthContext = Depends(current_context), db: Session = Depends(get_db)) -> dict:
    mold = db.get(Mold, mold_id)
    if mold is None:
        raise api_error(404, "MOLD_NOT_FOUND", "模具不存在")
    return mold_dict(mold)


@router.post("/molds")
def create_mold(payload: MoldInput, context: AuthContext = Depends(require_csrf), db: Session = Depends(get_db)) -> dict:
    require_admin(context)
    mold_set = db.scalar(select(MoldSet).where(MoldSet.id == payload.set_id).with_for_update())
    location = db.scalar(select(Location).where(Location.id == payload.current_location_id).with_for_update().execution_options(populate_existing=True))
    if mold_set is None or not mold_set.active or location is None or not location.active:
        raise api_error(422, "MOLD_REFERENCE_INVALID", "模具套或位置无效")
    frozen = db.scalar(select(StocktakeSession.id).where(StocktakeSession.location_id == location.id, StocktakeSession.status.in_(["ACTIVE", "SUBMITTED"])).limit(1))
    if frozen is not None:
        raise api_error(409, "LOCATION_STOCKTAKE_FROZEN", "该库位正在盘点，暂不能新增模具")
    if payload.status == "READY" and location.type != "SHELF" or payload.status == "PENDING_INSPECTION" and location.type not in {"SHELF", "INSPECTION"}:
        raise api_error(422, "STATUS_LOCATION_INVALID", "状态与位置类型不一致")
    current_count = len(db.scalars(select(Mold).where(Mold.set_id == mold_set.id, Mold.is_current.is_(True))).all())
    if current_count >= 10:
        raise api_error(409, "SET_FULL", "该套已有 10 个有效模具")
    mold = Mold(**payload.model_dump(), is_current=True, version=1)
    db.add(mold)
    flush_or_conflict(db, "MOLD_CONFLICT", "模具编号或套内尺码重复")
    fingerprint = hashlib.sha256(json.dumps(payload.model_dump(), ensure_ascii=False, sort_keys=True).encode("utf-8")).hexdigest()
    operation = Operation(request_id=str(uuid4()), payload_hash=fingerprint, type="INITIALIZE", actor_user_id=context.user.id, target_location_id=location.id, reason="维护员逐件建档")
    db.add(operation)
    db.add(OperationItem(operation=operation, mold_id=mold.id, before_status="NOT_REGISTERED", after_status=mold.status, before_location_id=None, after_location_id=location.id, before_custodian_id=None, after_custodian_id=None, before_version=0, after_version=1))
    db.add(AuditLog(actor_user_id=context.user.id, action="MOLD_CREATE", entity=mold.code, after=location.code))
    save_or_conflict(db, "MOLD_CONFLICT", "模具编号或套内尺码重复")
    return mold_dict(mold)


@router.delete("/molds/{mold_id}")
def delete_mold(mold_id: int, context: AuthContext = Depends(require_csrf), db: Session = Depends(get_db)) -> dict:
    require_admin(context)
    mold = db.scalar(select(Mold).where(Mold.id == mold_id).with_for_update())
    if mold is None:
        raise api_error(404, "MOLD_NOT_FOUND", "模具不存在")
    for model in (StocktakeExpected, StocktakeScan, StocktakeAdjustment):
        if db.scalar(select(model.id).where(model.mold_id == mold_id).limit(1)) is not None:
            raise api_error(409, "MOLD_IN_USE", "模具已有盘点记录，不能删除")
    if any(mold.code.upper() in (code.upper() for code in json.loads(record.codes_json)) for record in db.scalars(select(LabelPrintBatch).where(LabelPrintBatch.kind == "MOLD")).all()):
        raise api_error(409, "MOLD_IN_USE", "模具已打印标签，不能删除")
    items = db.scalars(select(OperationItem).where(OperationItem.mold_id == mold_id)).all()
    if len(items) != 1:
        raise api_error(409, "MOLD_IN_USE", "模具已有流转记录，不能删除")
    operation = db.get(Operation, items[0].operation_id)
    if operation is None or operation.type != "INITIALIZE" or operation.reason != "维护员逐件建档" or db.scalar(select(OperationItem.id).where(OperationItem.operation_id == operation.id, OperationItem.id != items[0].id).limit(1)) is not None:
        raise api_error(409, "MOLD_IN_USE", "模具已有业务记录，不能删除")
    code = mold.code
    db.delete(operation)
    db.delete(mold)
    db.add(AuditLog(actor_user_id=context.user.id, action="MOLD_DELETE", entity=code, before=f"撤销逐件建档 #{operation.id}"))
    save_or_conflict(db, "MOLD_IN_USE", "模具已被业务记录引用，不能删除")
    return {"id": mold_id, "code": code}


@router.post("/scan/resolve")
def resolve_scan(payload: ScanInput, _context: AuthContext = Depends(current_context), db: Session = Depends(get_db)) -> dict:
    raw = payload.raw_code.strip().upper()
    if raw.startswith("MOLD:"):
        code = raw[5:]
    elif raw.startswith("LOC:"):
        code = raw[4:]
        location = db.scalar(select(Location).where(func.upper(Location.code) == code))
        if location is None:
            raise api_error(404, "LOCATION_NOT_FOUND", "找不到这个库位")
        return {"kind": "LOCATION", "location": {"id": location.id, "code": location.code, "name": location.name, "type": location.type}}
    elif ":" in raw:
        raise api_error(422, "SCAN_PREFIX_INVALID", "二维码类型无法识别")
    else:
        code = raw
        location = db.scalar(select(Location).where(func.upper(Location.code) == code))
        if location is not None:
            return {"kind": "LOCATION", "location": {"id": location.id, "code": location.code, "name": location.name, "type": location.type}}
    mold = db.scalar(select(Mold).where(func.upper(Mold.code) == code, Mold.is_current.is_(True)))
    if mold is None:
        raise api_error(404, "MOLD_NOT_FOUND", "找不到这个模具编号")
    return {"kind": "MOLD", "mold": mold_dict(mold)}


@router.get("/dashboard")
def dashboard(_context: AuthContext = Depends(current_context), db: Session = Depends(get_db)) -> dict:
    molds = db.scalars(select(Mold).where(Mold.is_current.is_(True))).all()
    by_set: dict[int, list[Mold]] = defaultdict(list)
    for mold in molds:
        by_set[mold.set_id].append(mold)
    ready_sets = sum(len(group) == 10 and all(mold.status == "READY" and mold.current_location_id == mold.set.default_location_id for mold in group) for group in by_set.values())
    return {"total_molds": len(molds), "ready_molds": sum(mold.status == "READY" for mold in molds), "in_use_molds": sum(mold.status == "IN_USE" for mold in molds), "exception_molds": sum(mold.status not in {"READY", "IN_USE"} for mold in molds), "ready_sets": ready_sets, "total_sets": len(by_set)}


@router.get("/set-matrix")
def set_matrix(_context: AuthContext = Depends(current_context), db: Session = Depends(get_db)) -> list[dict]:
    sets = db.scalars(select(MoldSet).order_by(MoldSet.code)).all()
    molds = db.scalars(select(Mold).where(Mold.is_current.is_(True)).order_by(Mold.size_label)).all()
    by_set: dict[int, list[Mold]] = defaultdict(list)
    for mold in molds:
        by_set[mold.set_id].append(mold)
    return [{"set_id": item.id, "set_code": item.code, "name": item.model.name, "model_code": item.model.code, "default_location": item.default_location.code, "complete": len(by_set[item.id]) == 10, "items": [mold_dict(mold) for mold in by_set[item.id]]} for item in sets]


@router.get("/production-lines/summary")
def production_lines(_context: AuthContext = Depends(current_context), db: Session = Depends(get_db)) -> list[dict]:
    lines = db.scalars(select(Location).where(Location.type == "LINE", Location.active.is_(True)).order_by(Location.code)).all()
    molds = db.scalars(select(Mold).where(Mold.status == "IN_USE", Mold.is_current.is_(True))).all()
    return [{"line_id": line.id, "line_code": line.code, "sets": [{"set_code": mold_set.code, "name": mold_set.model.name, "mold_count": len(group), "sizes": [mold.size_label for mold in group], "custodians": sorted({mold.custodian.name if mold.custodian else "未记录" for mold in group})} for mold_set, group in _group_line_sets(molds, line.id)]} for line in lines]


def _group_line_sets(molds: list[Mold], location_id: int) -> list[tuple[MoldSet, list[Mold]]]:
    groups: dict[int, list[Mold]] = defaultdict(list)
    for mold in molds:
        if mold.current_location_id == location_id:
            groups[mold.set_id].append(mold)
    return [(group[0].set, group) for group in groups.values()]
