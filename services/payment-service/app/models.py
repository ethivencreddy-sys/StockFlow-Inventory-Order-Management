
from datetime import datetime, timezone

from sqlalchemy import Column, DateTime, Float, Integer, String

from app.database import Base


def utc_now():
    return datetime.now(timezone.utc)


class Payment(Base):
    __tablename__ = "payments"

    id = Column(Integer, primary_key=True, index=True)
    order_id = Column(Integer, nullable=False, index=True)
    user_id = Column(Integer, nullable=False, index=True)

    amount = Column(Float, nullable=False)
    currency = Column(String(3), nullable=False, default="INR")
    payment_method = Column(String(30), nullable=False, default="card")
    status = Column(String(30), nullable=False, default="pending")

    transaction_id = Column(String(100), nullable=True, unique=True)
    failure_reason = Column(String(500), nullable=True)

    created_at = Column(
        DateTime(timezone=True),
        default=utc_now,
        nullable=False,
    )
    updated_at = Column(
        DateTime(timezone=True),
        default=utc_now,
        onupdate=utc_now,
        nullable=False,
    )
