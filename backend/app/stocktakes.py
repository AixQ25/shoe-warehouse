from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
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
from .models import AuditLog, Location, Mold, Operation, OperationItem, StocktakeAdjustment, StocktakeExpected, StocktakeScan, StocktakeSession, utc_now
from .operations import response_for


router = APIRouter(prefix="/api/stocktakes", tags=["stocktakes"])


class CreateStocktake(BaseModel):
    location_id: int = Field(gt=0)


class ScanInput(BaseModel):
    raw_code: str = Field(min_length=1, max_length=100)


class ReasonInput(BaseModel):
    reason: str = Field(min_length=1, max_length=300)


class ResolutionInput(BaseModel):
    request_id: UUID
    type: Literal["MARK_UNVERIFIED", "CONFIRM_WRONG_LOCATION"]
    mold_id: int = Field(gt=0)
    expected_version: int = Field(gt=0)
    target_location_id: int | None = Field(default=None, gt=0)
    reason: str = Field(min_length=3, max_length=300)


def iso(value: datetime | None) -> str | None:
    if value is None:
        return None
    return (value.replace(tzinfo=timezone.utc) if value.tzinfo is None else value).isoformat()


def detail_dict(session: StocktakeSession) -> dict:
    expected = sorted(session.expected, key=lambda item: item.mold.code)
    scans = sorted(session.scans, key=lambda item: item.id)
    adjustments = sorted(session.adjustments, key=lambda item: item.id)
    adjusted_missing = {item.mold_id for item in adjustments if item.type == "MARK_UNVERIFIED"}
    adjusted_wrong = {item.mold_id for item in adjustments if item.type == "CONFIRM_WRONG_LOCATION"}
    found = {item.mold_id for item in scans if item.result == "EXPECTED"}
    missing = [item.mold.code for item in expected if item.mold_id not in found and item.mold_id not in adjusted_missing]
    unexpected = [item.code for item in scans if item.result != "EXPECTED" and not (item.result == "WRONG_LOCATION" and item.mold_id in adjusted_wrong)]
    return {
        "id": session.id,
        "location_id": session.location_id,
        "location_code": session.location.code,
        "location_name": session.location.name,
        "status": session.status,
        "created_at": iso(session.created_at),
        "submitted_at": iso(session.submitted_at),
        "location_verified": session.location_verified_at is not None,
        "closed_at": iso(session.closed_at),
        "close_reason": session.close_reason,
        "expected": [{"mold_id": item.mold_id, "code": item.mold.code, "status": item.expected_status, "version": item.expected_version} for item in expected],
        "scans": [{"id": item.id, "code": item.code, "mold_id": item.mold_id, "mold_version": item.mold.version if item.mold else None, "result": item.result, "scanned_at": iso(item.scanned_at)} for item in scans],
        "adjustments": [{"mold_id": item.mold_id, "code": item.mold.code, "type": item.type, "operation_id": item.operation_id, "created_at": iso(item.created_at)} for item in adjustments],
        "missing_codes": missing,
        "unexpected_codes": unexpected,
    }


def lock_session(db: Session, session_id: int) -> StocktakeSession:
    location_id = db.scalar(select(StocktakeSession.location_id).where(StocktakeSession.id == session_id))
    if location_id is None:
        raise api_error(404, "STOCKTAKE_NOT_FOUND", "盘点任务不存在")
    db.scalar(select(Location).where(Location.id == location_id).with_for_update())
    session = db.scalar(select(StocktakeSession).where(StocktakeSession.id == session_id).with_for_update().execution_options(populate_existing=True))
    if session is None:
        raise api_error(404, "STOCKTAKE_NOT_FOUND", "盘点任务不存在")
    return session


@router.get("")
def list_stocktakes(_context: AuthContext = Depends(current_context), db: Session = Depends(get_db)) -> list[dict]:
    sessions = db.scalars(select(StocktakeSession).order_by(StocktakeSession.id.desc()).limit(50)).all()
    return [detail_dict(item) for item in sessions]


@router.get("/{session_id}")
def stocktake_detail(session_id: int, _context: AuthContext = Depends(current_context), db: Session = Depends(get_db)) -> dict:
    session = db.get(StocktakeSession, session_id)
    if session is None:
        raise api_error(404, "STOCKTAKE_NOT_FOUND", "盘点任务不存在")
    return detail_dict(session)


@router.post("")
def create_stocktake(payload: CreateStocktake, request: Request, context: AuthContext = Depends(require_csrf), db: Session = Depends(get_db)) -> dict:
    require_operator(context)
    require_device(request, db, context)
    location = db.scalar(select(Location).where(Location.id == payload.location_id).with_for_update().execution_options(populate_existing=True))
    if location is None or not location.active or location.type != "SHELF":
        raise api_error(422, "LOCATION_INVALID", "盘点只能选择有效的普通库位")
    existing = db.scalar(select(StocktakeSession.id).where(StocktakeSession.location_id == location.id, StocktakeSession.status.in_(["ACTIVE", "SUBMITTED"])))
    if existing is not None:
        raise api_error(409, "LOCATION_ALREADY_FROZEN", "该库位已有未结束的盘点")
    molds = db.scalars(select(Mold).where(Mold.current_location_id == location.id, Mold.is_current.is_(True)).order_by(Mold.id).with_for_update()).all()
    session = StocktakeSession(location_id=location.id, status="ACTIVE", created_by_user_id=context.user.id)
    db.add(session)
    for mold in molds:
        db.add(StocktakeExpected(session=session, mold_id=mold.id, expected_version=mold.version, expected_status=mold.status))
    db.add(AuditLog(actor_user_id=context.user.id, action="STOCKTAKE_CREATE", entity=location.code, after=str(len(molds)), reason="冻结库位并保存期初清单"))
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        raise api_error(409, "LOCATION_ALREADY_FROZEN", "该库位已有未结束的盘点") from None
    return detail_dict(session)


@router.post("/{session_id}/scan")
def scan_stocktake(session_id: int, payload: ScanInput, request: Request, context: AuthContext = Depends(require_csrf), db: Session = Depends(get_db)) -> dict:
    require_operator(context)
    require_device(request, db, context)
    session = lock_session(db, session_id)
    if session.status != "ACTIVE":
        raise api_error(409, "STOCKTAKE_NOT_ACTIVE", "盘点不在扫码阶段")
    raw = payload.raw_code.strip().upper()
    if raw.startswith("LOC:"):
        if raw[4:] != session.location.code.upper():
            raise api_error(409, "WRONG_STOCKTAKE_LOCATION", "扫到的不是本次盘点库位")
        session.location_verified_at = utc_now()
        session.location_verified_by_user_id = context.user.id
        db.commit()
        return {"kind": "LOCATION_VERIFIED", "stocktake": detail_dict(session)}
    if not session.location_verified_at:
        raise api_error(409, "LOCATION_SCAN_REQUIRED", "请先扫描本次盘点库位码")
    if raw.startswith("MOLD:"):
        code = raw[5:]
    elif ":" in raw:
        raise api_error(422, "SCAN_PREFIX_INVALID", "二维码类型无法识别")
    else:
        code = raw
    if not code or len(code) > 80:
        raise api_error(422, "CODE_INVALID", "模具编号无效")
    previous = db.scalar(select(StocktakeScan).where(StocktakeScan.session_id == session.id, StocktakeScan.code == code))
    if previous is not None:
        return {"kind": "ALREADY_SCANNED", "result": previous.result, "stocktake": detail_dict(session)}
    mold = db.scalar(select(Mold).where(Mold.code == code, Mold.is_current.is_(True)))
    expected_ids = {item.mold_id for item in session.expected}
    result = "UNKNOWN" if mold is None else "EXPECTED" if mold.id in expected_ids else "WRONG_LOCATION"
    db.add(StocktakeScan(session=session, code=code, mold_id=mold.id if mold else None, result=result, scanned_by_user_id=context.user.id))
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        raise api_error(409, "SCAN_CONFLICT", "该模具已被其他盘点操作扫描，请刷新") from None
    return {"kind": "MOLD_SCANNED", "result": result, "stocktake": detail_dict(session)}


@router.delete("/{session_id}/scans/{scan_id}")
def remove_scan(session_id: int, scan_id: int, request: Request, context: AuthContext = Depends(require_csrf), db: Session = Depends(get_db)) -> dict:
    require_operator(context)
    require_device(request, db, context)
    session = lock_session(db, session_id)
    if session.status != "ACTIVE":
        raise api_error(409, "STOCKTAKE_NOT_ACTIVE", "盘点不在扫码阶段")
    scan = db.scalar(select(StocktakeScan).where(StocktakeScan.id == scan_id, StocktakeScan.session_id == session_id))
    if scan is None:
        raise api_error(404, "SCAN_NOT_FOUND", "扫描记录不存在")
    db.add(AuditLog(actor_user_id=context.user.id, action="STOCKTAKE_SCAN_REMOVE", entity=str(session.id), before=scan.code, reason="撤销误扫"))
    db.delete(scan)
    db.commit()
    return detail_dict(session)


@router.post("/{session_id}/submit")
def submit_stocktake(session_id: int, request: Request, context: AuthContext = Depends(require_csrf), db: Session = Depends(get_db)) -> dict:
    require_operator(context)
    require_device(request, db, context)
    session = lock_session(db, session_id)
    if session.status != "ACTIVE":
        raise api_error(409, "STOCKTAKE_NOT_ACTIVE", "盘点不在扫码阶段")
    if session.location_verified_at is None:
        raise api_error(409, "LOCATION_SCAN_REQUIRED", "请先扫描本次盘点库位码")
    session.status = "SUBMITTED"
    session.submitted_at = utc_now()
    db.add(AuditLog(actor_user_id=context.user.id, action="STOCKTAKE_SUBMIT", entity=str(session.id), after=session.location.code))
    db.commit()
    return detail_dict(session)


@router.post("/{session_id}/reopen")
def reopen_stocktake(session_id: int, payload: ReasonInput, context: AuthContext = Depends(require_csrf), db: Session = Depends(get_db)) -> dict:
    require_admin(context)
    session = lock_session(db, session_id)
    if session.status != "SUBMITTED":
        raise api_error(409, "STOCKTAKE_NOT_SUBMITTED", "只有已提交的盘点可以退回重扫")
    session.status = "ACTIVE"
    session.submitted_at = None
    db.add(AuditLog(actor_user_id=context.user.id, action="STOCKTAKE_REOPEN", entity=str(session.id), after="ACTIVE", reason=payload.reason.strip()))
    db.commit()
    return detail_dict(session)


@router.post("/{session_id}/close")
def close_stocktake(session_id: int, context: AuthContext = Depends(require_csrf), db: Session = Depends(get_db)) -> dict:
    require_admin(context)
    session = lock_session(db, session_id)
    if session.status != "SUBMITTED":
        raise api_error(409, "STOCKTAKE_NOT_SUBMITTED", "请先提交盘点结果")
    details = detail_dict(session)
    if details["missing_codes"] or details["unexpected_codes"]:
        raise api_error(409, "STOCKTAKE_DIFFERENCES", "仍有差异，不能直接结束盘点")
    session.status = "CLOSED"
    session.closed_at = utc_now()
    session.closed_by_user_id = context.user.id
    db.add(AuditLog(actor_user_id=context.user.id, action="STOCKTAKE_CLOSE", entity=str(session.id), after=session.location.code, reason="账实一致"))
    db.commit()
    return detail_dict(session)


@router.post("/{session_id}/cancel")
def cancel_stocktake(session_id: int, payload: ReasonInput, context: AuthContext = Depends(require_csrf), db: Session = Depends(get_db)) -> dict:
    require_admin(context)
    session = lock_session(db, session_id)
    if session.status not in {"ACTIVE", "SUBMITTED"}:
        raise api_error(409, "STOCKTAKE_ALREADY_FINISHED", "盘点已经结束")
    session.status = "CANCELLED"
    session.closed_at = utc_now()
    session.closed_by_user_id = context.user.id
    session.close_reason = payload.reason.strip()
    db.add(AuditLog(actor_user_id=context.user.id, action="STOCKTAKE_CANCEL", entity=str(session.id), after=session.location.code, reason=session.close_reason))
    db.commit()
    return detail_dict(session)


@router.post("/{session_id}/resolve")
def resolve_stocktake(session_id: int, payload: ResolutionInput, context: AuthContext = Depends(require_csrf), db: Session = Depends(get_db)) -> dict:
    require_admin(context)
    fingerprint = hashlib.sha256(json.dumps(payload.model_dump(mode="json"), ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")).hexdigest()
    existing = db.scalar(select(Operation).where(Operation.request_id == str(payload.request_id)))
    if existing is not None:
        linked = db.scalar(select(StocktakeAdjustment).where(StocktakeAdjustment.operation_id == existing.id, StocktakeAdjustment.session_id == session_id))
        if existing.payload_hash != fingerprint or existing.actor_user_id != context.user.id or linked is None:
            raise api_error(409, "REQUEST_ID_CONFLICT", "提交编号已经用于另一笔操作")
        return {"operation": response_for(existing), "stocktake": detail_dict(linked.session)}

    session_location_id = db.scalar(select(StocktakeSession.location_id).where(StocktakeSession.id == session_id))
    source_location_id = db.scalar(select(Mold.current_location_id).where(Mold.id == payload.mold_id))
    if session_location_id is None or source_location_id is None:
        raise api_error(404, "STOCKTAKE_OR_MOLD_NOT_FOUND", "盘点或模具不存在")
    target_id = payload.target_location_id if payload.type == "MARK_UNVERIFIED" else session_location_id
    if target_id is None:
        raise api_error(422, "TARGET_REQUIRED", "请指定未知位置")
    location_ids = sorted({session_location_id, source_location_id, target_id})
    locked = db.scalars(select(Location).where(Location.id.in_(location_ids)).order_by(Location.id).with_for_update().execution_options(populate_existing=True)).all()
    locations = {item.id: item for item in locked}
    if len(locations) != len(location_ids):
        raise api_error(422, "TARGET_INVALID", "位置不存在")
    session = lock_session(db, session_id)
    if session.status != "SUBMITTED":
        raise api_error(409, "STOCKTAKE_NOT_SUBMITTED", "请先提交盘点，才能核查差异")
    if db.scalar(select(StocktakeAdjustment.id).where(StocktakeAdjustment.session_id == session_id, StocktakeAdjustment.mold_id == payload.mold_id)) is not None:
        raise api_error(409, "ALREADY_RESOLVED", "这件模具的盘点差异已核查")
    other_frozen = db.scalar(select(StocktakeSession.id).where(StocktakeSession.location_id.in_(location_ids), StocktakeSession.id != session_id, StocktakeSession.status.in_(["ACTIVE", "SUBMITTED"])).limit(1))
    if other_frozen is not None:
        raise api_error(409, "OTHER_LOCATION_FROZEN", "模具涉及另一项未结束的盘点")
    mold = db.scalar(select(Mold).where(Mold.id == payload.mold_id).with_for_update().execution_options(populate_existing=True))
    if mold is None or not mold.is_current or mold.version != payload.expected_version:
        raise api_error(409, "VERSION_CONFLICT", "模具状态已变化，请重新核查")
    if mold.current_location_id != source_location_id:
        raise api_error(409, "LOCATION_CHANGED", "模具位置已变化，请重新核查")

    if payload.type == "MARK_UNVERIFIED":
        expected = db.scalar(select(StocktakeExpected).where(StocktakeExpected.session_id == session_id, StocktakeExpected.mold_id == mold.id))
        if expected is None or mold.code not in detail_dict(session)["missing_codes"] or mold.current_location_id != session.location_id or mold.version != expected.expected_version:
            raise api_error(409, "MISSING_FINDING_INVALID", "该模具不是当前有效的未扫差异")
        if not locations[target_id].active or locations[target_id].type != "UNKNOWN":
            raise api_error(422, "TARGET_INVALID", "未找到模具只能登记到有效的未知位置")
        new_status = "UNVERIFIED"
    else:
        if payload.target_location_id not in {None, session.location_id}:
            raise api_error(422, "TARGET_INVALID", "错位模具应调整到本次盘点库位")
        wrong_scan = db.scalar(select(StocktakeScan).where(StocktakeScan.session_id == session_id, StocktakeScan.mold_id == mold.id, StocktakeScan.result == "WRONG_LOCATION"))
        if wrong_scan is None or mold.current_location_id == session.location_id or locations[source_location_id].type != "SHELF" or mold.status not in {"READY", "PENDING_INSPECTION"}:
            raise api_error(409, "WRONG_LOCATION_FINDING_INVALID", "该模具不符合库位错位调整条件")
        new_status = mold.status

    ensure_shelf_capacity(db, locations, [(mold.current_location_id, target_id)])
    before_status = mold.status
    before_location = mold.current_location_id
    before_custodian = mold.custodian_person_id
    before_version = mold.version
    mold.status = new_status
    mold.current_location_id = target_id
    if new_status == "UNVERIFIED":
        mold.custodian_person_id = None
    operation = Operation(request_id=str(payload.request_id), payload_hash=fingerprint, type="STOCKTAKE_ADJUST", actor_user_id=context.user.id, target_location_id=target_id, reason=payload.reason.strip())
    db.add(operation)
    db.add(OperationItem(operation=operation, mold_id=mold.id, before_status=before_status, after_status=mold.status, before_location_id=before_location, after_location_id=target_id, before_custodian_id=before_custodian, after_custodian_id=mold.custodian_person_id, before_version=before_version, after_version=before_version + 1))
    db.add(StocktakeAdjustment(session=session, mold_id=mold.id, operation=operation, type=payload.type))
    db.add(AuditLog(actor_user_id=context.user.id, action=f"STOCKTAKE_{payload.type}", entity=str(session.id), before=mold.code, after=locations[target_id].code, reason=payload.reason.strip()))
    try:
        db.commit()
    except StaleDataError:
        db.rollback()
        raise api_error(409, "VERSION_CONFLICT", "模具被其他操作修改，请重新核查") from None
    except IntegrityError:
        db.rollback()
        duplicate = db.scalar(select(Operation).where(Operation.request_id == str(payload.request_id)))
        if duplicate is not None and duplicate.payload_hash == fingerprint and duplicate.actor_user_id == context.user.id:
            return {"operation": response_for(duplicate), "stocktake": detail_dict(db.get(StocktakeSession, session_id))}
        raise api_error(409, "RESOLUTION_CONFLICT", "核查发生冲突，请刷新任务") from None
    return {"operation": response_for(operation), "stocktake": detail_dict(session)}
