from __future__ import annotations

from datetime import date, datetime, timezone

from sqlalchemy import Boolean, Date, DateTime, ForeignKey, Index, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from .database import Base


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


class Person(Base):
    __tablename__ = "people"
    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(80), nullable=False)
    employee_code: Mapped[str | None] = mapped_column(String(50), unique=True)
    active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)


class User(Base):
    __tablename__ = "users"
    id: Mapped[int] = mapped_column(primary_key=True)
    username: Mapped[str] = mapped_column(String(80), unique=True, nullable=False)
    password_hash: Mapped[str] = mapped_column(String(200), nullable=False)
    role: Mapped[str] = mapped_column(String(20), nullable=False)
    person_id: Mapped[int | None] = mapped_column(ForeignKey("people.id"), unique=True)
    active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    person: Mapped[Person | None] = relationship()


class LoginSession(Base):
    __tablename__ = "login_sessions"
    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), nullable=False, index=True)
    token_hash: Mapped[str] = mapped_column(String(64), unique=True, nullable=False)
    csrf_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class AuthorizedDevice(Base):
    __tablename__ = "authorized_devices"
    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), nullable=False, index=True)
    label: Mapped[str] = mapped_column(String(100), nullable=False)
    token_hash: Mapped[str] = mapped_column(String(64), unique=True, nullable=False)
    authorized: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now, nullable=False)
    authorized_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    user: Mapped[User] = relationship()


class Location(Base):
    __tablename__ = "locations"
    id: Mapped[int] = mapped_column(primary_key=True)
    code: Mapped[str] = mapped_column(String(80), unique=True, nullable=False)
    name: Mapped[str] = mapped_column(String(120), nullable=False)
    type: Mapped[str] = mapped_column(String(20), nullable=False)
    zone: Mapped[str | None] = mapped_column(String(20))
    rack: Mapped[str | None] = mapped_column(String(20))
    level: Mapped[str | None] = mapped_column(String(20))
    active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)


class MoldModel(Base):
    __tablename__ = "mold_models"
    id: Mapped[int] = mapped_column(primary_key=True)
    code: Mapped[str] = mapped_column(String(80), unique=True, nullable=False)
    name: Mapped[str] = mapped_column(String(120), nullable=False)
    notes: Mapped[str | None] = mapped_column(Text)
    shoe_type: Mapped[str | None] = mapped_column(String(10))


class MoldSet(Base):
    __tablename__ = "mold_sets"
    id: Mapped[int] = mapped_column(primary_key=True)
    code: Mapped[str] = mapped_column(String(80), unique=True, nullable=False)
    model_id: Mapped[int] = mapped_column(ForeignKey("mold_models.id"), nullable=False)
    mold_category: Mapped[str | None] = mapped_column(String(10))
    size_labels: Mapped[str | None] = mapped_column(Text)
    default_location_id: Mapped[int] = mapped_column(ForeignKey("locations.id"), nullable=False)
    active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    model: Mapped[MoldModel] = relationship()
    default_location: Mapped[Location] = relationship()


Index("uq_model_set_category", MoldSet.model_id, MoldSet.mold_category, unique=True)


class Mold(Base):
    __tablename__ = "molds"
    id: Mapped[int] = mapped_column(primary_key=True)
    code: Mapped[str] = mapped_column(String(80), unique=True, nullable=False)
    original_code: Mapped[str | None] = mapped_column(String(100))
    set_id: Mapped[int] = mapped_column(ForeignKey("mold_sets.id"), nullable=False, index=True)
    size_label: Mapped[str] = mapped_column(String(30), nullable=False)
    manufacturer: Mapped[str | None] = mapped_column(String(100))
    mold_category: Mapped[str | None] = mapped_column(String(30))
    pairs_per_mold: Mapped[int | None] = mapped_column(Integer)
    sole_material: Mapped[str | None] = mapped_column(String(30))
    initial_quarter: Mapped[str | None] = mapped_column(String(5))
    opened_on: Mapped[date | None] = mapped_column(Date)
    status: Mapped[str] = mapped_column(String(30), nullable=False)
    current_location_id: Mapped[int] = mapped_column(ForeignKey("locations.id"), nullable=False)
    custodian_person_id: Mapped[int | None] = mapped_column(ForeignKey("people.id"))
    is_current: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    version: Mapped[int] = mapped_column(Integer, default=1, nullable=False)
    __mapper_args__ = {"version_id_col": version}
    set: Mapped[MoldSet] = relationship()
    current_location: Mapped[Location] = relationship()
    custodian: Mapped[Person | None] = relationship()


Index("uq_current_set_size", Mold.set_id, Mold.size_label, unique=True, postgresql_where=Mold.is_current.is_(True), sqlite_where=Mold.is_current.is_(True))


class StocktakeSession(Base):
    __tablename__ = "stocktake_sessions"
    id: Mapped[int] = mapped_column(primary_key=True)
    location_id: Mapped[int] = mapped_column(ForeignKey("locations.id"), nullable=False, index=True)
    status: Mapped[str] = mapped_column(String(20), nullable=False)
    created_by_user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now, nullable=False)
    submitted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    location_verified_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    location_verified_by_user_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"))
    closed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    closed_by_user_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"))
    close_reason: Mapped[str | None] = mapped_column(String(300))
    location: Mapped[Location] = relationship()
    expected: Mapped[list[StocktakeExpected]] = relationship(back_populates="session", cascade="all, delete-orphan")
    scans: Mapped[list[StocktakeScan]] = relationship(back_populates="session", cascade="all, delete-orphan")
    adjustments: Mapped[list[StocktakeAdjustment]] = relationship(back_populates="session", cascade="all, delete-orphan")


Index("uq_open_stocktake_location", StocktakeSession.location_id, unique=True, postgresql_where=StocktakeSession.status.in_(["ACTIVE", "SUBMITTED"]), sqlite_where=StocktakeSession.status.in_(["ACTIVE", "SUBMITTED"]))


class StocktakeExpected(Base):
    __tablename__ = "stocktake_expected"
    id: Mapped[int] = mapped_column(primary_key=True)
    session_id: Mapped[int] = mapped_column(ForeignKey("stocktake_sessions.id"), nullable=False, index=True)
    mold_id: Mapped[int] = mapped_column(ForeignKey("molds.id"), nullable=False)
    expected_version: Mapped[int] = mapped_column(Integer, nullable=False)
    expected_status: Mapped[str] = mapped_column(String(30), nullable=False)
    session: Mapped[StocktakeSession] = relationship(back_populates="expected")
    mold: Mapped[Mold] = relationship()


Index("uq_stocktake_expected_mold", StocktakeExpected.session_id, StocktakeExpected.mold_id, unique=True)


class StocktakeScan(Base):
    __tablename__ = "stocktake_scans"
    id: Mapped[int] = mapped_column(primary_key=True)
    session_id: Mapped[int] = mapped_column(ForeignKey("stocktake_sessions.id"), nullable=False, index=True)
    code: Mapped[str] = mapped_column(String(80), nullable=False)
    mold_id: Mapped[int | None] = mapped_column(ForeignKey("molds.id"))
    result: Mapped[str] = mapped_column(String(30), nullable=False)
    scanned_by_user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), nullable=False)
    scanned_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now, nullable=False)
    session: Mapped[StocktakeSession] = relationship(back_populates="scans")
    mold: Mapped[Mold | None] = relationship()


Index("uq_stocktake_scan_code", StocktakeScan.session_id, StocktakeScan.code, unique=True)


class StocktakeAdjustment(Base):
    __tablename__ = "stocktake_adjustments"
    id: Mapped[int] = mapped_column(primary_key=True)
    session_id: Mapped[int] = mapped_column(ForeignKey("stocktake_sessions.id"), nullable=False, index=True)
    mold_id: Mapped[int] = mapped_column(ForeignKey("molds.id"), nullable=False)
    operation_id: Mapped[int] = mapped_column(ForeignKey("operations.id"), nullable=False, unique=True)
    type: Mapped[str] = mapped_column(String(30), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now, nullable=False)
    session: Mapped[StocktakeSession] = relationship(back_populates="adjustments")
    mold: Mapped[Mold] = relationship()
    operation: Mapped[Operation] = relationship()


Index("uq_stocktake_adjusted_mold", StocktakeAdjustment.session_id, StocktakeAdjustment.mold_id, unique=True)


class Operation(Base):
    __tablename__ = "operations"
    id: Mapped[int] = mapped_column(primary_key=True)
    request_id: Mapped[str] = mapped_column(String(60), unique=True, nullable=False)
    payload_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    type: Mapped[str] = mapped_column(String(30), nullable=False)
    actor_user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), nullable=False)
    device_id: Mapped[int | None] = mapped_column(ForeignKey("authorized_devices.id"))
    target_location_id: Mapped[int] = mapped_column(ForeignKey("locations.id"), nullable=False)
    reason: Mapped[str | None] = mapped_column(String(300))
    correction_of_operation_id: Mapped[int | None] = mapped_column(Integer)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now, nullable=False)
    actor: Mapped[User] = relationship()
    target_location: Mapped[Location] = relationship()
    items: Mapped[list[OperationItem]] = relationship(back_populates="operation", cascade="all, delete-orphan")


Index("uq_operations_correction_of", Operation.correction_of_operation_id, unique=True)


class OperationItem(Base):
    __tablename__ = "operation_items"
    id: Mapped[int] = mapped_column(primary_key=True)
    operation_id: Mapped[int] = mapped_column(ForeignKey("operations.id"), nullable=False, index=True)
    mold_id: Mapped[int] = mapped_column(ForeignKey("molds.id"), nullable=False)
    before_status: Mapped[str] = mapped_column(String(30), nullable=False)
    after_status: Mapped[str] = mapped_column(String(30), nullable=False)
    before_location_id: Mapped[int | None] = mapped_column(ForeignKey("locations.id"))
    after_location_id: Mapped[int] = mapped_column(ForeignKey("locations.id"), nullable=False)
    before_custodian_id: Mapped[int | None] = mapped_column(ForeignKey("people.id"))
    after_custodian_id: Mapped[int | None] = mapped_column(ForeignKey("people.id"))
    before_version: Mapped[int] = mapped_column(Integer, nullable=False)
    after_version: Mapped[int] = mapped_column(Integer, nullable=False)
    note: Mapped[str | None] = mapped_column(String(300))
    operation: Mapped[Operation] = relationship(back_populates="items")
    mold: Mapped[Mold] = relationship()


class AuditLog(Base):
    __tablename__ = "audit_logs"
    id: Mapped[int] = mapped_column(primary_key=True)
    actor_user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), nullable=False)
    action: Mapped[str] = mapped_column(String(80), nullable=False)
    entity: Mapped[str] = mapped_column(String(100), nullable=False)
    before: Mapped[str | None] = mapped_column(Text)
    after: Mapped[str | None] = mapped_column(Text)
    reason: Mapped[str | None] = mapped_column(String(300))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now, nullable=False)


class ImportBatch(Base):
    __tablename__ = "import_batches"
    id: Mapped[int] = mapped_column(primary_key=True)
    token: Mapped[str] = mapped_column(String(60), unique=True, nullable=False)
    sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    created_by_user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), nullable=False)
    status: Mapped[str] = mapped_column(String(20), nullable=False)
    row_count: Mapped[int] = mapped_column(Integer, nullable=False)
    payload_json: Mapped[str] = mapped_column(Text, nullable=False)
    result_json: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now, nullable=False)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    committed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class LabelPrintBatch(Base):
    __tablename__ = "label_print_batches"
    id: Mapped[int] = mapped_column(primary_key=True)
    request_id: Mapped[str] = mapped_column(String(60), unique=True, nullable=False)
    actor_user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), nullable=False)
    kind: Mapped[str] = mapped_column(String(20), nullable=False)
    purpose: Mapped[str] = mapped_column(String(20), nullable=False)
    codes_json: Mapped[str] = mapped_column(Text, nullable=False)
    reason: Mapped[str | None] = mapped_column(String(300))
    requested_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now, nullable=False)
