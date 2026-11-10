
from datetime import datetime, timezone

from sqlalchemy import (
    Boolean,
    Column,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
)

from app.database import Base


def utc_now():
    return datetime.now(timezone.utc).replace(tzinfo=None)


class Inventory(Base):
    __tablename__ = "inventory"

    product_id = Column(Integer, primary_key=True, index=True)
    quantity = Column(Integer, nullable=False, default=0)
    reserved_quantity = Column(Integer, nullable=False, default=0)
    low_stock_threshold = Column(Integer, nullable=False, default=5)
    updated_at = Column(DateTime, default=utc_now, onupdate=utc_now)


class StockReservation(Base):
    __tablename__ = "stock_reservations"

    id = Column(Integer, primary_key=True, index=True)
    reservation_code = Column(String(64), unique=True, index=True, nullable=False)
    order_reference = Column(String(100), nullable=False, index=True)
    product_id = Column(Integer, ForeignKey("inventory.product_id"), nullable=False)
    quantity = Column(Integer, nullable=False)
    status = Column(String(20), nullable=False, default="reserved")
    expires_at = Column(DateTime, nullable=False)
    created_at = Column(DateTime, default=utc_now, nullable=False)


class InventoryTransaction(Base):
    __tablename__ = "inventory_transactions"

    id = Column(Integer, primary_key=True, index=True)
    product_id = Column(Integer, nullable=False, index=True)
    change_quantity = Column(Integer, nullable=False)
    reason = Column(String(250), nullable=False)
    responsible_user_id = Column(Integer, nullable=True)
    created_at = Column(DateTime, default=utc_now, nullable=False)


Index("ix_reservation_product_status", StockReservation.product_id, StockReservation.status)
