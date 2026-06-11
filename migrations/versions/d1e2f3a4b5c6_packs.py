"""canonical CNK-keyed pack registry (bilingual, pack-aware entity model)

Revision ID: d1e2f3a4b5c6
Revises: d0e1f2a3b4c5
Create Date: 2026-06-04
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = "d1e2f3a4b5c6"
down_revision = "d0e1f2a3b4c5"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "packs",
        sa.Column("cnk", sa.String(16), primary_key=True),
        sa.Column("brand_id", sa.Integer, sa.ForeignKey("brands.id", ondelete="SET NULL"), index=True),
        sa.Column("brand_name", sa.String(256), index=True),
        sa.Column("name_fr", sa.String(512)),
        sa.Column("name_nl", sa.String(512)),
        sa.Column("active_substance", sa.String(256)),
        sa.Column("atc", sa.String(16)),
        sa.Column("category", sa.String(160)),
        sa.Column("pharma_form", sa.String(160)),
        sa.Column("ean", sa.String(32)),
        sa.Column("kind", sa.String(24)),
        sa.Column("is_prescription", sa.Boolean),
        sa.Column("price", sa.Numeric(10, 2)),
        sa.Column("old_price", sa.Numeric(10, 2)),
        sa.Column("in_stock", sa.Boolean),
        sa.Column("rating", sa.Numeric(3, 2)),
        sa.Column("rating_count", sa.Integer),
        sa.Column("product_url", sa.String(1024)),
        sa.Column("sources", postgresql.JSONB),
    )


def downgrade():
    op.drop_table("packs")
