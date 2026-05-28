"""action_events table — flywheel telemetry

Revision ID: a1f2d3e4b5c6
Revises: 601fe698a69e
Create Date: 2026-05-21 12:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision: str = "a1f2d3e4b5c6"
down_revision: Union[str, None] = "601fe698a69e"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # create_type=False stops sa.Column(..., enum) from re-issuing CREATE TYPE
    # — we create the types ourselves via .create(checkfirst=True) below.
    action_subject_type = postgresql.ENUM(
        "recommendation", "alert", "adverse_event", "ai_suggestion",
        "trend_signal", "bpi_score",
        name="actionsubjecttype",
        create_type=False,
    )
    action_subject_type.create(op.get_bind(), checkfirst=True)

    action_decision = postgresql.ENUM(
        "viewed", "accepted", "skipped", "acted_upon", "dismissed", "snoozed",
        name="actiondecision",
        create_type=False,
    )
    action_decision.create(op.get_bind(), checkfirst=True)

    op.create_table(
        "action_events",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("user_id", sa.Integer(), nullable=True),
        sa.Column("subject_type", action_subject_type, nullable=False),
        sa.Column("subject_id", sa.String(length=64), nullable=False),
        sa.Column("decision", action_decision, nullable=False),
        sa.Column("context", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_action_events_user_id", "action_events", ["user_id"])
    op.create_index("ix_action_events_subject_type", "action_events", ["subject_type"])
    op.create_index("ix_action_events_subject_id", "action_events", ["subject_id"])
    op.create_index("ix_action_events_decision", "action_events", ["decision"])
    op.create_index("ix_action_events_created_at", "action_events", ["created_at"])


def downgrade() -> None:
    op.drop_index("ix_action_events_created_at", table_name="action_events")
    op.drop_index("ix_action_events_decision", table_name="action_events")
    op.drop_index("ix_action_events_subject_id", table_name="action_events")
    op.drop_index("ix_action_events_subject_type", table_name="action_events")
    op.drop_index("ix_action_events_user_id", table_name="action_events")
    op.drop_table("action_events")
    sa.Enum(name="actiondecision").drop(op.get_bind(), checkfirst=True)
    sa.Enum(name="actionsubjecttype").drop(op.get_bind(), checkfirst=True)
