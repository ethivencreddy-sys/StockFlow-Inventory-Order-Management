import math
import uuid

import httpx
from fastapi import Depends, FastAPI, HTTPException, Request
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy.orm import Session

from app.database import Base, engine, get_db
from app.models import AuditLog, Payment
from app.schemas import PaymentCreate, PaymentResponse, PaymentStatusUpdate
from app.security import get_current_user, require_roles


Base.metadata.create_all(bind=engine)

app = FastAPI(
    title="Payment Service",
    description="Payment record creation and status management",
    version="1.3.0",
)

bearer_scheme = HTTPBearer()

ORDER_SERVICE_URL = "http://stockflow-order:8005"
INVENTORY_SERVICE_URL = "http://stockflow-inventory:8003"
REQUEST_TIMEOUT = 10.0


def record_audit(
    db: Session,
    user_id: int | None,
    action: str,
    resource_id: int | str | None,
    details: str,
    request: Request,
) -> None:
    try:
        forwarded_for = request.headers.get("x-forwarded-for")
        ip_address = (
            forwarded_for.split(",")[0].strip()
            if forwarded_for
            else (request.client.host if request.client else None)
        )

        db.add(
            AuditLog(
                user_id=user_id,
                action=action,
                resource_type="payment",
                resource_id=str(resource_id) if resource_id is not None else None,
                status="success",
                details=details[:500],
                ip_address=ip_address,
            )
        )
        db.commit()

    except Exception as exc:
        db.rollback()
        print(f"Audit logging failed: {type(exc).__name__}")


def get_order(order_id: int, token: str) -> dict:
    try:
        response = httpx.get(
            f"{ORDER_SERVICE_URL}/orders/{order_id}",
            headers={"Authorization": f"Bearer {token}"},
            timeout=REQUEST_TIMEOUT,
        )
        response.raise_for_status()
        return response.json()

    except httpx.HTTPStatusError as exc:
        if exc.response.status_code == 404:
            raise HTTPException(status_code=404, detail="Order not found") from exc
        if exc.response.status_code == 403:
            raise HTTPException(
                status_code=403,
                detail="You are not allowed to access this order",
            ) from exc
        raise HTTPException(
            status_code=502,
            detail="Order Service could not verify the order",
        ) from exc

    except httpx.HTTPError as exc:
        raise HTTPException(
            status_code=502,
            detail="Order Service is unavailable",
        ) from exc


def synchronize_order_payment(
    payment: Payment,
    payment_status: str,
    token: str,
) -> None:
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
                f"Could not synchronize order {payment.order_id}. "
                "The payment status was not changed."
            ),
        ) from exc


def release_failed_order_reservations(
    payment: Payment,
    token: str,
) -> None:
    headers = {"Authorization": f"Bearer {token}"}

    try:
        order_response = httpx.get(
            f"{ORDER_SERVICE_URL}/orders/{payment.order_id}",
            headers=headers,
            timeout=REQUEST_TIMEOUT,
        )
        order_response.raise_for_status()

        order_reference = order_response.json().get("order_reference")

        if not order_reference:
            raise HTTPException(
                status_code=502,
                detail="Order response is missing order_reference",
            )

        reservations_response = httpx.get(
            f"{INVENTORY_SERVICE_URL}/inventory/reservations/by-order/"
            f"{order_reference}",
            headers=headers,
            timeout=REQUEST_TIMEOUT,
        )
        reservations_response.raise_for_status()

        for reservation in reservations_response.json():
            if reservation.get("status") != "reserved":
                continue

            reservation_id = reservation.get("id")
            if reservation_id is None:
                continue

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
                "Payment status was updated, but inventory reservation "
                "release failed. The inventory expiry worker remains a fallback."
            ),
        ) from exc


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
    request: Request,
    credentials: HTTPAuthorizationCredentials = Depends(bearer_scheme),
    user: dict = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    token = credentials.credentials
    order = get_order(payment_data.order_id, token)

    is_admin = user.get("role") == "administrator"

    if not is_admin and order.get("user_id") != user["user_id"]:
        raise HTTPException(
            status_code=403,
            detail="You cannot make a payment for another user's order",
        )

    if order.get("status") == "cancelled":
        raise HTTPException(
            status_code=409,
            detail="Cannot pay for a cancelled order",
        )

    if order.get("payment_status") in {"paid", "refunded"}:
        raise HTTPException(
            status_code=409,
            detail="This order has already been paid or refunded",
        )

    if not math.isclose(
        float(payment_data.amount),
        float(order.get("total_amount", 0)),
        rel_tol=0,
        abs_tol=0.01,
    ):
        raise HTTPException(
            status_code=422,
            detail="Payment amount does not match the order total",
        )

    currency = payment_data.currency.upper()
    if currency != "INR":
        raise HTTPException(
            status_code=422,
            detail="Only INR payments are currently supported",
        )

    existing_active = (
        db.query(Payment)
        .filter(
            Payment.order_id == payment_data.order_id,
            Payment.status == "pending",
        )
        .first()
    )

    if existing_active:
        raise HTTPException(
            status_code=409,
            detail="A pending payment already exists for this order",
        )

    existing_success = (
        db.query(Payment)
        .filter(
            Payment.order_id == payment_data.order_id,
            Payment.status == "succeeded",
        )
        .first()
    )

    if existing_success:
        raise HTTPException(
            status_code=409,
            detail="A successful payment already exists for this order",
        )

    payment = Payment(
        order_id=payment_data.order_id,
        user_id=user["user_id"],
        amount=payment_data.amount,
        currency=currency,
        payment_method=payment_data.payment_method,
        status="pending",
    )

    try:
        db.add(payment)
        db.commit()
        db.refresh(payment)
    except Exception:
        db.rollback()
        raise HTTPException(
            status_code=500,
            detail="Could not create payment",
        )

    record_audit(
        db=db,
        user_id=user["user_id"],
        action="payment_created",
        resource_id=payment.id,
        details=(
            f"Created payment for order {payment.order_id}, "
            f"amount {payment.amount} {payment.currency}"
        ),
        request=request,
    )

    return payment


@app.get("/payments", response_model=list[PaymentResponse])
def list_payments(
    user: dict = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    query = db.query(Payment)

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

    if user.get("role") != "administrator":
        query = query.filter(Payment.user_id == user["user_id"])

    payment = query.first()

    if payment is None:
        raise HTTPException(status_code=404, detail="Payment not found")

    return payment


@app.patch(
    "/payments/{payment_id}/status",
    response_model=PaymentResponse,
)
def update_payment_status(
    payment_id: int,
    status_data: PaymentStatusUpdate,
    request: Request,
    credentials: HTTPAuthorizationCredentials = Depends(bearer_scheme),
    user: dict = Depends(require_roles("administrator")),
    db: Session = Depends(get_db),
):
    payment = db.query(Payment).filter(Payment.id == payment_id).first()

    if payment is None:
        raise HTTPException(status_code=404, detail="Payment not found")

    requested_status = status_data.status
    previous_status = payment.status

    if previous_status != "pending":
        if previous_status == requested_status:
            return payment

        raise HTTPException(
            status_code=409,
            detail=(
                f"Cannot change a payment from {previous_status} "
                "to another status. Create a new attempt if the payment failed."
            ),
        )

    token = credentials.credentials

    if requested_status == "succeeded":
        another_success = (
            db.query(Payment)
            .filter(
                Payment.order_id == payment.order_id,
                Payment.status == "succeeded",
                Payment.id != payment.id,
            )
            .first()
        )

        if another_success:
            raise HTTPException(
                status_code=409,
                detail="Another successful payment already exists for this order",
            )

        synchronize_order_payment(payment, "paid", token)
        payment.transaction_id = (
            f"DEV-{uuid.uuid4().hex[:16].upper()}"
        )
        payment.failure_reason = None

    elif requested_status in {"failed", "cancelled"}:
        synchronize_order_payment(payment, "failed", token)
        payment.failure_reason = (
            "Payment cancelled during development testing"
            if requested_status == "cancelled"
            else "Marked as failed during development testing"
        )

    payment.status = requested_status

    try:
        db.commit()
        db.refresh(payment)
    except Exception:
        db.rollback()
        raise HTTPException(
            status_code=500,
            detail="Could not save payment status",
        )

    record_audit(
        db=db,
        user_id=user["user_id"],
        action="payment_status_updated",
        resource_id=payment.id,
        details=(
            f"Payment status changed from {previous_status} "
            f"to {payment.status}"
        ),
        request=request,
    )

    if requested_status in {"failed", "cancelled"}:
        release_failed_order_reservations(payment, token)

    return payment


@app.post(
    "/payments/{payment_id}/refund",
    response_model=PaymentResponse,
)
def refund_payment(
    payment_id: int,
    request: Request,
    credentials: HTTPAuthorizationCredentials = Depends(bearer_scheme),
    user: dict = Depends(require_roles("administrator")),
    db: Session = Depends(get_db),
):
    payment = db.query(Payment).filter(Payment.id == payment_id).first()

    if payment is None:
        raise HTTPException(status_code=404, detail="Payment not found")

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

    synchronize_order_payment(
        payment,
        "refunded",
        credentials.credentials,
    )

    payment.status = "refunded"
    payment.failure_reason = None

    try:
        db.commit()
        db.refresh(payment)
    except Exception:
        db.rollback()
        raise HTTPException(
            status_code=500,
            detail="Could not save refund status",
        )

    record_audit(
        db=db,
        user_id=user["user_id"],
        action="payment_refunded",
        resource_id=payment.id,
        details=(
            f"Refunded payment for order {payment.order_id}, "
            f"amount {payment.amount} {payment.currency}"
        ),
        request=request,
    )

    return payment