from __future__ import annotations

from enum import Enum


class UserRole(str, Enum):
    CLIENT = "client"
    MANAGER = "manager"
    ADMIN = "admin"


class BookingStatus(str, Enum):
    NEW = "new"
    CONFIRMED = "confirmed"
    DONE = "done"
    CANCELLED = "cancelled"
    NO_SHOW = "no_show"


class NotificationType(str, Enum):
    REMINDER_24H = "reminder_24h"
    REMINDER_2H = "reminder_2h"
    MANAGER_ALERT = "manager_alert"


class NotificationStatus(str, Enum):
    PENDING = "pending"
    SENT = "sent"
    FAILED = "failed"
