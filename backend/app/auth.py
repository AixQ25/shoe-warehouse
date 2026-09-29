from __future__ import annotations

import hashlib
import hmac
import secrets
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Depends, Header, HTTPException, Request, Response
from pydantic import BaseModel, Field
from sqlalchemy import or_, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from .database import make_session_factory
from .models import AuditLog, AuthorizedDevice, ImportBatch, LabelPrintBatch, LoginSession, Operation, Person, StocktakeScan, StocktakeSession, User, utc_now

SESSION_COOKIE = "warehouse_session"
DEVICE_COOKIE = "warehouse_device"
CSRF_COOKIE = "warehouse_csrf"


def token_hash(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def hash_password(password: str) -> str:
    salt = secrets.token_bytes(16)
    digest = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt, 600_000)
    return f"pbkdf2_sha256$600000${salt.hex()}${digest.hex()}"


def verify_password(password: str, stored: str) -> bool:
    try:
        algorithm, rounds, salt, digest = stored.split("$")
        if algorithm != "pbkdf2_sha256":
            return False
        candidate = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), bytes.fromhex(salt), int(rounds))
        return hmac.compare_digest(candidate, bytes.fromhex(digest))
    except (ValueError, TypeError):
        return False


def api_error(status: int, code: str, message: str) -> HTTPException:
    return HTTPException(status_code=status, detail={"error_code": code, "message": message})


def get_db(request: Request):  # type: ignore[no-untyped-def]
    factory = request.app.state.session_factory
    with factory() as db:
        yield db


@dataclass
class AuthContext:
    user: User
    login: LoginSession


def current_context(request: Request, db: Session = Depends(get_db)) -> AuthContext:
    raw = request.cookies.get(SESSION_COOKIE)
    if not raw:
        raise api_error(401, "NOT_LOGGED_IN", "请先登录")
    login = db.scalar(select(LoginSession).where(LoginSession.token_hash == token_hash(raw)))
    if login is None or login.revoked_at is not None:
        raise api_error(401, "SESSION_INVALID", "登录已失效")
    expires = login.expires_at.replace(tzinfo=timezone.utc) if login.expires_at.tzinfo is None else login.expires_at
    if expires <= utc_now():
        raise api_error(401, "SESSION_EXPIRED", "登录已过期")
    user = db.get(User, login.user_id)
    if user is None or not user.active or (user.person_id is not None and (user.person is None or not user.person.active)):
        raise api_error(403, "ACCOUNT_DISABLED", "账号或人员已停用")
    return AuthContext(user, login)


def require_csrf(request: Request, x_csrf_token: str | None = Header(default=None), context: AuthContext = Depends(current_context)) -> AuthContext:
    cookie = request.cookies.get(CSRF_COOKIE)
    if not x_csrf_token or not cookie or not hmac.compare_digest(cookie, x_csrf_token) or not hmac.compare_digest(context.login.csrf_hash, token_hash(x_csrf_token)):
        raise api_error(403, "CSRF_FAILED", "页面验证已失效，请重新登录")
    return context


def require_admin(context: AuthContext) -> None:
    if context.user.role != "ADMIN":
        raise api_error(403, "FORBIDDEN", "需要系统维护员权限")


def require_operator(context: AuthContext) -> None:
    if context.user.role not in {"ADMIN", "WORKER"} or context.user.person_id is None:
        raise api_error(403, "FORBIDDEN", "当前账号不能办理库存操作")


def require_device(request: Request, db: Session, context: AuthContext) -> AuthorizedDevice:
    raw = request.cookies.get(DEVICE_COOKIE)
    if not raw:
        raise api_error(403, "DEVICE_REQUIRED", "当前手机尚未登记授权")
    device = db.scalar(select(AuthorizedDevice).where(AuthorizedDevice.token_hash == token_hash(raw), AuthorizedDevice.user_id == context.user.id))
    if device is None or not device.authorized or device.revoked_at is not None:
        raise api_error(403, "DEVICE_NOT_AUTHORIZED", "当前设备未授权或已撤销")
    return device


class LoginInput(BaseModel):
    username: str = Field(min_length=1, max_length=80)
    password: str = Field(min_length=1, max_length=200)


class DeviceInput(BaseModel):
    label: str = Field(min_length=1, max_length=100)


class UserInput(BaseModel):
    username: str = Field(min_length=1, max_length=80)
    password: str = Field(min_length=12, max_length=200)
    role: str
    person_id: int | None = None


class UserActiveInput(BaseModel):
    active: bool
    reason: str = Field(min_length=3, max_length=300)


class PasswordResetInput(BaseModel):
    password: str = Field(min_length=12, max_length=200)
    reason: str = Field(min_length=3, max_length=300)


auth_router = APIRouter(prefix="/api/auth", tags=["auth"])
device_router = APIRouter(prefix="/api/devices", tags=["devices"])


@auth_router.post("/login")
def login(payload: LoginInput, response: Response, request: Request, db: Session = Depends(get_db)) -> dict:
    user = db.scalar(select(User).where(User.username == payload.username))
    if user is None or not user.active or not verify_password(payload.password, user.password_hash):
        raise api_error(401, "BAD_CREDENTIALS", "账号或密码错误")
    if user.person_id is not None and (user.person is None or not user.person.active):
        raise api_error(403, "ACCOUNT_DISABLED", "人员已停用")
    session_token = secrets.token_urlsafe(32)
    csrf_token = secrets.token_urlsafe(32)
    db.add(LoginSession(user_id=user.id, token_hash=token_hash(session_token), csrf_hash=token_hash(csrf_token), expires_at=utc_now() + timedelta(hours=12)))
    db.commit()
    secure = request.app.state.cookie_secure
    response.set_cookie(SESSION_COOKIE, session_token, max_age=43200, httponly=True, secure=secure, samesite="lax", path="/")
    response.set_cookie(CSRF_COOKIE, csrf_token, max_age=43200, httponly=False, secure=secure, samesite="lax", path="/")
    return {"id": user.id, "username": user.username, "role": user.role, "person": user.person.name if user.person else None, "csrf_token": csrf_token}


@auth_router.get("/me")
def me(context: AuthContext = Depends(current_context)) -> dict:
    user = context.user
    return {"id": user.id, "username": user.username, "role": user.role, "person": user.person.name if user.person else None}


@auth_router.post("/logout")
def logout(response: Response, context: AuthContext = Depends(require_csrf), db: Session = Depends(get_db)) -> dict:
    context.login.revoked_at = utc_now()
    db.commit()
    response.delete_cookie(SESSION_COOKIE, path="/")
    response.delete_cookie(CSRF_COOKIE, path="/")
    response.delete_cookie(DEVICE_COOKIE, path="/")
    return {"ok": True}


@auth_router.get("/users")
def list_users(context: AuthContext = Depends(current_context), db: Session = Depends(get_db)) -> list[dict]:
    require_admin(context)
    return [{"id": user.id, "username": user.username, "role": user.role, "person_id": user.person_id, "person": user.person.name if user.person else None, "active": user.active} for user in db.scalars(select(User).order_by(User.id)).all()]


@auth_router.post("/users")
def create_user(payload: UserInput, context: AuthContext = Depends(require_csrf), db: Session = Depends(get_db)) -> dict:
    require_admin(context)
    if not payload.username.strip():
        raise api_error(422, "USERNAME_REQUIRED", "账号名不能为空")
    if payload.role not in {"ADMIN", "WORKER", "READONLY"}:
        raise api_error(422, "ROLE_INVALID", "账号角色无效")
    if payload.role == "READONLY" and payload.person_id is not None or payload.role != "READONLY" and payload.person_id is None:
        raise api_error(422, "PERSON_REQUIRED", "维护员和领用账号须关联人员；只读账号不关联人员")
    if payload.person_id is not None:
        person = db.get(Person, payload.person_id)
        if person is None or not person.active:
            raise api_error(422, "PERSON_INVALID", "关联人员不存在或已停用")
    user = User(username=payload.username.strip(), password_hash=hash_password(payload.password), role=payload.role, person_id=payload.person_id)
    db.add(user)
    try:
        db.flush()
        db.add(AuditLog(actor_user_id=context.user.id, action="USER_CREATE", entity=str(user.id), after=f"{user.username} · {user.role}"))
        db.commit()
    except IntegrityError:
        db.rollback()
        raise api_error(409, "USER_CONFLICT", "账号名已存在，或该人员已关联其他账号") from None
    return {"id": user.id, "username": user.username, "role": user.role, "person_id": user.person_id, "active": True}


@auth_router.delete("/users/{user_id}")
def delete_user(user_id: int, context: AuthContext = Depends(require_csrf), db: Session = Depends(get_db)) -> dict:
    require_admin(context)
    if user_id == context.user.id:
        raise api_error(409, "CANNOT_DELETE_SELF", "不能删除当前登录的维护员账号")
    user = db.scalar(select(User).where(User.id == user_id).with_for_update())
    if user is None:
        raise api_error(404, "USER_NOT_FOUND", "账号不存在")
    references = (
        (Operation, Operation.actor_user_id == user_id),
        (StocktakeSession, or_(StocktakeSession.created_by_user_id == user_id, StocktakeSession.location_verified_by_user_id == user_id, StocktakeSession.closed_by_user_id == user_id)),
        (StocktakeScan, StocktakeScan.scanned_by_user_id == user_id),
        (ImportBatch, ImportBatch.created_by_user_id == user_id),
        (LabelPrintBatch, LabelPrintBatch.actor_user_id == user_id),
        (AuditLog, AuditLog.actor_user_id == user_id),
    )
    if any(db.scalar(select(model.id).where(condition).limit(1)) is not None for model, condition in references):
        raise api_error(409, "USER_IN_USE", "账号已有业务记录，不能删除；可停用账号")
    username = user.username
    for login in db.scalars(select(LoginSession).where(LoginSession.user_id == user_id)).all():
        db.delete(login)
    for device in db.scalars(select(AuthorizedDevice).where(AuthorizedDevice.user_id == user_id)).all():
        db.delete(device)
    db.delete(user)
    db.add(AuditLog(actor_user_id=context.user.id, action="USER_DELETE", entity=str(user_id), before=username))
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        raise api_error(409, "USER_IN_USE", "账号已被业务记录引用，不能删除") from None
    return {"id": user_id, "username": username}


@auth_router.patch("/users/{user_id}/active")
def set_user_active(user_id: int, payload: UserActiveInput, context: AuthContext = Depends(require_csrf), db: Session = Depends(get_db)) -> dict:
    require_admin(context)
    if user_id == context.user.id and not payload.active:
        raise api_error(409, "CANNOT_DISABLE_SELF", "不能停用当前登录的维护员账号")
    user = db.scalar(select(User).where(User.id == user_id).with_for_update())
    if user is None:
        raise api_error(404, "USER_NOT_FOUND", "账号不存在")
    if user.active == payload.active:
        raise api_error(409, "USER_UNCHANGED", "账号状态没有变化")
    before = "启用" if user.active else "停用"
    user.active = payload.active
    if not payload.active:
        for login in db.scalars(select(LoginSession).where(LoginSession.user_id == user_id, LoginSession.revoked_at.is_(None))).all():
            login.revoked_at = utc_now()
        for device in db.scalars(select(AuthorizedDevice).where(AuthorizedDevice.user_id == user_id, AuthorizedDevice.revoked_at.is_(None))).all():
            device.authorized = False
            device.revoked_at = utc_now()
    db.add(AuditLog(actor_user_id=context.user.id, action="USER_ACTIVE", entity=str(user_id), before=before, after="启用" if payload.active else "停用", reason=payload.reason.strip()))
    db.commit()
    return {"id": user.id, "active": user.active}


@auth_router.post("/users/{user_id}/reset-password")
def reset_user_password(user_id: int, payload: PasswordResetInput, context: AuthContext = Depends(require_csrf), db: Session = Depends(get_db)) -> dict:
    require_admin(context)
    user = db.scalar(select(User).where(User.id == user_id).with_for_update())
    if user is None:
        raise api_error(404, "USER_NOT_FOUND", "账号不存在")
    user.password_hash = hash_password(payload.password)
    for login in db.scalars(select(LoginSession).where(LoginSession.user_id == user_id, LoginSession.revoked_at.is_(None))).all():
        login.revoked_at = utc_now()
    for device in db.scalars(select(AuthorizedDevice).where(AuthorizedDevice.user_id == user_id, AuthorizedDevice.revoked_at.is_(None))).all():
        device.authorized = False
        device.revoked_at = utc_now()
    db.add(AuditLog(actor_user_id=context.user.id, action="USER_PASSWORD_RESET", entity=str(user_id), reason=payload.reason.strip()))
    db.commit()
    return {"id": user.id, "sessions_revoked": True, "devices_revoked": True}


@auth_router.get("/audit")
def list_audit(context: AuthContext = Depends(current_context), db: Session = Depends(get_db)) -> list[dict]:
    require_admin(context)
    logs = db.scalars(select(AuditLog).order_by(AuditLog.id.desc()).limit(100)).all()
    return [{"id": item.id, "time": item.created_at, "actor_user_id": item.actor_user_id, "action": item.action, "entity": item.entity, "before": item.before, "after": item.after, "reason": item.reason} for item in logs]


@device_router.post("/register")
def register_device(payload: DeviceInput, request: Request, response: Response, context: AuthContext = Depends(require_csrf), db: Session = Depends(get_db)) -> dict:
    if context.user.role != "WORKER" and context.user.role != "ADMIN":
        raise api_error(403, "FORBIDDEN", "当前账号不能登记作业设备")
    raw = secrets.token_urlsafe(32)
    device = AuthorizedDevice(user_id=context.user.id, label=payload.label.strip(), token_hash=token_hash(raw), authorized=False)
    db.add(device)
    db.commit()
    response.set_cookie(DEVICE_COOKIE, raw, max_age=60 * 60 * 24 * 180, httponly=True, secure=request.app.state.cookie_secure, samesite="lax", path="/")
    return {"id": device.id, "label": device.label, "authorized": False}


@device_router.get("")
def list_devices(context: AuthContext = Depends(current_context), db: Session = Depends(get_db)) -> list[dict]:
    query = select(AuthorizedDevice).order_by(AuthorizedDevice.id.desc())
    if context.user.role != "ADMIN":
        query = query.where(AuthorizedDevice.user_id == context.user.id)
    devices = db.scalars(query).all()
    return [{"id": item.id, "user_id": item.user_id, "username": item.user.username, "person": item.user.person.name if item.user.person else None, "label": item.label, "authorized": item.authorized, "revoked": item.revoked_at is not None} for item in devices]


@device_router.get("/current")
def current_device(request: Request, context: AuthContext = Depends(current_context), db: Session = Depends(get_db)) -> dict:
    raw = request.cookies.get(DEVICE_COOKIE)
    if not raw:
        return {"registered": False, "authorized": False}
    device = db.scalar(select(AuthorizedDevice).where(AuthorizedDevice.token_hash == token_hash(raw), AuthorizedDevice.user_id == context.user.id))
    if device is None:
        return {"registered": False, "authorized": False}
    return {"registered": True, "id": device.id, "label": device.label, "authorized": device.authorized and device.revoked_at is None, "revoked": device.revoked_at is not None}


@device_router.post("/{device_id}/authorize")
def authorize_device(device_id: int, context: AuthContext = Depends(require_csrf), db: Session = Depends(get_db)) -> dict:
    require_admin(context)
    device = db.get(AuthorizedDevice, device_id)
    if device is None or device.revoked_at is not None:
        raise api_error(404, "DEVICE_NOT_FOUND", "设备不存在或已撤销")
    device.authorized = True
    device.authorized_at = utc_now()
    db.commit()
    return {"id": device.id, "authorized": True}


@device_router.post("/{device_id}/revoke")
def revoke_device(device_id: int, context: AuthContext = Depends(require_csrf), db: Session = Depends(get_db)) -> dict:
    require_admin(context)
    device = db.get(AuthorizedDevice, device_id)
    if device is None:
        raise api_error(404, "DEVICE_NOT_FOUND", "设备不存在")
    device.authorized = False
    device.revoked_at = utc_now()
    db.commit()
    return {"id": device.id, "authorized": False}


@device_router.delete("/{device_id}")
def delete_device(device_id: int, context: AuthContext = Depends(require_csrf), db: Session = Depends(get_db)) -> dict:
    require_admin(context)
    device = db.scalar(select(AuthorizedDevice).where(AuthorizedDevice.id == device_id).with_for_update())
    if device is None:
        raise api_error(404, "DEVICE_NOT_FOUND", "设备不存在")
    if db.scalar(select(Operation.id).where(Operation.device_id == device_id).limit(1)) is not None:
        raise api_error(409, "DEVICE_IN_USE", "设备已有流转记录，不能删除；可撤销授权")
    label = device.label
    db.delete(device)
    db.add(AuditLog(actor_user_id=context.user.id, action="DEVICE_DELETE", entity=str(device_id), before=label))
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        raise api_error(409, "DEVICE_IN_USE", "设备已被业务记录引用，不能删除") from None
    return {"id": device_id, "label": label}
