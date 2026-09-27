"""link compensating operations to their original document

Revision ID: a42c7e9d105b
Revises: 8c7f0e622a16
"""

from alembic import op
import sqlalchemy as sa


revision = "a42c7e9d105b"
down_revision = "8c7f0e622a16"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("operations", sa.Column("correction_of_operation_id", sa.Integer()))
    op.create_index("uq_operations_correction_of", "operations", ["correction_of_operation_id"], unique=True)


def downgrade() -> None:
    if op.get_bind().scalar(sa.text("SELECT COUNT(*) FROM operations WHERE correction_of_operation_id IS NOT NULL")):
        raise RuntimeError("已有补偿更正单据，不能直接回退此迁移；请先备份并制定数据迁移方案")
    op.drop_index("uq_operations_correction_of", table_name="operations")
    op.drop_column("operations", "correction_of_operation_id")
