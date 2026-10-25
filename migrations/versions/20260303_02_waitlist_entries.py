"""Add waitlist entries table.

Revision ID: 20260303_02
Revises: 20260302_01
Create Date: 2026-03-03 02:20:00
"""
from __future__ import annotations

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision = "20260303_02"
down_revision = "20260302_01"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "waitlist_entries",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("client_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("service_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("date", sa.Date(), nullable=False),
        sa.Column("comment", sa.Text(), nullable=True),
        sa.Column("source", sa.Text(), nullable=False, server_default="telegram"),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(
            ["client_id"],
            ["users.id"],
            name="fk_waitlist_entries_client_id_users",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["service_id"],
            ["services.id"],
            name="fk_waitlist_entries_service_id_services",
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_waitlist_entries"),
        sa.UniqueConstraint(
            "client_id",
            "service_id",
            "date",
            name="uq_waitlist_client_service_date",
        ),
    )
    op.create_index("idx_waitlist_date", "waitlist_entries", ["date"])
    op.create_index("idx_waitlist_service_date", "waitlist_entries", ["service_id", "date"])
    op.create_index("idx_waitlist_client_id", "waitlist_entries", ["client_id"])


def downgrade() -> None:
    op.drop_index("idx_waitlist_client_id", table_name="waitlist_entries")
    op.drop_index("idx_waitlist_service_date", table_name="waitlist_entries")
    op.drop_index("idx_waitlist_date", table_name="waitlist_entries")
    op.drop_table("waitlist_entries")
