"""shoe classifications and explicit per-set size plans"""
from alembic import op
import sqlalchemy as sa

revision = "d3b8a29401f6"
down_revision = "c29a7d103e82"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("mold_models", sa.Column("shoe_type", sa.String(10)))
    op.add_column("mold_sets", sa.Column("size_labels", sa.Text()))
    # A/B sets in the previous version were explicitly restricted to men's ten sizes.
    op.execute("UPDATE mold_models SET shoe_type='男鞋' WHERE id IN (SELECT model_id FROM mold_sets WHERE mold_category IS NOT NULL)")


def downgrade() -> None:
    connection = op.get_bind()
    if connection.scalar(sa.text("SELECT COUNT(*) FROM mold_models WHERE shoe_type IS NOT NULL")) or connection.scalar(sa.text("SELECT COUNT(*) FROM mold_sets WHERE size_labels IS NOT NULL")):
        raise RuntimeError("已有鞋类或整套码数资料，不能直接回退；请先备份并制定迁移方案")
    op.drop_column("mold_sets", "size_labels")
    op.drop_column("mold_models", "shoe_type")
