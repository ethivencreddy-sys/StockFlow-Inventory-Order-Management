
from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


class PaymentCreate(BaseModel):
    order_id: int = Field(gt=0)
    amount: float = Field(gt=0)
    currency: str = Field(default="INR", min_length=3, max_length=3)
    payment_method: Literal["card", "upi", "net_banking"] = "card"


class PaymentStatusUpdate(BaseModel):
    status: Literal["pending", "succeeded", "failed", "refunded"]


class PaymentResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    order_id: int
    user_id: int
    amount: float
    currency: str
    payment_method: str
    status: str
    transaction_id: str | None
    failure_reason: str | None
    created_at: datetime
    updated_at: datetime
