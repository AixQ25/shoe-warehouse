"""add optional per-mold label metadata without changing asset identities"""

from alembic import op
import sqlalchemy as sa

revision = "b18d6f024c91"
down_revision = "a42c7e9d105b"
branch_labels = None
depends_on = None


def upgrade() -> None:
    for column in (
        sa.Column("manufacturer", sa.String(100)),
        sa.Column("mold_category", sa.String(30)),
        sa.Column("pairs_per_mold", sa.Integer()),
        sa.Column("sole_material", sa.String(30)),
        sa.Column("initial_quarter", sa.String(5)),
        sa.Column("opened_on", sa.Date()),
    ):
        op.add_column("molds", column)


def downgrade() -> None:
    fields = ("manufacturer", "mold_category", "pairs_per_mold", "sole_material", "initial_quarter", "opened_on")
    populated = " OR ".join(f"{field} IS NOT NULL" for field in fields)
    if op.get_bind().scalar(sa.text(f"SELECT COUNT(*) FROM molds WHERE {populated}")):
        raise RuntimeError("已有模具标签资料，不能直接回退此迁移；请先备份并制定数据迁移方案")
    for field in reversed(fields):
        op.drop_column("molds", field)
