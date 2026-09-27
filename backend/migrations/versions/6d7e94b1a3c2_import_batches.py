"""persist validated import previews and record honest initialization snapshots

Revision ID: 6d7e94b1a3c2
Revises: ce41a451dd8b
"""

from alembic import op
import sqlalchemy as sa


revision = "6d7e94b1a3c2"
down_revision = "ce41a451dd8b"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("operation_items") as batch_op:
        batch_op.alter_column("before_location_id", existing_type=sa.Integer(), nullable=True)
    op.create_table(
        "import_batches",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("token", sa.String(length=60), nullable=False, unique=True),
        sa.Column("sha256", sa.String(length=64), nullable=False),
        sa.Column("created_by_user_id", sa.Integer(), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("status", sa.String(length=20), nullable=False),
        sa.Column("row_count", sa.Integer(), nullable=False),
        sa.Column("payload_json", sa.Text(), nullable=False),
        sa.Column("result_json", sa.Text()),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("committed_at", sa.DateTime(timezone=True)),
    )


def downgrade() -> None:
    connection = op.get_bind()
    if connection.scalar(sa.text("SELECT COUNT(*) FROM import_batches")) or connection.scalar(sa.text("SELECT COUNT(*) FROM operation_items WHERE before_location_id IS NULL")):
        raise RuntimeError("已有导入记录或初始化流水，不能直接回退此迁移；请先备份并制定数据迁移方案")
    op.drop_table("import_batches")
    with op.batch_alter_table("operation_items") as batch_op:
        batch_op.alter_column("before_location_id", existing_type=sa.Integer(), nullable=False)
