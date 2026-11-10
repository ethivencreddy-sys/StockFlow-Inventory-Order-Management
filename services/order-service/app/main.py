
import uuid
import os
import json
import httpx

from fastapi import Depends, FastAPI, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy.orm import Session, selectinload

from app.database import get_db
from app.models import Order, OrderItem, OutboxEvent
from app.schemas import (
    OrderCreate,
    OrderResponse,
    OrderStatusUpdate,
    OrderPaymentSync,
)
from app.security import require_roles


app = FastAPI(title="StockFlow Order Service")

bearer_scheme = HTTPBearer()

INVENTORY_SERVICE_URL = os.getenv(
    "INVENTORY_SERVICE_URL",
    "http://stockflow-inventory:8003",
)

INVENTORY_TIMEOUT = 10.0


@app.get("/health")
def health():
    return {"status": "healthy", "service": "order-service"}


@app.post(
    "/orders",
    response_model=OrderResponse,
    status_code=status.HTTP_201_CREATED,
)
def create_order(
    order_data: OrderCreate,
    credentials: HTTPAuthorizationCredentials = Depends(bearer_scheme),
    db: Session = Depends(get_db),
    user: dict = Depends(require_roles("administrator", "customer")),
):
    if not order_data.items:
        raise HTTPException(
            status_code=400,
            detail="An order must contain at least one item",
        )

    order_reference = f"ORDER-{uuid.uuid4().hex[:16]}"
    reservations = []
    total_amount = 0.0

    try:
        # Reserve stock for every order item.
        with httpx.Client(timeout=INVENTORY_TIMEOUT) as client:
            for item_data in order_data.items:
                if item_data.quantity <= 0 or item_data.unit_price < 0:
                    raise HTTPException(
                        status_code=400,
                        detail="Invalid item quantity or price",
                    )

                reservation_response = client.post(
                    f"{INVENTORY_SERVICE_URL}/inventory/reservations",
                    json={
                        "order_reference": order_reference,
                        "product_id": item_data.product_id,
                        "quantity": item_data.quantity,
                        "expires_in_minutes": 15,
                    },
                    headers={
                        "Authorization": (
                            f"Bearer {credentials.credentials}"
                        )
                    },
                )

                if reservation_response.is_error:
                    raise HTTPException(
                        status_code=reservation_response.status_code,
                        detail=(
                            "Inventory reservation failed: "
                            f"{reservation_response.text}"
                        ),
                    )

                reservations.append(reservation_response.json())

        # Calculate total and prepare order items.
        order_items = []

        for item_data in order_data.items:
            item_subtotal = item_data.quantity * item_data.unit_price
            total_amount += item_subtotal

            order_items.append(
                OrderItem(
                    product_id=item_data.product_id,
                    quantity=item_data.quantity,
                    unit_price=item_data.unit_price,
                    subtotal=item_subtotal,
                )
            )

        order = Order(
            user_id=user["user_id"],
            order_reference=order_reference,
            total_amount=round(total_amount, 2),
            status="pending",
            payment_status="unpaid",
            shipping_address=order_data.shipping_address,
            items=order_items,
        )

        # Save order and outbox event in one transaction.
        db.add(order)
        db.flush()

        event_payload = {
            "order_id": order.id,
            "order_reference": order.order_reference,
            "user_id": order.user_id,
            "total_amount": order.total_amount,
            "status": order.status,
            "payment_status": order.payment_status,
            "items": [
                {
                    "product_id": item.product_id,
                    "quantity": item.quantity,
                    "unit_price": item.unit_price,
                    "subtotal": item.subtotal,
                }
                for item in order.items
            ],
        }

        outbox_event = OutboxEvent(
            event_type="order.created",
            payload=json.dumps(event_payload),
        )

        db.add(outbox_event)
        db.commit()
        db.refresh(order)

        return (
            db.query(Order)
            .options(selectinload(Order.items))
            .filter(Order.id == order.id)
            .first()
        )

    except HTTPException:
        db.rollback()
        _release_reservations(reservations, credentials.credentials)
        raise

    except Exception as exc:
        db.rollback()
        _release_reservations(reservations, credentials.credentials)

        raise HTTPException(
            status_code=500,
            detail=f"Could not create order: {str(exc)}",
        )


def _release_reservations(reservations: list, token: str) -> None:
    """Best-effort cleanup when order creation fails."""

    with httpx.Client(timeout=INVENTORY_TIMEOUT) as client:
        for reservation in reservations:
            reservation_id = reservation.get("id")

            if reservation_id is None:
                continue

            try:
                client.post(
                    f"{INVENTORY_SERVICE_URL}/inventory/reservations/"
                    f"{reservation_id}/release",
                    headers={"Authorization": f"Bearer {token}"},
                )
            except httpx.HTTPError:
                pass


@app.get("/orders", response_model=list[OrderResponse])
def get_orders(
    db: Session = Depends(get_db),
    user: dict = Depends(require_roles("administrator", "customer")),
):
    query = db.query(Order).options(selectinload(Order.items))

    if user.get("role") != "administrator":
        user_id = user.get("user_id", user.get("id", user.get("sub")))

        if user_id is None:
            raise HTTPException(
                status_code=401,
                detail="User ID missing from token",
            )

        try:
            user_id = int(user_id)
        except (TypeError, ValueError):
            raise HTTPException(
                status_code=401,
                detail="Invalid user ID in token",
            )

        query = query.filter(Order.user_id == user_id)

    return query.order_by(Order.id.desc()).all()


@app.get("/orders/{order_id}", response_model=OrderResponse)
def get_order(
    order_id: int,
    db: Session = Depends(get_db),
    user: dict = Depends(require_roles("administrator", "customer")),
):
    order = (
        db.query(Order)
        .options(selectinload(Order.items))
        .filter(Order.id == order_id)
        .first()
    )

    if order is None:
        raise HTTPException(status_code=404, detail="Order not found")

    if (
        user.get("role") != "administrator"
        and order.user_id != user.get("user_id")
    ):
        raise HTTPException(status_code=403, detail="Access denied")

    return order


@app.patch("/orders/{order_id}/status", response_model=OrderResponse)
def update_order_status(
    order_id: int,
    status_data: OrderStatusUpdate,
    credentials: HTTPAuthorizationCredentials = Depends(bearer_scheme),
    db: Session = Depends(get_db),
    admin: dict = Depends(require_roles("administrator")),
):
    order = (
        db.query(Order)
        .options(selectinload(Order.items))
        .filter(Order.id == order_id)
        .first()
    )

    if order is None:
        raise HTTPException(status_code=404, detail="Order not found")

    if order.status in {"delivered", "cancelled"}:
        raise HTTPException(
            status_code=409,
            detail=f"Cannot update an order that is {order.status}",
        )

    new_status = status_data.status

    if new_status == "cancelled":
        if order.payment_status == "paid":
            raise HTTPException(
                status_code=409,
                detail=(
                    "This order is already paid. Process a refund before "
                    "cancelling it."
                ),
            )

        if not order.order_reference:
            raise HTTPException(
                status_code=409,
                detail="Order has no stored inventory reservation reference",
            )

        try:
            lookup_response = httpx.get(
                f"{INVENTORY_SERVICE_URL}/inventory/reservations/by-order/"
                f"{order.order_reference}",
                headers={
                    "Authorization": f"Bearer {credentials.credentials}"
                },
                timeout=INVENTORY_TIMEOUT,
            )
            lookup_response.raise_for_status()
            reservations = lookup_response.json()

        except httpx.HTTPError as exc:
            raise HTTPException(
                status_code=502,
                detail=f"Could not retrieve inventory reservations: {exc}",
            )

        for reservation in reservations:
            if reservation.get("status") != "reserved":
                continue

            try:
                release_response = httpx.post(
                    f"{INVENTORY_SERVICE_URL}/inventory/reservations/"
                    f"{reservation['id']}/release",
                    headers={
                        "Authorization": f"Bearer {credentials.credentials}"
                    },
                    timeout=INVENTORY_TIMEOUT,
                )
                release_response.raise_for_status()

            except httpx.HTTPError as exc:
                raise HTTPException(
                    status_code=502,
                    detail=(
                        "Could not release inventory reservation "
                        f"{reservation.get('id')}: {exc}. "
                        "The order has not been marked cancelled."
                    ),
                )

    order.status = new_status
    db.commit()

    return (
        db.query(Order)
        .options(selectinload(Order.items))
        .filter(Order.id == order_id)
        .first()
    )


@app.patch(
    "/orders/{order_id}/payment-status",
    response_model=OrderResponse,
)
def update_payment_status(
    order_id: int,
    payment_data: OrderPaymentSync,
    db: Session = Depends(get_db),
    admin: dict = Depends(require_roles("administrator")),
):
    order = (
        db.query(Order)
        .options(selectinload(Order.items))
        .filter(Order.id == order_id)
        .first()
    )

    if order is None:
        raise HTTPException(status_code=404, detail="Order not found")

    if abs(order.total_amount - payment_data.amount) > 0.01:
        raise HTTPException(
            status_code=400,
            detail="Payment amount does not match the order total",
        )

    if (
        order.status == "cancelled"
        and payment_data.payment_status == "paid"
    ):
        raise HTTPException(
            status_code=409,
            detail="Cannot mark a cancelled order as paid",
        )

    if payment_data.payment_status == "refunded":
        if order.payment_status == "refunded":
            return order

        if order.payment_status != "paid":
            raise HTTPException(
                status_code=409,
                detail=(
                    "Only paid orders can be marked as refunded. "
                    f"Current payment status: {order.payment_status}"
                ),
            )

    order.payment_status = payment_data.payment_status

    if (
        payment_data.payment_status == "paid"
        and order.status == "pending"
    ):
        order.status = "confirmed"

    db.commit()
    db.refresh(order)

    return (
        db.query(Order)
        .options(selectinload(Order.items))
        .filter(Order.id == order_id)
        .first()
    )
