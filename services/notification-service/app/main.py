
from datetime import datetime, timezone

from fastapi import Depends, FastAPI, HTTPException, Query, Response
from sqlalchemy.orm import Session

from app.database import Base, engine, get_db
from app.models import Notification
from app.schemas import (
    NotificationCreate,
    NotificationResponse,
    NotificationStatusUpdate,
)
from app.security import get_current_user, require_roles

Base.metadata.create_all(bind=engine)

app = FastAPI(
    title="Notification Service",
    description="Create, retrieve, and manage user notifications",
    version="1.0.0",
)


@app.get("/health")
def health():
    return {
        "status": "healthy",
        "service": "notification-service",
    }


@app.post(
    "/notifications",
    response_model=NotificationResponse,
    status_code=201,
)
def create_notification(
    notification_data: NotificationCreate,
    user: dict = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    notification = Notification(
        user_id=user["user_id"],
        title=notification_data.title,
        message=notification_data.message,
        notification_type=notification_data.notification_type,
        channel=notification_data.channel,
        status="unread",
    )

    db.add(notification)
    db.commit()
    db.refresh(notification)

    return notification


@app.get("/notifications", response_model=list[NotificationResponse])
def list_notifications(
    status: str | None = Query(
        default=None,
        pattern="^(read|unread)$",
    ),
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=10, ge=1, le=100),
    user: dict = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    query = db.query(Notification).filter(
        Notification.user_id == user["user_id"]
    )

    if status is not None:
        query = query.filter(Notification.status == status)

    return (
        query.order_by(Notification.created_at.desc())
        .offset((page - 1) * page_size)
        .limit(page_size)
        .all()
    )


@app.get(
    "/notifications/{notification_id}",
    response_model=NotificationResponse,
)
def get_notification(
    notification_id: int,
    user: dict = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    notification = (
        db.query(Notification)
        .filter(
            Notification.id == notification_id,
            Notification.user_id == user["user_id"],
        )
        .first()
    )

    if notification is None:
        raise HTTPException(
            status_code=404,
            detail="Notification not found",
        )

    return notification


@app.patch(
    "/notifications/{notification_id}/status",
    response_model=NotificationResponse,
)
def update_notification_status(
    notification_id: int,
    status_data: NotificationStatusUpdate,
    user: dict = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    notification = (
        db.query(Notification)
        .filter(
            Notification.id == notification_id,
            Notification.user_id == user["user_id"],
        )
        .first()
    )

    if notification is None:
        raise HTTPException(
            status_code=404,
            detail="Notification not found",
        )

    notification.status = status_data.status
    notification.read_at = (
        datetime.now(timezone.utc)
        if status_data.status == "read"
        else None
    )

    db.commit()
    db.refresh(notification)

    return notification


@app.delete("/notifications/{notification_id}", status_code=204)
def delete_notification(
    notification_id: int,
    user: dict = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    notification = (
        db.query(Notification)
        .filter(
            Notification.id == notification_id,
            Notification.user_id == user["user_id"],
        )
        .first()
    )

    if notification is None:
        raise HTTPException(
            status_code=404,
            detail="Notification not found",
        )

    db.delete(notification)
    db.commit()

    return Response(status_code=204)
