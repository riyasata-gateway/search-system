"""search_queries, search_results, ai_answers — search audit tables

Revision ID: c3d4e5f6a7b8
Revises: b2e3f4a5c6d7
Create Date: 2026-05-28 12:30:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision: str = "c3d4e5f6a7b8"
down_revision: Union[str, None] = "b2e3f4a5c6d7"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    search_mode = postgresql.ENUM(
        "live", "ai", "semantic",
        name="searchmode",
        create_type=False,
    )
    search_mode.create(op.get_bind(), checkfirst=True)

    # `sentiment` enum already exists from the initial schema — reuse it.
    sentiment_enum = postgresql.ENUM(
        "positive", "neutral", "negative",
        name="sentiment",
        create_type=False,
    )

    op.create_table(
        "search_queries",
        sa.Column("id", postgresql.UUID(as_uuid=False), nullable=False),
        sa.Column("user_id", sa.Integer(), nullable=True),
        sa.Column("mode", search_mode, nullable=False),
        sa.Column("q", sa.String(length=512), nullable=False),
        sa.Column("lang", sa.String(length=8), nullable=True),
        sa.Column("sources_requested", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("expanded_terms", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("filters", postgresql.JSONB(astext_type=sa.Text()), nullable=True,
                  comment="Period, country, brand_id, etc. — kept flexible per mode"),
        sa.Column("total_results", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("elapsed_ms", sa.Integer(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_search_queries_user_id", "search_queries", ["user_id"])
    op.create_index("ix_search_queries_mode", "search_queries", ["mode"])
    op.create_index("ix_search_queries_q", "search_queries", ["q"])
    op.create_index("ix_search_queries_created_at", "search_queries", ["created_at"])

    op.create_table(
        "search_results",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("query_id", postgresql.UUID(as_uuid=False), nullable=False),
        sa.Column("rank", sa.Integer(), nullable=False),
        sa.Column("source_type", sa.String(length=64), nullable=True),
        sa.Column("source_url", sa.String(length=2048), nullable=True),
        sa.Column("snippet", sa.Text(), nullable=True),
        sa.Column("sentiment", sentiment_enum, nullable=True),
        sa.Column("topic", sa.String(length=32), nullable=True),
        sa.Column("risk_type", sa.String(length=32), nullable=True),
        sa.Column("score", sa.Numeric(6, 5), nullable=True,
                  comment="Cosine score for semantic mode; null otherwise"),
        sa.Column("mention_id", postgresql.UUID(as_uuid=False), nullable=True,
                  comment="Only set when result was matched to a stored mention (semantic mode)"),
        sa.Column("country", sa.String(length=2), nullable=True),
        sa.Column("language", sa.String(length=5), nullable=True),
        sa.Column("published_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(["query_id"], ["search_queries.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["mention_id"], ["mentions.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_search_results_query_id", "search_results", ["query_id"])
    op.create_index("ix_search_results_mention_id", "search_results", ["mention_id"])

    op.create_table(
        "ai_answers",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("query_id", postgresql.UUID(as_uuid=False), nullable=False),
        sa.Column("model", sa.String(length=64), nullable=False),
        sa.Column("answer", sa.Text(), nullable=False),
        sa.Column("key_points", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("sentiment_summary", sa.String(length=16), nullable=True),
        sa.Column("disclaimer", sa.Text(), nullable=True),
        sa.Column("grounding_sources", postgresql.JSONB(astext_type=sa.Text()), nullable=True,
                  comment="List of {ref, source_url, source_type, snippet} — the evidence the LLM saw"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["query_id"], ["search_queries.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("query_id", name="uq_ai_answers_query_id"),
    )


def downgrade() -> None:
    op.drop_table("ai_answers")
    op.drop_index("ix_search_results_mention_id", table_name="search_results")
    op.drop_index("ix_search_results_query_id", table_name="search_results")
    op.drop_table("search_results")
    op.drop_index("ix_search_queries_created_at", table_name="search_queries")
    op.drop_index("ix_search_queries_q", table_name="search_queries")
    op.drop_index("ix_search_queries_mode", table_name="search_queries")
    op.drop_index("ix_search_queries_user_id", table_name="search_queries")
    op.drop_table("search_queries")
    sa.Enum(name="searchmode").drop(op.get_bind(), checkfirst=True)