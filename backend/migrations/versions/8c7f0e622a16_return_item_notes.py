"""keep each abnormal return item's reason with its history

Revision ID: 8c7f0e622a16
Revises: 873c18a14a94
"""

from alembic import op
import sqlalchemy as sa


revision = "8c7f0e622a16"
down_revision = "873c18a14a94"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("operation_items", sa.Column("note", sa.String(length=300)))


def downgrade() -> None:
    if op.get_bind().scalar(sa.text("SELECT COUNT(*) FROM operation_items WHERE note IS NOT NULL")):
        raise RuntimeError("已有逐件归还原因，不能直接回退此迁移；请先备份并制定数据迁移方案")
    op.drop_column("operation_items", "note")
