"""link reconciled stocktake findings to inventory operations

Revision ID: ce41a451dd8b
Revises: 8a60e4a82b6b
"""

from alembic import op
import sqlalchemy as sa


revision = "ce41a451dd8b"
down_revision = "8a60e4a82b6b"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "stocktake_adjustments",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("session_id", sa.Integer(), sa.ForeignKey("stocktake_sessions.id"), nullable=False),
        sa.Column("mold_id", sa.Integer(), sa.ForeignKey("molds.id"), nullable=False),
        sa.Column("operation_id", sa.Integer(), sa.ForeignKey("operations.id"), nullable=False, unique=True),
        sa.Column("type", sa.String(length=30), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_stocktake_adjustments_session_id", "stocktake_adjustments", ["session_id"])
    op.create_index("uq_stocktake_adjusted_mold", "stocktake_adjustments", ["session_id", "mold_id"], unique=True)


def downgrade() -> None:
    op.drop_index("uq_stocktake_adjusted_mold", table_name="stocktake_adjustments")
    op.drop_index("ix_stocktake_adjustments_session_id", table_name="stocktake_adjustments")
    op.drop_table("stocktake_adjustments")
