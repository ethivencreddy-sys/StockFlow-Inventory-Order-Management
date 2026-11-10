
from datetime import datetime
from decimal import Decimal
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator


class CouponCreate(BaseModel):
    code: str = Field(min_length=3, max_length=50)
    discount_type: Literal["percentage", "fixed"]
    discount_value: Decimal = Field(gt=0, max_digits=10, decimal_places=2)
    minimum_purchase: Decimal = Field(
        default=Decimal("0"),
        ge=0,
        max_digits=10,
        decimal_places=2,
    )
    maximum_discount: Decimal | None = Field(
        default=None,
        gt=0,
        max_digits=10,
        decimal_places=2,
    )
    usage_limit: int | None = Field(default=None, gt=0)
    expires_at: datetime | None = None
    is_active: bool = True

    @field_validator("code")
    @classmethod
    def normalize_code(cls, value: str) -> str:
        return value.strip().upper()

    @field_validator("discount_value")
    @classmethod
    def validate_discount_value(cls, value: Decimal, info):
        discount_type = info.data.get("discount_type")

        if discount_type == "percentage" and value > 100:
            raise ValueError("Percentage discount cannot exceed 100.")

        return value


class CouponValidate(BaseModel):
    code: str = Field(min_length=3, max_length=50)
    user_id: int = Field(gt=0)
    order_amount: Decimal = Field(gt=0, max_digits=10, decimal_places=2)

    @field_validator("code")
    @classmethod
    def normalize_code(cls, value: str) -> str:
        return value.strip().upper()


class CouponRedeem(BaseModel):
    code: str = Field(min_length=3, max_length=50)
    user_id: int = Field(gt=0)
    order_id: int | None = Field(default=None, gt=0)
    order_amount: Decimal = Field(gt=0, max_digits=10, decimal_places=2)

    @field_validator("code")
    @classmethod
    def normalize_code(cls, value: str) -> str:
        return value.strip().upper()


class CouponResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    code: str
    discount_type: str
    discount_value: Decimal
    minimum_purchase: Decimal
    maximum_discount: Decimal | None
    usage_limit: int | None
    usage_count: int
    expires_at: datetime | None
    is_active: bool
    created_at: datetime


class CouponValidationResponse(BaseModel):
    valid: bool
    code: str
    discount_amount: Decimal
    final_amount: Decimal
    message: str
