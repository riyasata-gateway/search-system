"""B3 — add 'reimbursement' value to the intent enum

Revision ID: a4b5c6d7e8f9
Revises: f3a4b5c6d7e8
Create Date: 2026-06-11 09:00:00.000000

"""
from typing import Sequence, Union

from alembic import op


revision: str = "a4b5c6d7e8f9"
down_revision: Union[str, None] = "f3a4b5c6d7e8"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute("ALTER TYPE intent ADD VALUE IF NOT EXISTS 'reimbursement'")


def downgrade() -> None:
    # Postgres enum value removal is unsafe; leave the value in place (harmless if unused).
    pass
