"""add raw_metadata JSONB to mentions

Stores source-specific structured payload from connectors (openFDA reaction
terms, clinical-trial phase/status) so we can aggregate on it instead of parsing
free text.

Revision ID: d0e1f2a3b4c5
Revises: c9d0e1f2a3b4
Create Date: 2026-06-04
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = "d0e1f2a3b4c5"
down_revision = "c9d0e1f2a3b4"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column("mentions", sa.Column("raw_metadata", postgresql.JSONB(), nullable=True))


def downgrade():
    op.drop_column("mentions", "raw_metadata")
