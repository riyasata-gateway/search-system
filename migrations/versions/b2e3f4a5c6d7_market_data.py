"""market_data, prescription_events, market_data_imports

Revision ID: b2e3f4a5c6d7
Revises: a1f2d3e4b5c6
Create Date: 2026-05-21 14:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision: str = "b2e3f4a5c6d7"
down_revision: Union[str, None] = "a1f2d3e4b5c6"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # create_type=False stops sa.Column(..., enum) from re-issuing CREATE TYPE
    # — we create the types ourselves via .create(checkfirst=True) below.
    market_data_source = postgresql.ENUM(
        "iqvia", "gers", "ims", "other",
        name="marketdatasource",
        create_type=False,
    )
    market_data_source.create(op.get_bind(), checkfirst=True)

    market_data_period = postgresql.ENUM(
        "weekly", "monthly", "quarterly",
        name="marketdataperiod",
        create_type=False,
    )
    market_data_period.create(op.get_bind(), checkfirst=True)

    op.create_table(
        "market_data",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("source", market_data_source, nullable=False),
        sa.Column("product_id", sa.Integer(), nullable=True),
        sa.Column("brand_id", sa.Integer(), nullable=True),
        sa.Column("country", sa.String(length=2), nullable=False),
        sa.Column("region", sa.String(length=128), nullable=True),
        sa.Column("period", market_data_period, nullable=False),
        sa.Column("period_start", sa.Date(), nullable=False),
        sa.Column("period_end", sa.Date(), nullable=False),
        sa.Column("units", sa.Integer(), nullable=True),
        sa.Column("revenue_eur", sa.Numeric(14, 2), nullable=True),
        sa.Column("market_share_pct", sa.Numeric(5, 2), nullable=True),
        sa.Column("source_filename", sa.String(length=255), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["product_id"], ["products.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["brand_id"], ["brands.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("source", "product_id", "brand_id", "country", "region",
                             "period", "period_start", name="uq_market_data_row"),
    )
    op.create_index("ix_market_data_country", "market_data", ["country"])
    op.create_index("ix_market_data_period_start", "market_data", ["period_start"])

    op.create_table(
        "prescription_events",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("product_id", sa.Integer(), nullable=True),
        sa.Column("brand_id", sa.Integer(), nullable=True),
        sa.Column("country", sa.String(length=2), nullable=False),
        sa.Column("region", sa.String(length=128), nullable=True),
        sa.Column("hcp_id_hash", sa.String(length=64), nullable=True),
        sa.Column("hcp_specialty", sa.String(length=64), nullable=True),
        sa.Column("patient_age_band", sa.String(length=8), nullable=True),
        sa.Column("patient_sex", sa.String(length=1), nullable=True),
        sa.Column("rx_date", sa.Date(), nullable=False),
        sa.Column("units", sa.Integer(), nullable=False),
        sa.Column("is_new_to_brand", sa.Boolean(), nullable=False),
        sa.Column("collected_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("retention_expires_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("source_filename", sa.String(length=255), nullable=True),
        sa.ForeignKeyConstraint(["product_id"], ["products.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["brand_id"], ["brands.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_prescription_events_brand_id", "prescription_events", ["brand_id"])
    op.create_index("ix_prescription_events_country", "prescription_events", ["country"])
    op.create_index("ix_prescription_events_hcp_id_hash", "prescription_events", ["hcp_id_hash"])
    op.create_index("ix_prescription_events_rx_date", "prescription_events", ["rx_date"])

    op.create_table(
        "market_data_imports",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("uploaded_by", sa.Integer(), nullable=True),
        sa.Column("source", market_data_source, nullable=False),
        sa.Column("kind", sa.String(length=32), nullable=False),
        sa.Column("filename", sa.String(length=255), nullable=False),
        sa.Column("row_count", sa.Integer(), nullable=False),
        sa.Column("rejected_count", sa.Integer(), nullable=False),
        sa.Column("uploaded_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("notes", sa.String(length=512), nullable=True),
        sa.ForeignKeyConstraint(["uploaded_by"], ["users.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
    )


def downgrade() -> None:
    op.drop_table("market_data_imports")
    op.drop_index("ix_prescription_events_rx_date", table_name="prescription_events")
    op.drop_index("ix_prescription_events_hcp_id_hash", table_name="prescription_events")
    op.drop_index("ix_prescription_events_country", table_name="prescription_events")
    op.drop_index("ix_prescription_events_brand_id", table_name="prescription_events")
    op.drop_table("prescription_events")
    op.drop_index("ix_market_data_period_start", table_name="market_data")
    op.drop_index("ix_market_data_country", table_name="market_data")
    op.drop_table("market_data")
    sa.Enum(name="marketdataperiod").drop(op.get_bind(), checkfirst=True)
    sa.Enum(name="marketdatasource").drop(op.get_bind(), checkfirst=True)
