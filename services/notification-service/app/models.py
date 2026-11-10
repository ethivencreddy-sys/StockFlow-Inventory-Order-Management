
from datetime import datetime, timezone

from sqlalchemy import Column, DateTime, Integer, String, Text

from app.database import Base


def utc_now():
    return datetime.now(timezone.utc)


class Notification(Base):
    __tablename__ = "notifications"

    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, nullable=False, index=True)
    title = Column(String(200), nullable=False)
    message = Column(Text, nullable=False)
    notification_type = Column(String(50), nullable=False, default="general")
    status = Column(String(20), nullable=False, default="unread")
    channel = Column(String(20), nullable=False, default="in_app")

    created_at = Column(
        DateTime(timezone=True),
        default=utc_now,
        nullable=False,
    )
    read_at = Column(DateTime(timezone=True), nullable=True)
