"""alert_rules table — B7 user-defined saved threshold alert rules

Revision ID: f3a4b5c6d7e8
Revises: e2f3a4b5c6d7
Create Date: 2026-06-10 16:30:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision: str = "f3a4b5c6d7e8"
down_revision: Union[str, None] = "e2f3a4b5c6d7"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # New saved-rule alert type (additive to the existing alerttype enum).
    op.execute("ALTER TYPE alerttype ADD VALUE IF NOT EXISTS 'threshold_rule'")

    rule_metric = postgresql.ENUM(
        "bpi", "launch_readiness", "momentum", "sentiment",
        "complaint_rate", "brand_trust", "review_volume",
        name="rulemetric", create_type=False,
    )
    rule_metric.create(op.get_bind(), checkfirst=True)
    rule_operator = postgresql.ENUM(
        "lt", "lte", "gt", "gte", name="ruleoperator", create_type=False,
    )
    rule_operator.create(op.get_bind(), checkfirst=True)
    # alertseverity already exists (alerts table) — reference it, don't recreate.
    alert_severity = postgresql.ENUM(
        "low", "medium", "high", "critical", name="alertseverity", create_type=False,
    )

    op.create_table(
        "alert_rules",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("owner_id", sa.Integer(), nullable=False),
        sa.Column("name", sa.String(length=120), nullable=False),
        sa.Column("metric", rule_metric, nullable=False),
        sa.Column("operator", rule_operator, nullable=False),
        sa.Column("threshold", sa.Float(), nullable=False),
        sa.Column("brand_id", sa.Integer(), nullable=True),
        sa.Column("severity", alert_severity, nullable=False, server_default="medium"),
        sa.Column("active", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("last_evaluated_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_triggered_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(["owner_id"], ["users.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["brand_id"], ["brands.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_alert_rules_owner_id", "alert_rules", ["owner_id"])


def downgrade() -> None:
    op.drop_index("ix_alert_rules_owner_id", table_name="alert_rules")
    op.drop_table("alert_rules")
    sa.Enum(name="ruleoperator").drop(op.get_bind(), checkfirst=True)
    sa.Enum(name="rulemetric").drop(op.get_bind(), checkfirst=True)
    # alerttype value 'threshold_rule' is left in place (enum value removal is
    # unsafe in Postgres); harmless if unused.
