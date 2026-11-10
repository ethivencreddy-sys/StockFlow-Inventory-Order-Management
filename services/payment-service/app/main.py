
import uuid

import httpx
from fastapi import Depends, FastAPI, HTTPException
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy.orm import Session

from app.database import Base, engine, get_db
from app.models import Payment
from app.schemas import PaymentCreate, PaymentResponse, PaymentStatusUpdate
from app.security import get_current_user, require_roles


Base.metadata.create_all(bind=engine)

app = FastAPI(
    title="Payment Service",
    description="Payment record creation and status management",
    version="1.2.0",
)

bearer_scheme = HTTPBearer()

ORDER_SERVICE_URL = "http://stockflow-order:8005"
INVENTORY_SERVICE_URL = "http://stockflow-inventory:8003"
REQUEST_TIMEOUT = 10.0


@app.get("/health")
def health():
    return {"status": "healthy", "service": "payment-service"}


@app.post(
    "/payments",
    response_model=PaymentResponse,
    status_code=201,
)
def create_payment(
    payment_data: PaymentCreate,
    user: dict = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    payment = Payment(
        order_id=payment_data.order_id,
        user_id=user["user_id"],
        amount=payment_data.amount,
        currency=payment_data.currency.upper(),
        payment_method=payment_data.payment_method,
        status="pending",
    )

    db.add(payment)
    db.commit()
    db.refresh(payment)

    return payment



@app.get("/payments", response_model=list[PaymentResponse])
def list_payments(
    user: dict = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    query = db.query(Payment)

    # Administrators can list all payments.
    # Customers can list only their own payments.
    if user.get("role") != "administrator":
        query = query.filter(Payment.user_id == user["user_id"])

    return query.order_by(Payment.created_at.desc()).all()




@app.get("/payments/{payment_id}", response_model=PaymentResponse)
def get_payment(
    payment_id: int,
    user: dict = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    query = db.query(Payment).filter(Payment.id == payment_id)

    # Administrators can view any payment; customers can view only their own.
    if user.get("role") != "administrator":
        query = query.filter(Payment.user_id == user["user_id"])

    payment = query.first()

    if payment is None:
        raise HTTPException(
            status_code=404,
            detail="Payment not found",
        )

    return payment


def synchronize_order_payment(
    payment: Payment,
    payment_status: str,
    token: str,
) -> None:
    """Synchronize the payment status with the Order Service."""
    try:
        response = httpx.patch(
            f"{ORDER_SERVICE_URL}/orders/{payment.order_id}/payment-status",
            json={
                "payment_status": payment_status,
                "amount": payment.amount,
            },
            headers={"Authorization": f"Bearer {token}"},
            timeout=REQUEST_TIMEOUT,
        )
        response.raise_for_status()
    except httpx.HTTPError as exc:
        raise HTTPException(
            status_code=502,
            detail=(
                f"Payment status is saved, but order "
                f"{payment.order_id} synchronization failed: {exc}"
            ),
        ) from exc


def release_failed_order_reservations(
    payment: Payment,
    token: str,
) -> None:
    """Release active inventory reservations for a failed payment."""
    headers = {"Authorization": f"Bearer {token}"}

    try:
        # Fetch the order to obtain its actual stored reservation reference.
        order_response = httpx.get(
            f"{ORDER_SERVICE_URL}/orders/{payment.order_id}",
            headers=headers,
            timeout=REQUEST_TIMEOUT,
        )
        order_response.raise_for_status()
        order_data = order_response.json()

        order_reference = order_data.get("order_reference")
        if not order_reference:
            raise HTTPException(
                status_code=502,
                detail=(
                    "Could not release inventory: the Order Service response "
                    "does not contain order_reference. Add this field to "
                    "OrderResponse before enabling automatic release."
                ),
            )

        # Find only reservations belonging to this exact order.
        reservations_response = httpx.get(
            f"{INVENTORY_SERVICE_URL}/inventory/reservations/by-order/"
            f"{order_reference}",
            headers=headers,
            timeout=REQUEST_TIMEOUT,
        )
        reservations_response.raise_for_status()
        reservations = reservations_response.json()

        # Release active reservations only. Already-released reservations
        # are deliberately skipped to avoid duplicate release attempts.
        for reservation in reservations:
            if reservation.get("status") != "reserved":
                continue

            reservation_id = reservation.get("id")
            if reservation_id is None:
                raise HTTPException(
                    status_code=502,
                    detail="Inventory returned a reservation without an ID",
                )

            release_response = httpx.post(
                f"{INVENTORY_SERVICE_URL}/inventory/reservations/"
                f"{reservation_id}/release",
                headers=headers,
                timeout=REQUEST_TIMEOUT,
            )
            release_response.raise_for_status()

    except HTTPException:
        raise
    except httpx.HTTPError as exc:
        raise HTTPException(
            status_code=502,
            detail=(
                "Payment status is saved, but inventory reservation "
                f"release failed: {exc}"
            ),
        ) from exc


@app.patch(
    "/payments/{payment_id}/status",
    response_model=PaymentResponse,
)
def update_payment_status(
    payment_id: int,
    status_data: PaymentStatusUpdate,
    credentials: HTTPAuthorizationCredentials = Depends(bearer_scheme),
    user: dict = Depends(require_roles("administrator")),
    db: Session = Depends(get_db),
):
    payment = (
        db.query(Payment)
        .filter(Payment.id == payment_id)
        .first()
    )

    if payment is None:
        raise HTTPException(status_code=404, detail="Payment not found")

    requested_status = status_data.status

    # Do not allow changing a completed success or refund to another status.
    if payment.status in {"succeeded", "refunded"}:
        if payment.status != requested_status:
            raise HTTPException(
                status_code=409,
                detail=f"Cannot change status of a {payment.status} payment",
            )

        if payment.status == "refunded":
            return payment

    else:
        payment.status = requested_status

        if requested_status == "succeeded":
            if not payment.transaction_id:
                payment.transaction_id = (
                    f"DEV-{uuid.uuid4().hex[:16].upper()}"
                )
            payment.failure_reason = None

        elif requested_status == "failed":
            payment.failure_reason = (
                "Marked as failed during development testing"
            )

        db.commit()
        db.refresh(payment)

    token = credentials.credentials

    if payment.status == "succeeded":
        synchronize_order_payment(payment, "paid", token)

    elif payment.status == "failed":
        # Update the order first, then release inventory. If either step
        # fails, repeating this failed status request retries the operation.
        synchronize_order_payment(payment, "failed", token)
        release_failed_order_reservations(payment, token)

    return payment



@app.post(
    "/payments/{payment_id}/refund",
    response_model=PaymentResponse,
)
def refund_payment(
    payment_id: int,
    credentials: HTTPAuthorizationCredentials = Depends(bearer_scheme),
    user: dict = Depends(require_roles("administrator")),
    db: Session = Depends(get_db),
):
    payment = (
        db.query(Payment)
        .filter(Payment.id == payment_id)
        .first()
    )

    if payment is None:
        raise HTTPException(
            status_code=404,
            detail="Payment not found",
        )

    if payment.status == "refunded":
        return payment

    if payment.status != "succeeded":
        raise HTTPException(
            status_code=409,
            detail=(
                "Only successful payments can be refunded. "
                f"Current status: {payment.status}"
            ),
        )

    token = credentials.credentials

    # Synchronize the order before committing the refund locally.
    synchronize_order_payment(payment, "refunded", token)

    payment.status = "refunded"
    payment.failure_reason = None
    db.commit()
    db.refresh(payment)

    return payment
