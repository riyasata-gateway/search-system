"""search_queries.role — role lens applied to each search (role-based analytics)

Revision ID: d4e5f6a7b8c9
Revises: c3d4e5f6a7b8
Create Date: 2026-05-29 10:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "d4e5f6a7b8c9"
down_revision: Union[str, None] = "c3d4e5f6a7b8"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "search_queries",
        sa.Column(
            "role",
            sa.String(length=16),
            nullable=True,
            comment="Role lens applied to this search (pharmacist/lab_user/admin) — powers role-based analytics",
        ),
    )
    op.create_index("ix_search_queries_role", "search_queries", ["role"])


def downgrade() -> None:
    op.drop_index("ix_search_queries_role", table_name="search_queries")
    op.drop_column("search_queries", "role")
