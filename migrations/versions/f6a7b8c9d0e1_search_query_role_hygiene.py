"""Backfill retired `lab_user` role in the search-audit log

The `userrole` enum split (e5f6a7b8c9d0) migrated `lab_user` *accounts* to
`brand_manager`, but the historical `search_queries.role` column (a free-text
varchar stamped at search time) still carried the retired `lab_user` value on
older rows. That made the analytics role-usage table show a dead persona.

This migration aligns the audit log with the live role set:
  lab_user -> brand_manager   (same 1:1 successor as the account migration)

Rows with a NULL role (searches recorded before role tracking existed) are left
as-is — there's no defensible role to assign them, and analytics already groups
them under "unknown".

Revision ID: f6a7b8c9d0e1
Revises: e5f6a7b8c9d0
Create Date: 2026-05-29 13:30:00.000000
"""
from typing import Sequence, Union

from alembic import op


revision: str = "f6a7b8c9d0e1"
down_revision: Union[str, None] = "e5f6a7b8c9d0"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute(
        "UPDATE search_queries SET role = 'brand_manager' WHERE role = 'lab_user'"
    )


def downgrade() -> None:
    # Best-effort reverse: we can't tell which brand_manager rows were originally
    # lab_user, so the downgrade is intentionally a no-op (data-only migration).
    pass
