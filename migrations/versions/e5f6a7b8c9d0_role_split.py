"""Split lab_user role into marketing + brand_manager

Replaces the generic `lab_user` UserRole with two distinct business personas:
`marketing` and `brand_manager`. Existing `lab_user` accounts are migrated to
`brand_manager` (the strategic owner of a brand is the closest 1:1 successor).

Postgres enums can't drop a value in place, so we swap the type:
  1. rename old type aside
  2. create the new 4-value type
  3. re-point users.role at it, mapping lab_user -> brand_manager
  4. drop the old type

Revision ID: e5f6a7b8c9d0
Revises: d4e5f6a7b8c9
Create Date: 2026-05-29 12:00:00.000000

"""
from typing import Sequence, Union

from alembic import op


revision: str = "e5f6a7b8c9d0"
down_revision: Union[str, None] = "d4e5f6a7b8c9"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute("ALTER TYPE userrole RENAME TO userrole_old")
    op.execute(
        "CREATE TYPE userrole AS ENUM "
        "('pharmacist', 'marketing', 'brand_manager', 'admin')"
    )
    # Drop the column default (if any) so the USING cast can run, then re-point.
    op.execute("ALTER TABLE users ALTER COLUMN role DROP DEFAULT")
    op.execute(
        "ALTER TABLE users ALTER COLUMN role TYPE userrole USING ("
        "  CASE role::text "
        "    WHEN 'lab_user' THEN 'brand_manager' "
        "    ELSE role::text "
        "  END"
        ")::userrole"
    )
    op.execute("DROP TYPE userrole_old")


def downgrade() -> None:
    op.execute("ALTER TYPE userrole RENAME TO userrole_new")
    op.execute(
        "CREATE TYPE userrole AS ENUM ('pharmacist', 'lab_user', 'admin')"
    )
    op.execute("ALTER TABLE users ALTER COLUMN role DROP DEFAULT")
    # marketing + brand_manager both collapse back to the generic lab_user.
    op.execute(
        "ALTER TABLE users ALTER COLUMN role TYPE userrole USING ("
        "  CASE role::text "
        "    WHEN 'marketing' THEN 'lab_user' "
        "    WHEN 'brand_manager' THEN 'lab_user' "
        "    ELSE role::text "
        "  END"
        ")::userrole"
    )
    op.execute("DROP TYPE userrole_new")