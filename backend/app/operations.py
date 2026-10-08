from __future__ import annotations

import hashlib
import json
from datetime import timezone
from typing import Literal
from uuid import UUID

from fastapi import APIRouter, Depends, Request
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session
from sqlalchemy.orm.exc import StaleDataError

from .auth import AuthContext, api_error, current_context, get_db, require_admin, require_csrf, require_device, require_operator
from .capacity import ensure_shelf_capacity
from .mold_metadata import set_complete
from .models import AuditLog, Location, Mold, MoldSet, Operation, OperationItem, StocktakeSession

router = APIRouter(prefix="/api/operations", tags=["operations"])


class ItemInput(BaseModel):
    mold_id: int = Field(gt=0)
    expected_version: int = Field(gt=0)
    return_condition: Literal["READY", "PENDING_INSPECTION", "IN_REPAIR"] = "READY"
    exception_location_id: int | None = Field(default=None, gt=0)
    note: str | None = Field(default=None, max_length=300)


class OperationInput(BaseModel):
    request_id: UUID
    type: Literal["ISSUE", "RETURN", "MOVE", "TRANSFER"]
    target_location_id: int = Field(gt=0)
    items: list[ItemInput] = Field(min_length=1, max_length=100)
    reason: str | None = Field(default=None, max_length=300)


class CorrectionInput(BaseModel):
    request_id: UUID
    reason: str = Field(min_length=3, max_length=300)


def response_for(operation: Operation) -> dict:
    return {
        "id": operation.id,
        "request_id": operation.request_id,
        "type": operation.type,
        "actor_user_id": operation.actor_user_id,
        "actor_name": operation.actor.person.name if operation.actor.person else operation.actor.username,
        "device_id": operation.device_id,
        "target_location_id": operation.target_location_id,
        "target_location_code": operation.target_location.code,
        "reason": operation.reason,
        "correction_of_operation_id": operation.correction_of_operation_id,
        "created_at": (operation.created_at.replace(tzinfo=timezone.utc) if operation.created_at.tzinfo is None else operation.created_at).isoformat(),
        "items": [
            {
                "mold_id": item.mold_id,
                "mold_code": item.mold.code,
                "before_status": item.before_status,
                "after_status": item.after_status,
                "before_location_id": item.before_location_id,
                "after_location_id": item.after_location_id,
                "before_custodian_id": item.before_custodian_id,
                "after_custodian_id": item.after_custodian_id,
                "before_version": item.before_version,
                "after_version": item.after_version,
                "note": item.note,
            }
            for item in operation.items
        ],
    }


@router.get("")
def list_operations(offset: int = 0, limit: int = 50, context: AuthContext = Depends(current_context), db: Session = Depends(get_db)) -> list[dict]:
    if offset < 0 or limit < 1 or limit > 100:
        raise api_error(422, "BAD_PAGINATION", "分页参数无效")
    query = select(Operation)
    if context.user.role == "WORKER":
        query = query.where(Operation.actor_user_id == context.user.id)
    operations = db.scalars(query.order_by(Operation.id.desc()).offset(offset).limit(limit)).all()
    return [response_for(item) for item in operations]


@router.get("/by-request/{request_id}")
def find_by_request(request_id: UUID, context: AuthContext = Depends(current_context), db: Session = Depends(get_db)) -> dict:
    operation = db.scalar(select(Operation).where(Operation.request_id == str(request_id)))
    if operation is None:
        raise api_error(404, "OPERATION_NOT_FOUND", "没有找到这次提交")
    if context.user.role not in {"ADMIN", "READONLY"} and operation.actor_user_id != context.user.id:
        raise api_error(403, "FORBIDDEN", "无权查看这次提交")
    return response_for(operation)


@router.get("/{operation_id}")
def operation_detail(operation_id: int, context: AuthContext = Depends(current_context), db: Session = Depends(get_db)) -> dict:
    operation = db.get(Operation, operation_id)
    if operation is None:
        raise api_error(404, "OPERATION_NOT_FOUND", "单据不存在")
    if context.user.role != "ADMIN" and context.user.role != "READONLY" and operation.actor_user_id != context.user.id:
        raise api_error(403, "FORBIDDEN", "无权查看这张单据")
    return response_for(operation)


@router.post("/{operation_id}/corrections")
def correct_operation(operation_id: int, payload: CorrectionInput, context: AuthContext = Depends(require_csrf), db: Session = Depends(get_db)) -> dict:
    require_admin(context)
    fingerprint = hashlib.sha256(json.dumps({"operation_id": operation_id, **payload.model_dump(mode="json")}, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")).hexdigest()
    existing = db.scalar(select(Operation).where(Operation.request_id == str(payload.request_id)))
    if existing is not None:
        if existing.payload_hash != fingerprint or existing.actor_user_id != context.user.id or existing.correction_of_operation_id != operation_id:
            raise api_error(409, "REQUEST_ID_CONFLICT", "提交编号已经用于另一笔操作")
        return response_for(existing)
    original = db.get(Operation, operation_id)
    if original is None:
        raise api_error(404, "OPERATION_NOT_FOUND", "原单据不存在")
    if original.type not in {"ISSUE", "RETURN", "MOVE", "TRANSFER"} or not original.items:
        raise api_error(409, "CORRECTION_NOT_SUPPORTED", "此类单据需要专项核查，不能直接冲销")
    if db.scalar(select(Operation.id).where(Operation.correction_of_operation_id == operation_id)) is not None:
        raise api_error(409, "ALREADY_CORRECTED", "这张单据已有补偿更正")
    items = sorted(original.items, key=lambda item: item.mold_id)
    if any(item.before_location_id is None for item in items):
        raise api_error(409, "CORRECTION_NOT_SUPPORTED", "原单据缺少可恢复的位置快照")
    ids = [item.mold_id for item in items]
    location_ids = sorted({item.before_location_id for item in items if item.before_location_id is not None} | {item.after_location_id for item in items})
    locations = db.scalars(select(Location).where(Location.id.in_(location_ids)).order_by(Location.id).with_for_update().execution_options(populate_existing=True)).all()
    if len(locations) != len(location_ids) or any(not location.active for location in locations):
        raise api_error(409, "CORRECTION_LOCATION_INVALID", "原位置已停用，不能直接冲销")
    frozen = db.scalar(select(StocktakeSession.id).where(StocktakeSession.location_id.in_(location_ids), StocktakeSession.status.in_(["ACTIVE", "SUBMITTED"])).limit(1))
    if frozen is not None:
        raise api_error(409, "LOCATION_STOCKTAKE_FROZEN", "涉及的库位正在盘点，暂不能更正")
    molds = db.scalars(select(Mold).where(Mold.id.in_(ids)).order_by(Mold.id).with_for_update().execution_options(populate_existing=True)).all()
    if len(molds) != len(items):
        raise api_error(409, "MOLD_NOT_FOUND", "原单据中的模具已无法核对")
    by_id = {item.mold_id: item for item in items}
    for mold in molds:
        item = by_id[mold.id]
        if not mold.is_current or mold.version != item.after_version or mold.status != item.after_status or mold.current_location_id != item.after_location_id or mold.custodian_person_id != item.after_custodian_id:
            raise api_error(409, "SUBSEQUENT_MOVEMENT", f"{mold.code} 已有后续变化，请逐件核查，不得直接回滚旧单据")
    if original.type == "RETURN":
        for set_id in {mold.set_id for mold in molds}:
            members = db.scalars(select(Mold).where(Mold.set_id == set_id, Mold.is_current.is_(True))).all()
            if set_complete(members[0].set, members) and all(member.id in by_id and by_id[member.id].after_status == "READY" for member in members):
                raise api_error(409, "FULL_SET_RETURN_REVIEW", "整套归还可能改变默认库位，请专项核查后处理，不能直接冲销")
    ensure_shelf_capacity(db, {location.id: location for location in locations}, [(mold.current_location_id, by_id[mold.id].before_location_id) for mold in molds])
    operation = Operation(request_id=str(payload.request_id), payload_hash=fingerprint, type="CORRECTION", actor_user_id=context.user.id, target_location_id=items[0].before_location_id, reason=payload.reason.strip(), correction_of_operation_id=original.id)
    db.add(operation)
    for mold in molds:
        item = by_id[mold.id]
        before_version = mold.version
        mold.status = item.before_status
        mold.current_location_id = item.before_location_id
        mold.custodian_person_id = item.before_custodian_id
        db.add(OperationItem(operation=operation, mold_id=mold.id, before_status=item.after_status, after_status=item.before_status, before_location_id=item.after_location_id, after_location_id=item.before_location_id, before_custodian_id=item.after_custodian_id, after_custodian_id=item.before_custodian_id, before_version=before_version, after_version=before_version + 1, note=f"补偿原单据 #{original.id}"))
    db.add(AuditLog(actor_user_id=context.user.id, action="OPERATION_CORRECT", entity=str(original.id), before=original.type, after="CORRECTION", reason=payload.reason.strip()))
    try:
        db.commit()
    except StaleDataError:
        db.rollback()
        raise api_error(409, "VERSION_CONFLICT", "模具被其他操作修改，请重新核对") from None
    except IntegrityError:
        db.rollback()
        duplicate = db.scalar(select(Operation).where(Operation.request_id == str(payload.request_id)))
        if duplicate is not None and duplicate.payload_hash == fingerprint and duplicate.actor_user_id == context.user.id and duplicate.correction_of_operation_id == operation_id:
            return response_for(duplicate)
        raise api_error(409, "CORRECTION_CONFLICT", "更正发生冲突，请查询本次提交结果") from None
    return response_for(operation)


@router.post("")
def submit_operation(payload: OperationInput, request: Request, context: AuthContext = Depends(require_csrf), db: Session = Depends(get_db)) -> dict:
    require_operator(context)
    device = require_device(request, db, context)
    ids = [item.mold_id for item in payload.items]
    if len(set(ids)) != len(ids):
        raise api_error(422, "DUPLICATE_MOLD", "清单中有重复模具")
    if payload.type != "RETURN" and any(item.return_condition != "READY" or item.exception_location_id is not None or item.note for item in payload.items):
        raise api_error(422, "RETURN_FIELDS_INVALID", "仅归还操作可设置逐件异常结果")
    if payload.type == "RETURN":
        for item in payload.items:
            abnormal = item.return_condition != "READY"
            if abnormal and (item.exception_location_id is None or len((item.note or "").strip()) < 3):
                raise api_error(422, "RETURN_EXCEPTION_INCOMPLETE", "异常归还需逐件选择实际位置并填写至少 3 个字的原因")
            if not abnormal and (item.exception_location_id is not None or item.note):
                raise api_error(422, "RETURN_FIELDS_INVALID", "完好归还不能填写异常位置或原因")
    canonical = json.dumps(payload.model_dump(mode="json"), ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    fingerprint = hashlib.sha256(canonical.encode("utf-8")).hexdigest()
    existing = db.scalar(select(Operation).where(Operation.request_id == str(payload.request_id)))
    if existing is not None:
        if existing.payload_hash != fingerprint or existing.actor_user_id != context.user.id:
            raise api_error(409, "REQUEST_ID_CONFLICT", "提交编号已经用于另一笔操作")
        return response_for(existing)

    target = db.get(Location, payload.target_location_id)
    if target is None or not target.active:
        raise api_error(422, "TARGET_INVALID", "目标位置不存在或已停用")
    has_normal_return = payload.type == "RETURN" and any(item.return_condition == "READY" for item in payload.items)
    valid_target = {"ISSUE": "LINE", "RETURN": "SHELF", "MOVE": "SHELF", "TRANSFER": "LINE"}[payload.type] if payload.type != "RETURN" or has_normal_return else None
    exception_ids = {item.exception_location_id for item in payload.items if item.exception_location_id is not None}
    if (valid_target is not None and target.type != valid_target) or (valid_target is None and target.id not in exception_ids):
        raise api_error(422, "TARGET_TYPE_INVALID", "目标位置类型与操作不符")

    # Every stock movement locks affected locations before molds. Stocktake creation
    # uses the same order, so its snapshot and the location freeze cannot interleave.
    source_ids = set(db.scalars(select(Mold.current_location_id).where(Mold.id.in_(ids))).all())
    affected_ids = sorted(source_ids | {target.id} | exception_ids)
    locked_locations = db.scalars(select(Location).where(Location.id.in_(affected_ids)).order_by(Location.id).with_for_update().execution_options(populate_existing=True)).all()
    location_by_id = {location.id: location for location in locked_locations}
    target = location_by_id.get(payload.target_location_id)
    if target is None or not target.active or (valid_target is not None and target.type != valid_target) or (valid_target is None and target.id not in exception_ids):
        raise api_error(422, "TARGET_INVALID", "目标位置已变化，请重新选择")
    if payload.type == "RETURN":
        for item in payload.items:
            if item.return_condition == "READY":
                continue
            exception_target = location_by_id.get(item.exception_location_id)
            required_type = "INSPECTION" if item.return_condition == "PENDING_INSPECTION" else "REPAIR"
            if exception_target is None or not exception_target.active or exception_target.type != required_type:
                raise api_error(422, "RETURN_EXCEPTION_LOCATION_INVALID", "异常归还的实际位置与状态不符")
    frozen = db.scalar(select(StocktakeSession.id).where(StocktakeSession.location_id.in_(affected_ids), StocktakeSession.status.in_(["ACTIVE", "SUBMITTED"])).limit(1))
    if frozen is not None:
        raise api_error(409, "LOCATION_STOCKTAKE_FROZEN", "涉及的库位正在盘点，暂不能流转")

    molds = db.scalars(select(Mold).where(Mold.id.in_(ids)).order_by(Mold.id).with_for_update().execution_options(populate_existing=True)).all()
    if len(molds) != len(ids) or any(not mold.is_current for mold in molds):
        raise api_error(409, "MOLD_NOT_FOUND", "清单中有不存在或已停用的模具")
    versions = {item.mold_id: item.expected_version for item in payload.items}
    if any(mold.version != versions[mold.id] for mold in molds):
        raise api_error(409, "VERSION_CONFLICT", "模具状态已变化，请重新扫码核对")

    for mold in molds:
        source = mold.current_location
        if payload.type == "ISSUE" and (mold.status != "READY" or source.type != "SHELF"):
            raise api_error(409, "NOT_ISSUABLE", f"{mold.code} 当前不可领用")
        if payload.type == "RETURN" and (mold.status != "IN_USE" or source.type != "LINE"):
            raise api_error(409, "NOT_RETURNABLE", f"{mold.code} 当前不可普通归还")
        if payload.type == "MOVE" and (mold.status != "READY" or source.type != "SHELF" or source.id == target.id):
            raise api_error(409, "NOT_MOVABLE", f"{mold.code} 当前不能移库或位置未变化")
        if payload.type == "TRANSFER" and (mold.status != "IN_USE" or source.type != "LINE" or (source.id == target.id and mold.custodian_person_id == context.user.person_id)):
            raise api_error(409, "NOT_TRANSFERABLE", f"{mold.code} 当前不能转线或责任人未变化")

    return_items = {item.mold_id: item for item in payload.items}
    ensure_shelf_capacity(db, location_by_id, [
        (mold.current_location_id, return_items[mold.id].exception_location_id if payload.type == "RETURN" and return_items[mold.id].exception_location_id is not None else target.id)
        for mold in molds
    ])
    op = Operation(request_id=str(payload.request_id), payload_hash=fingerprint, type=payload.type, actor_user_id=context.user.id, device_id=device.id, target_location_id=target.id, reason=payload.reason)
    db.add(op)
    chosen_ids = set(ids)
    if payload.type == "RETURN":
        set_ids = sorted({mold.set_id for mold in molds})
        sets = db.scalars(select(MoldSet).where(MoldSet.id.in_(set_ids)).order_by(MoldSet.id).with_for_update()).all()
        for mold_set in sets:
            members = db.scalars(select(Mold).where(Mold.set_id == mold_set.id, Mold.is_current.is_(True)).order_by(Mold.id).with_for_update()).all()
            if set_complete(members[0].set, members) and all(member.id in chosen_ids and return_items[member.id].return_condition == "READY" for member in members) and mold_set.default_location_id != target.id:
                old = mold_set.default_location_id
                mold_set.default_location_id = target.id
                db.add(AuditLog(actor_user_id=context.user.id, action="FULL_SET_RETURN_RELOCATE", entity=mold_set.code, before=str(old), after=str(target.id), reason="整套完好归还换位"))

    for mold in molds:
        item_input = return_items[mold.id]
        before_status = mold.status
        before_location = mold.current_location_id
        before_custodian = mold.custodian_person_id
        before_version = mold.version
        destination = location_by_id[item_input.exception_location_id] if payload.type == "RETURN" and item_input.exception_location_id is not None else target
        mold.current_location_id = destination.id
        if payload.type == "ISSUE":
            mold.status = "IN_USE"
            mold.custodian_person_id = context.user.person_id
        elif payload.type == "RETURN":
            mold.status = item_input.return_condition
            mold.custodian_person_id = None
        elif payload.type == "TRANSFER":
            mold.custodian_person_id = context.user.person_id
        db.add(OperationItem(operation=op, mold_id=mold.id, before_status=before_status, after_status=mold.status, before_location_id=before_location, after_location_id=destination.id, before_custodian_id=before_custodian, after_custodian_id=mold.custodian_person_id, before_version=before_version, after_version=before_version + 1, note=item_input.note.strip() if payload.type == "RETURN" and item_input.note else None))

    try:
        db.commit()
    except StaleDataError:
        db.rollback()
        raise api_error(409, "VERSION_CONFLICT", "模具被其他操作修改，请重新核对") from None
    except IntegrityError:
        db.rollback()
        duplicate = db.scalar(select(Operation).where(Operation.request_id == str(payload.request_id)))
        if duplicate is not None and duplicate.payload_hash == fingerprint and duplicate.actor_user_id == context.user.id:
            return response_for(duplicate)
        raise api_error(409, "REQUEST_CONFLICT", "提交发生冲突，请查询本次提交结果") from None
    return response_for(op)
