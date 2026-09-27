from __future__ import annotations

import hashlib
import json
from typing import Literal
from uuid import UUID

from fastapi import APIRouter, Depends, Request
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session
from sqlalchemy.orm.exc import StaleDataError

from .auth import AuthContext, api_error, get_db, require_admin, require_csrf, require_device, require_operator
from .catalog import mold_dict
from .models import AuditLog, Location, Mold, Operation, OperationItem, StocktakeSession
from .operations import response_for


router = APIRouter(prefix="/api/molds", tags=["mold-exceptions"])

Action = Literal["RETURN_FOR_INSPECTION", "SEND_REPAIR", "REPAIR_COMPLETE", "INSPECTION_PASS", "SCRAP", "FOUND"]


class ExceptionInput(BaseModel):
    request_id: UUID
    action: Action
    expected_version: int = Field(gt=0)
    target_location_id: int = Field(gt=0)
    reason: str = Field(min_length=3, max_length=300)
    found_status: Literal["PENDING_INSPECTION", "READY"] | None = None


@router.post("/{mold_id}/transition")
def transition_mold(mold_id: int, payload: ExceptionInput, request: Request, context: AuthContext = Depends(require_csrf), db: Session = Depends(get_db)) -> dict:
    if payload.action in {"SCRAP", "FOUND"}:
        require_admin(context)
    else:
        require_operator(context)
        if context.user.role != "ADMIN":
            require_device(request, db, context)
    if payload.action == "FOUND" and payload.found_status is None or payload.action != "FOUND" and payload.found_status is not None:
        raise api_error(422, "FOUND_STATUS_INVALID", "找回模具时须选择恢复状态，其他操作不得填写")

    fingerprint = hashlib.sha256(json.dumps({"mold_id": mold_id, **payload.model_dump(mode="json")}, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")).hexdigest()
    existing = db.scalar(select(Operation).where(Operation.request_id == str(payload.request_id)))
    if existing is not None:
        if existing.payload_hash != fingerprint or existing.actor_user_id != context.user.id or len(existing.items) != 1 or existing.items[0].mold_id != mold_id:
            raise api_error(409, "REQUEST_ID_CONFLICT", "提交编号已经用于另一笔操作")
        return {"operation": response_for(existing), "mold": mold_dict(db.get(Mold, mold_id))}

    source_id = db.scalar(select(Mold.current_location_id).where(Mold.id == mold_id))
    if source_id is None:
        raise api_error(404, "MOLD_NOT_FOUND", "模具不存在")
    location_ids = sorted({source_id, payload.target_location_id})
    locked_locations = db.scalars(select(Location).where(Location.id.in_(location_ids)).order_by(Location.id).with_for_update().execution_options(populate_existing=True)).all()
    locations = {item.id: item for item in locked_locations}
    target = locations.get(payload.target_location_id)
    if target is None or not target.active:
        raise api_error(422, "TARGET_INVALID", "目标位置无效")
    frozen = db.scalar(select(StocktakeSession.id).where(StocktakeSession.location_id.in_(location_ids), StocktakeSession.status.in_(["ACTIVE", "SUBMITTED"])).limit(1))
    if frozen is not None:
        raise api_error(409, "LOCATION_STOCKTAKE_FROZEN", "涉及的库位正在盘点，暂不能办理")
    mold = db.scalar(select(Mold).where(Mold.id == mold_id).with_for_update().execution_options(populate_existing=True))
    if mold is None or not mold.is_current or mold.version != payload.expected_version or mold.current_location_id != source_id:
        raise api_error(409, "VERSION_CONFLICT", "模具状态已变化，请刷新后重新核对")

    if payload.action == "RETURN_FOR_INSPECTION":
        valid = mold.status == "IN_USE" and target.type in {"INSPECTION", "SHELF"}
        after_status = "PENDING_INSPECTION"
    elif payload.action == "SEND_REPAIR":
        valid = mold.status in {"IN_USE", "PENDING_INSPECTION"} and target.type == "REPAIR"
        after_status = "IN_REPAIR"
    elif payload.action == "REPAIR_COMPLETE":
        valid = mold.status == "IN_REPAIR" and target.type == "INSPECTION"
        after_status = "PENDING_INSPECTION"
    elif payload.action == "INSPECTION_PASS":
        valid = mold.status == "PENDING_INSPECTION" and target.type == "SHELF"
        after_status = "READY"
    elif payload.action == "SCRAP":
        valid = mold.status != "SCRAPPED" and target.type == "SCRAP"
        after_status = "SCRAPPED"
    else:
        valid = mold.status == "UNVERIFIED" and ((payload.found_status == "READY" and target.type == "SHELF") or (payload.found_status == "PENDING_INSPECTION" and target.type in {"SHELF", "INSPECTION"}))
        after_status = payload.found_status
    if not valid or after_status is None:
        raise api_error(409, "TRANSITION_INVALID", "当前状态或目标位置不允许这项操作")

    before_status = mold.status
    before_location = mold.current_location_id
    before_custodian = mold.custodian_person_id
    before_version = mold.version
    mold.status = after_status
    mold.current_location_id = target.id
    mold.custodian_person_id = None
    if payload.action == "SCRAP":
        mold.is_current = False
    operation = Operation(request_id=str(payload.request_id), payload_hash=fingerprint, type=payload.action, actor_user_id=context.user.id, target_location_id=target.id, reason=payload.reason.strip())
    db.add(operation)
    db.add(OperationItem(operation=operation, mold_id=mold.id, before_status=before_status, after_status=after_status, before_location_id=before_location, after_location_id=target.id, before_custodian_id=before_custodian, after_custodian_id=None, before_version=before_version, after_version=before_version + 1))
    if payload.action in {"SCRAP", "FOUND"}:
        db.add(AuditLog(actor_user_id=context.user.id, action=payload.action, entity=mold.code, before=before_status, after=after_status, reason=payload.reason.strip()))
    try:
        db.commit()
    except StaleDataError:
        db.rollback()
        raise api_error(409, "VERSION_CONFLICT", "模具被其他操作修改，请重新核对") from None
    except IntegrityError:
        db.rollback()
        duplicate = db.scalar(select(Operation).where(Operation.request_id == str(payload.request_id)))
        if duplicate is not None and duplicate.payload_hash == fingerprint and duplicate.actor_user_id == context.user.id:
            return {"operation": response_for(duplicate), "mold": mold_dict(db.get(Mold, mold_id))}
        raise api_error(409, "TRANSITION_CONFLICT", "提交发生冲突，请查询单据结果") from None
    return {"operation": response_for(operation), "mold": mold_dict(mold)}
