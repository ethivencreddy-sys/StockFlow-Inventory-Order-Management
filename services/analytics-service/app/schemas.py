
from datetime import date, datetime
from decimal import Decimal

from pydantic import BaseModel, ConfigDict


class SalesSummary(BaseModel):
    start_date: date | None = None
    end_date: date | None = None
    total_orders: int
    completed_orders: int
    cancelled_orders: int
    total_sales: Decimal
    average_order_value: Decimal


class DailySales(BaseModel):
    date: date
    total_orders: int
    total_sales: Decimal


class ProductPerformance(BaseModel):
    product_id: int
    product_name: str | None = None
    quantity_sold: int
    revenue: Decimal


class LowStockItem(BaseModel):
    product_id: int
    quantity: int
    reserved_quantity: int
    available_quantity: int
    low_stock_threshold: int


class AnalyticsSnapshotResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    report_type: str
    generated_at: datetime
    report_data: dict
