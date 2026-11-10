
from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


class NotificationCreate(BaseModel):
    user_id: int = Field(gt=0)
    title: str = Field(min_length=1, max_length=200)
    message: str = Field(min_length=1)
    notification_type: str = Field(default="general", max_length=50)
    channel: Literal["in_app", "email", "sms"] = "in_app"


class NotificationResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    user_id: int
    title: str
    message: str
    notification_type: str
    status: str
    channel: str
    created_at: datetime
    read_at: datetime | None


class NotificationStatusUpdate(BaseModel):
    status: Literal["read", "unread"]
