"""Review-native fields on mentions — rating / brand_name / product_name

Pharmacy product-review imports (farmaline, medimarket) carry structured
attributes the generic Mention model lacks. These columns let the review
sentiment dashboard aggregate by brand / product and compute avg-rating KPIs
without forcing review brands into the seeded `brands` table.

Revision ID: b8c9d0e1f2a3
Revises: a7b8c9d0e1f2
Create Date: 2026-06-02 00:00:00.000000
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op


revision: str = "b8c9d0e1f2a3"
down_revision: Union[str, None] = "a7b8c9d0e1f2"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("mentions", sa.Column("rating", sa.SmallInteger(), nullable=True))
    op.add_column("mentions", sa.Column("brand_name", sa.String(256), nullable=True))
    op.add_column("mentions", sa.Column("product_name", sa.String(512), nullable=True))
    op.create_index("ix_mentions_brand_name", "mentions", ["brand_name"])
    op.create_index("ix_mentions_source_type", "mentions", ["source_type"])


def downgrade() -> None:
    op.drop_index("ix_mentions_source_type", table_name="mentions")
    op.drop_index("ix_mentions_brand_name", table_name="mentions")
    op.drop_column("mentions", "product_name")
    op.drop_column("mentions", "brand_name")
    op.drop_column("mentions", "rating")
