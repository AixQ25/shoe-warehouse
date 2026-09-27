"""record label print requests without altering asset identity

Revision ID: 873c18a14a94
Revises: 6d7e94b1a3c2
"""

from alembic import op
import sqlalchemy as sa


revision = "873c18a14a94"
down_revision = "6d7e94b1a3c2"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "label_print_batches",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("request_id", sa.String(length=60), unique=True, nullable=False),
        sa.Column("actor_user_id", sa.Integer(), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("kind", sa.String(length=20), nullable=False),
        sa.Column("purpose", sa.String(length=20), nullable=False),
        sa.Column("codes_json", sa.Text(), nullable=False),
        sa.Column("reason", sa.String(length=300)),
        sa.Column("requested_at", sa.DateTime(timezone=True), nullable=False),
    )


def downgrade() -> None:
    if op.get_bind().scalar(sa.text("SELECT COUNT(*) FROM label_print_batches")):
        raise RuntimeError("已有标签打印请求记录，不能直接回退此迁移；请先备份并制定数据迁移方案")
    op.drop_table("label_print_batches")
