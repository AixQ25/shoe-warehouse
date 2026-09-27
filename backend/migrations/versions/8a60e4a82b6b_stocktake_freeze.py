"""stocktake sessions, snapshots and scans

Revision ID: 8a60e4a82b6b
Revises: f3038d03c747
"""

from alembic import op
import sqlalchemy as sa


revision = "8a60e4a82b6b"
down_revision = "f3038d03c747"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "stocktake_sessions",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("location_id", sa.Integer(), sa.ForeignKey("locations.id"), nullable=False),
        sa.Column("status", sa.String(length=20), nullable=False),
        sa.Column("created_by_user_id", sa.Integer(), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("submitted_at", sa.DateTime(timezone=True)),
        sa.Column("location_verified_at", sa.DateTime(timezone=True)),
        sa.Column("location_verified_by_user_id", sa.Integer(), sa.ForeignKey("users.id")),
        sa.Column("closed_at", sa.DateTime(timezone=True)),
        sa.Column("closed_by_user_id", sa.Integer(), sa.ForeignKey("users.id")),
        sa.Column("close_reason", sa.String(length=300)),
    )
    op.create_index("ix_stocktake_sessions_location_id", "stocktake_sessions", ["location_id"])
    op.create_index("uq_open_stocktake_location", "stocktake_sessions", ["location_id"], unique=True, postgresql_where=sa.text("status IN ('ACTIVE', 'SUBMITTED')"), sqlite_where=sa.text("status IN ('ACTIVE', 'SUBMITTED')"))
    op.create_table(
        "stocktake_expected",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("session_id", sa.Integer(), sa.ForeignKey("stocktake_sessions.id"), nullable=False),
        sa.Column("mold_id", sa.Integer(), sa.ForeignKey("molds.id"), nullable=False),
        sa.Column("expected_version", sa.Integer(), nullable=False),
        sa.Column("expected_status", sa.String(length=30), nullable=False),
    )
    op.create_index("ix_stocktake_expected_session_id", "stocktake_expected", ["session_id"])
    op.create_index("uq_stocktake_expected_mold", "stocktake_expected", ["session_id", "mold_id"], unique=True)
    op.create_table(
        "stocktake_scans",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("session_id", sa.Integer(), sa.ForeignKey("stocktake_sessions.id"), nullable=False),
        sa.Column("code", sa.String(length=80), nullable=False),
        sa.Column("mold_id", sa.Integer(), sa.ForeignKey("molds.id")),
        sa.Column("result", sa.String(length=30), nullable=False),
        sa.Column("scanned_by_user_id", sa.Integer(), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("scanned_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_stocktake_scans_session_id", "stocktake_scans", ["session_id"])
    op.create_index("uq_stocktake_scan_code", "stocktake_scans", ["session_id", "code"], unique=True)


def downgrade() -> None:
    op.drop_index("uq_stocktake_scan_code", table_name="stocktake_scans")
    op.drop_index("ix_stocktake_scans_session_id", table_name="stocktake_scans")
    op.drop_table("stocktake_scans")
    op.drop_index("uq_stocktake_expected_mold", table_name="stocktake_expected")
    op.drop_index("ix_stocktake_expected_session_id", table_name="stocktake_expected")
    op.drop_table("stocktake_expected")
    op.drop_index("uq_open_stocktake_location", table_name="stocktake_sessions")
    op.drop_index("ix_stocktake_sessions_location_id", table_name="stocktake_sessions")
    op.drop_table("stocktake_sessions")
