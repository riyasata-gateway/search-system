"""Brand → Source → KPI framework fields on brands

Adds the Datatopia workbook's brand metadata to the `brands` table so the
catalog API and role dashboards can read category / tier-signal / KPI-interest
straight off the brand row. `manufacturer` already serves as the "Owner".

Revision ID: c9d0e1f2a3b4
Revises: b8c9d0e1f2a3
Create Date: 2026-06-03 00:00:00.000000
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op


revision: str = "c9d0e1f2a3b4"
down_revision: Union[str, None] = "b8c9d0e1f2a3"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("brands", sa.Column("category", sa.String(128), nullable=True))
    op.add_column("brands", sa.Column("tier_a_signal", sa.Text(), nullable=True))
    op.add_column("brands", sa.Column("tier_bc_signal", sa.Text(), nullable=True))
    op.add_column(
        "brands",
        sa.Column("kpi_roles", sa.ARRAY(sa.String(32)), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("brands", "kpi_roles")
    op.drop_column("brands", "tier_bc_signal")
    op.drop_column("brands", "tier_a_signal")
    op.drop_column("brands", "category")