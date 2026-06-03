"""Per-search metrics table — persists role-tailored DIA metrics per /search call

Revision ID: a7b8c9d0e1f2
Revises: f6a7b8c9d0e1
Create Date: 2026-05-29 19:00:00.000000
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSONB, UUID


revision: str = "a7b8c9d0e1f2"
down_revision: Union[str, None] = "f6a7b8c9d0e1"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "search_metrics",
        sa.Column("id", sa.Integer, primary_key=True, autoincrement=True),
        sa.Column("query_id", UUID(as_uuid=False),
                  sa.ForeignKey("search_queries.id", ondelete="CASCADE"), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False,
                  server_default=sa.func.now()),
        sa.Column("role", sa.String(16), nullable=True),
        sa.Column("mode", sa.String(16), nullable=True),
        sa.Column("brand_resolved", sa.Boolean, nullable=False, server_default=sa.false()),
        sa.Column("brand_id", sa.Integer, nullable=True),
        sa.Column("brand_name", sa.String(255), nullable=True),
        # framework tier
        sa.Column("bpi", sa.Numeric(6, 2), nullable=True),
        sa.Column("bpi_awareness", sa.Numeric(5, 4), nullable=True),
        sa.Column("bpi_adoption", sa.Numeric(5, 4), nullable=True),
        sa.Column("bpi_sentiment", sa.Numeric(5, 4), nullable=True),
        sa.Column("bpi_market_fit", sa.Numeric(5, 4), nullable=True),
        sa.Column("bpi_confidence", sa.Numeric(5, 4), nullable=True),
        sa.Column("adoption_is_proxy", sa.Boolean, nullable=True),
        sa.Column("sov_percent", sa.Numeric(6, 2), nullable=True),
        sa.Column("momentum_score", sa.Numeric(8, 2), nullable=True),
        sa.Column("lifecycle_stage", sa.String(32), nullable=True),
        sa.Column("launch_readiness", sa.Numeric(6, 2), nullable=True),
        # snapshot tier
        sa.Column("total", sa.Integer, nullable=False, server_default="0"),
        sa.Column("sentiment_index", sa.Numeric(5, 4), nullable=True),
        sa.Column("net_sentiment_label", sa.String(16), nullable=True),
        sa.Column("reach_total", sa.Integer, nullable=True),
        sa.Column("engagement_rate", sa.Numeric(12, 2), nullable=True),
        sa.Column("risk_share", sa.Numeric(5, 4), nullable=True),
        sa.Column("official_coverage", sa.Numeric(5, 4), nullable=True),
        sa.Column("source_diversity", sa.Integer, nullable=True),
        # detail
        sa.Column("framework", JSONB, nullable=True),
        sa.Column("snapshot", JSONB, nullable=True),
        sa.Column("headline", JSONB, nullable=True),
    )
    op.create_unique_constraint("uq_search_metrics_query_id", "search_metrics", ["query_id"])
    op.create_index("ix_search_metrics_query_id", "search_metrics", ["query_id"])
    op.create_index("ix_search_metrics_created_at", "search_metrics", ["created_at"])
    op.create_index("ix_search_metrics_role", "search_metrics", ["role"])
    op.create_index("ix_search_metrics_brand_id", "search_metrics", ["brand_id"])


def downgrade() -> None:
    op.drop_table("search_metrics")
