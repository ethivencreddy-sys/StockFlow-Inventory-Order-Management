
from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field, HttpUrl


class ProductCreate(BaseModel):
    name: str = Field(min_length=2, max_length=150)
    description: str = Field(default="", max_length=3000)
    category: str = Field(min_length=2, max_length=100)
    brand: str = Field(default="", max_length=100)
    price: float = Field(gt=0, allow_inf_nan=False)
    image_url: HttpUrl | None = None


class ProductUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=2, max_length=150)
    description: str | None = Field(default=None, max_length=3000)
    category: str | None = Field(default=None, min_length=2, max_length=100)
    brand: str | None = Field(default=None, max_length=100)
    price: float | None = Field(default=None, gt=0, allow_inf_nan=False)
    image_url: HttpUrl | None = None
    is_active: bool | None = None


class ProductResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    name: str
    description: str
    category: str
    brand: str
    price: float
    image_url: str | None
    rating: float
    is_active: bool
    created_at: datetime
