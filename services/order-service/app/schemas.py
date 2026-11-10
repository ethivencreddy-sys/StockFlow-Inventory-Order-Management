
from datetime import datetime
from typing import List, Literal

from pydantic import BaseModel, ConfigDict, Field


class OrderItemCreate(BaseModel):
    product_id: int = Field(gt=0)
    quantity: int = Field(gt=0, le=100)
    unit_price: float = Field(gt=0)


class OrderCreate(BaseModel):
    shipping_address: str = Field(min_length=5, max_length=500)
    items: List[OrderItemCreate] = Field(min_length=1)


class OrderItemResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    product_id: int
    quantity: int
    unit_price: float
    subtotal: float


class OrderResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    user_id: int
    order_reference: str | None = None
    total_amount: float
    status: str
    payment_status: str
    shipping_address: str
    created_at: datetime
    updated_at: datetime
    items: List[OrderItemResponse]


class OrderStatusUpdate(BaseModel):
    status: Literal["pending", "confirmed", "processing", "shipped", "delivered", "cancelled"]


class OrderPaymentSync(BaseModel):
    payment_status: Literal["paid", "failed", "refunded"]
    amount: float = Field(gt=0)
