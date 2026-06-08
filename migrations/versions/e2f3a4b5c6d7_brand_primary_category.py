"""Brand primary-category (5-code supplier taxonomy)

Adds the coarse Belgian supplier taxonomy (NUT/RX/PAC/PEC/OTC) imported from the
supplier-categorisation workbook to the `brands` table, alongside the existing
fine-grained `category` (competitive family). Kept separate so peer-set / SoV
math (which keys on `category`) is unaffected. Powers the Brand Catalog filter.

Revision ID: e2f3a4b5c6d7
Revises: d1e2f3a4b5c6
Create Date: 2026-06-07 00:00:00.000000
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op


revision: str = "e2f3a4b5c6d7"
down_revision: Union[str, None] = "d1e2f3a4b5c6"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("brands", sa.Column("primary_category", sa.String(8), nullable=True))
    op.add_column("brands", sa.Column("category_confidence", sa.String(16), nullable=True))
    op.add_column("brands", sa.Column("category_rationale", sa.Text(), nullable=True))
    op.create_index("ix_brands_primary_category", "brands", ["primary_category"])


def downgrade() -> None:
    op.drop_index("ix_brands_primary_category", table_name="brands")
    op.drop_column("brands", "category_rationale")
    op.drop_column("brands", "category_confidence")
    op.drop_column("brands", "primary_category")