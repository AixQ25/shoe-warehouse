"""identify A/B sets within a model while preserving legacy identities"""

from alembic import op
import sqlalchemy as sa

revision = "c29a7d103e82"
down_revision = "b18d6f024c91"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Legacy sets stay unclassified: do not guess A/B from arbitrary old codes.
    op.add_column("mold_sets", sa.Column("mold_category", sa.String(10)))
    op.create_index("uq_model_set_category", "mold_sets", ["model_id", "mold_category"], unique=True)


def downgrade() -> None:
    if op.get_bind().scalar(sa.text("SELECT COUNT(*) FROM mold_sets WHERE mold_category IS NOT NULL")):
        raise RuntimeError("已有 A/B 套别资料，不能直接回退此迁移；请先备份并制定数据迁移方案")
    op.drop_index("uq_model_set_category", table_name="mold_sets")
    op.drop_column("mold_sets", "mold_category")
