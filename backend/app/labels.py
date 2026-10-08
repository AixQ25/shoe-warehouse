from __future__ import annotations

import json
from datetime import timezone
from typing import Literal
from uuid import UUID

from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from .auth import AuthContext, api_error, current_context, get_db, require_csrf
from .models import LabelPrintBatch, Location, Mold
from .mold_metadata import metadata_dict


router = APIRouter(prefix="/api/labels", tags=["labels"])


class LabelSelection(BaseModel):
    kind: Literal["MOLD", "LOCATION"]
    codes: list[str] = Field(min_length=1, max_length=100)


class PrintRecordInput(LabelSelection):
    request_id: UUID
    purpose: Literal["INITIAL", "REPRINT"]
    reason: str | None = Field(default=None, max_length=300)


def require_label_operator(context: AuthContext) -> None:
    if context.user.role not in {"ADMIN", "WORKER"}:
        raise api_error(403, "FORBIDDEN", "当前账号不能打印标签")


def resolve_labels(selection: LabelSelection, db: Session) -> list[dict]:
    codes = [code.strip().upper() for code in selection.codes]
    if any(not code or len(code) > 80 for code in codes) or len(set(codes)) != len(codes):
        raise api_error(422, "LABEL_CODES_INVALID", "标签编号不能为空、重复或超过 80 字符")
    if selection.kind == "MOLD":
        found = db.scalars(select(Mold).where(func.upper(Mold.code).in_(codes), Mold.is_current.is_(True))).all()
        labels = {item.code.upper(): {"kind": "MOLD", "code": item.code, "mold_number": item.set.model.code, "qr_content": f"MOLD:{item.code}", "model_code": item.set.model.code, "set_code": item.set.code, "size_label": item.size_label, "name": item.set.model.name, **metadata_dict(item)} for item in found}
    else:
        found = db.scalars(select(Location).where(func.upper(Location.code).in_(codes), Location.active.is_(True))).all()
        labels = {item.code.upper(): {"kind": "LOCATION", "code": item.code, "qr_content": f"LOC:{item.code}", "name": item.name} for item in found}
    if len(found) != len(codes) or len(labels) != len(codes):
        raise api_error(404, "LABEL_TARGET_NOT_FOUND", "部分标签编号不存在或已停用，请刷新资料")
    return [labels[code] for code in codes]


def record_dict(record: LabelPrintBatch) -> dict:
    at = record.requested_at.replace(tzinfo=timezone.utc) if record.requested_at.tzinfo is None else record.requested_at
    return {"id": record.id, "request_id": record.request_id, "kind": record.kind, "purpose": record.purpose, "codes": json.loads(record.codes_json), "reason": record.reason, "actor_user_id": record.actor_user_id, "requested_at": at.isoformat()}


@router.post("/preview")
def preview_labels(selection: LabelSelection, context: AuthContext = Depends(current_context), db: Session = Depends(get_db)) -> dict:
    require_label_operator(context)
    return {"labels": resolve_labels(selection, db)}


@router.post("/print-record")
def record_print(payload: PrintRecordInput, context: AuthContext = Depends(require_csrf), db: Session = Depends(get_db)) -> dict:
    require_label_operator(context)
    reason = payload.reason.strip() if payload.reason else None
    if payload.purpose == "REPRINT" and (reason is None or len(reason) < 3):
        raise api_error(422, "PRINT_REASON_REQUIRED", "补打标签需填写至少 3 个字的原因")
    existing = db.scalar(select(LabelPrintBatch).where(LabelPrintBatch.request_id == str(payload.request_id)))
    requested_codes = [code.strip().upper() for code in payload.codes]
    if existing is not None:
        if existing.actor_user_id != context.user.id or existing.kind != payload.kind or existing.purpose != payload.purpose or [code.upper() for code in json.loads(existing.codes_json)] != requested_codes or existing.reason != reason:
            raise api_error(409, "PRINT_REQUEST_CONFLICT", "请求编号已用于另一批标签")
        return record_dict(existing)
    labels = resolve_labels(payload, db)
    codes = [item["code"] for item in labels]
    record = LabelPrintBatch(request_id=str(payload.request_id), actor_user_id=context.user.id, kind=payload.kind, purpose=payload.purpose, codes_json=json.dumps(codes, ensure_ascii=False), reason=reason)
    db.add(record)
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        raise api_error(409, "PRINT_REQUEST_CONFLICT", "请求编号已被占用，请查询打印记录") from None
    return record_dict(record)


@router.get("/print-records")
def list_print_records(limit: int = 30, context: AuthContext = Depends(current_context), db: Session = Depends(get_db)) -> list[dict]:
    require_label_operator(context)
    if limit < 1 or limit > 100:
        raise api_error(422, "BAD_PAGINATION", "分页参数无效")
    query = select(LabelPrintBatch).order_by(LabelPrintBatch.id.desc()).limit(limit)
    if context.user.role == "WORKER":
        query = query.where(LabelPrintBatch.actor_user_id == context.user.id)
    return [record_dict(item) for item in db.scalars(query).all()]
