
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
        default=lambda: datetime.now(timezone.utc),
        nullable=False,
    )
