
from datetime import datetime

from pydantic import BaseModel, Field


class CartItemCreate(BaseModel):
    product_id: int = Field(gt=0)
    quantity: int = Field(gt=0, le=100)


class CartItemUpdate(BaseModel):
    quantity: int = Field(gt=0, le=100)


class CartItemResponse(BaseModel):
    id: int
    user_id: int
    product_id: int
    quantity: int
    created_at: datetime
    updated_at: datetime


class CartSummary(BaseModel):
    user_id: int
    items: list[CartItemResponse]
    total_items: int


class WishlistItemCreate(BaseModel):
    product_id: int = Field(gt=0)


class WishlistItemResponse(BaseModel):
    id: int
    user_id: int
    product_id: int
    created_at: datetime
