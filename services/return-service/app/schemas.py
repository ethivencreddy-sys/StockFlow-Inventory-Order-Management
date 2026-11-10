from datetime import datetime
from typing import Literal, Optional

from pydantic import BaseModel, Field


class ReturnCreate(BaseModel):
    order_id: int = Field(gt=0)
    product_id: Optional[int] = Field(default=None, gt=0)
    reason: str = Field(min_length=5, max_length=500)


class ReturnStatusUpdate(BaseModel):
    status: Literal[
        "approved",
        "rejected",
        "refund_processing",
        "refunded",
        "completed",
    ]
    refund_amount: Optional[float] = Field(default=None, ge=0)
    admin_notes: Optional[str] = Field(default=None, max_length=2000)


class ReturnResponse(BaseModel):
    id: int
    order_id: int
    user_id: int
    product_id: Optional[int]
    reason: str
    status: str
    refund_amount: float
    admin_notes: Optional[str]
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}