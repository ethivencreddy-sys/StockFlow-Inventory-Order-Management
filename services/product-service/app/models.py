
from datetime import datetime, timezone

from sqlalchemy import (
    Boolean,
    Column,
    DateTime,
    Float,
    Integer,
    String,
    Text,
)

from app.database import Base


def utc_now():
    return datetime.now(timezone.utc)


class Product(Base):
    __tablename__ = "products"

    id = Column(Integer, primary_key=True, index=True)
    name = Column(String(150), nullable=False, index=True)
    description = Column(Text, nullable=False, default="")
    category = Column(String(100), nullable=False, index=True)
    brand = Column(String(100), nullable=False, default="")
    price = Column(Float, nullable=False)
    image_url = Column(String(500), nullable=True)
    rating = Column(Float, nullable=False, default=0.0)
    is_active = Column(Boolean, nullable=False, default=True)

    created_at = Column(
        DateTime,
        default=utc_now,
        nullable=False,
    )


class AuditLog(Base):
    __tablename__ = "audit_logs"

    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, nullable=True, index=True)
    action = Column(String(100), nullable=False, index=True)
    resource_type = Column(String(100), nullable=False)
    resource_id = Column(String(100), nullable=True)
    status = Column(String(20), nullable=False)
    details = Column(String(500), nullable=True)
    ip_address = Column(String(45), nullable=True)
    created_at = Column(
        DateTime,
        default=utc_now,
        nullable=False,
        index=True,
    )
