"""Add user locale preference.

Revision ID: 20260305_03
Revises: 20260303_02
Create Date: 2026-03-05 18:20:00
"""
from __future__ import annotations

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision = "20260305_03"
down_revision = "20260303_02"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "users",
        sa.Column("locale", sa.Text(), nullable=False, server_default="ru"),
    )


def downgrade() -> None:
    op.drop_column("users", "locale")
