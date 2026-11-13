from datetime import datetime

from pydantic import (
    BaseModel,
    Field,
    ConfigDict,
    computed_field,
    field_validator,
)


class InventoryCreate(BaseModel):
    product_id: int = Field(gt=0)
    quantity: int = Field(ge=0)
    low_stock_threshold: int = Field(default=5, ge=0)


class StockAdjustment(BaseModel):
    change_quantity: int = Field(
        description="Positive to add stock; negative to deduct stock. Cannot be zero."
    )
    reason: str = Field(min_length=3, max_length=250)
    responsible_user_id: int | None = Field(default=None, gt=0)

    @field_validator("change_quantity")
    @classmethod
    def validate_change_quantity(cls, value):
        if value == 0:
            raise ValueError("Stock adjustment cannot be zero")
        return value


class ReservationCreate(BaseModel):
    order_reference: str = Field(min_length=1, max_length=100)
    product_id: int = Field(gt=0)
    quantity: int = Field(gt=0)
    expires_in_minutes: int = Field(default=15, ge=1, le=1440)


class ReservationRelease(BaseModel):
    quantity: int | None = Field(default=None, gt=0)


class InventoryResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    product_id: int
    quantity: int
    reserved_quantity: int
    low_stock_threshold: int
    updated_at: datetime | None

    @computed_field
    @property
    def available_quantity(self) -> int:
        return self.quantity - self.reserved_quantity


class ReservationResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    reservation_code: str
    order_reference: str
    product_id: int
    quantity: int
    released_quantity: int
    status: str
    expires_at: datetime
    created_at: datetime


class TransactionResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    product_id: int
    change_quantity: int
    reason: str
    responsible_user_id: int | None
    created_at: datetime