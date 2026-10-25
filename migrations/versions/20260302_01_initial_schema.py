"""Initial schema for Telegram booking bot MVP.

Revision ID: 20260302_01
Revises:
Create Date: 2026-03-02 22:25:00
"""
from __future__ import annotations

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision = "20260302_01"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()

    user_role = postgresql.ENUM("client", "manager", "admin", name="user_role", create_type=False)
    booking_status = postgresql.ENUM(
        "new", "confirmed", "done", "cancelled", "no_show", name="booking_status", create_type=False
    )
    notification_type = postgresql.ENUM(
        "reminder_24h", "reminder_2h", "manager_alert", name="notification_type", create_type=False
    )
    notification_status = postgresql.ENUM(
        "pending", "sent", "failed", name="notification_status", create_type=False
    )

    user_role.create(bind, checkfirst=True)
    booking_status.create(bind, checkfirst=True)
    notification_type.create(bind, checkfirst=True)
    notification_status.create(bind, checkfirst=True)

    op.create_table(
        "users",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("telegram_id", sa.BigInteger(), nullable=False),
        sa.Column("full_name", sa.Text(), nullable=True),
        sa.Column("phone", sa.Text(), nullable=True),
        sa.Column("role", user_role, nullable=False, server_default="client"),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.PrimaryKeyConstraint("id", name="pk_users"),
        sa.UniqueConstraint("telegram_id", name="uq_users_telegram_id"),
    )
    op.create_index("idx_users_telegram_id", "users", ["telegram_id"])
    op.create_index("idx_users_role", "users", ["role"])

    op.create_table(
        "services",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("name", sa.Text(), nullable=False),
        sa.Column("duration_min", sa.Integer(), nullable=False),
        sa.Column("price", sa.Numeric(10, 2), nullable=True),
        sa.Column("is_active", sa.Boolean(), server_default=sa.text("true"), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.PrimaryKeyConstraint("id", name="pk_services"),
    )

    op.create_table(
        "working_hours",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("weekday", sa.Integer(), nullable=False),
        sa.Column("start_time", sa.Time(), nullable=False),
        sa.Column("end_time", sa.Time(), nullable=False),
        sa.Column("is_working_day", sa.Boolean(), server_default=sa.text("true"), nullable=False),
        sa.CheckConstraint("weekday BETWEEN 1 AND 7", name="ck_working_hours_weekday_range"),
        sa.PrimaryKeyConstraint("id", name="pk_working_hours"),
        sa.UniqueConstraint("weekday", name="uq_working_hours_weekday"),
    )

    op.create_table(
        "bookings",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("client_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("service_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("date", sa.Date(), nullable=False),
        sa.Column("start_time", sa.Time(), nullable=False),
        sa.Column("end_time", sa.Time(), nullable=False),
        sa.Column("status", booking_status, nullable=False, server_default="new"),
        sa.Column("comment", sa.Text(), nullable=True),
        sa.Column("source", sa.Text(), nullable=False, server_default="telegram"),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(["client_id"], ["users.id"], name="fk_bookings_client_id_users", ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["service_id"], ["services.id"], name="fk_bookings_service_id_services", ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("id", name="pk_bookings"),
        sa.UniqueConstraint(
            "service_id",
            "date",
            "start_time",
            name="uq_bookings_service_date_start_time",
        ),
    )
    op.create_index("idx_bookings_date_time", "bookings", ["date", "start_time"])
    op.create_index("idx_bookings_status", "bookings", ["status"])
    op.create_index("idx_bookings_client_id", "bookings", ["client_id"])

    op.create_table(
        "notifications",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("booking_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("type", notification_type, nullable=False),
        sa.Column("scheduled_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("sent_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("status", notification_status, nullable=False, server_default="pending"),
        sa.Column("error", sa.Text(), nullable=True),
        sa.Column("attempts", sa.Integer(), nullable=False, server_default="0"),
        sa.ForeignKeyConstraint(["booking_id"], ["bookings.id"], name="fk_notifications_booking_id_bookings", ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id", name="pk_notifications"),
    )

    op.create_table(
        "audit_log",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("actor_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("entity_type", sa.Text(), nullable=False),
        sa.Column("entity_id", sa.Text(), nullable=False),
        sa.Column("action", sa.Text(), nullable=False),
        sa.Column("payload", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(["actor_id"], ["users.id"], name="fk_audit_log_actor_id_users", ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id", name="pk_audit_log"),
    )


def downgrade() -> None:
    bind = op.get_bind()

    op.drop_table("audit_log")
    op.drop_table("notifications")

    op.drop_index("idx_bookings_client_id", table_name="bookings")
    op.drop_index("idx_bookings_status", table_name="bookings")
    op.drop_index("idx_bookings_date_time", table_name="bookings")
    op.drop_table("bookings")

    op.drop_table("working_hours")
    op.drop_table("services")

    op.drop_index("idx_users_role", table_name="users")
    op.drop_index("idx_users_telegram_id", table_name="users")
    op.drop_table("users")

    notification_status = sa.Enum("pending", "sent", "failed", name="notification_status")
    notification_type = sa.Enum(
        "reminder_24h", "reminder_2h", "manager_alert", name="notification_type"
    )
    booking_status = sa.Enum(
        "new", "confirmed", "done", "cancelled", "no_show", name="booking_status"
    )
    user_role = sa.Enum("client", "manager", "admin", name="user_role")

    notification_status.drop(bind, checkfirst=True)
    notification_type.drop(bind, checkfirst=True)
    booking_status.drop(bind, checkfirst=True)
    user_role.drop(bind, checkfirst=True)
