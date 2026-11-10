
import os

import httpx
from fastapi import Depends, FastAPI, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy.orm import Session

from app.database import Base, engine, get_db
from app.models import ReturnRequest
from app.schemas import ReturnCreate, ReturnResponse, ReturnStatusUpdate
from app.security import require_roles

Base.metadata.create_all(bind=engine)

app = FastAPI(
    title="StockFlow Return Service",
    version="1.0.0",
)

bearer_scheme = HTTPBearer()

PAYMENT_SERVICE_URL = os.getenv(
    "PAYMENT_SERVICE_URL",
    "http://stockflow-payment:8006",
)
REQUEST_TIMEOUT = 10.0


@app.get("/health")
def health():
    return {"status": "healthy", "service": "return-service"}


@app.post(
    "/returns",
    response_model=ReturnResponse,
    status_code=status.HTTP_201_CREATED,
)
def create_return(
    data: ReturnCreate,
    user: dict = Depends(require_roles("customer", "administrator")),
    db: Session = Depends(get_db),
):
    user_id = user.get("user_id", user.get("id", user.get("sub")))

    if user_id is None:
        raise HTTPException(status_code=401, detail="User ID missing from token")

    try:
        user_id = int(user_id)
    except (TypeError, ValueError):
        raise HTTPException(status_code=401, detail="Invalid user ID in token")

    record = ReturnRequest(
        order_id=data.order_id,
        user_id=user_id,
        product_id=data.product_id,
        reason=data.reason,
    )

    db.add(record)
    db.commit()
    db.refresh(record)
    return record


@app.get("/returns/my", response_model=list[ReturnResponse])
def get_my_returns(
    user: dict = Depends(require_roles("customer", "administrator")),
    db: Session = Depends(get_db),
):
    user_id = user.get("user_id", user.get("id", user.get("sub")))

    if user_id is None:
        raise HTTPException(status_code=401, detail="User ID missing from token")

    try:
        user_id = int(user_id)
    except (TypeError, ValueError):
        raise HTTPException(status_code=401, detail="Invalid user ID in token")

    return (
        db.query(ReturnRequest)
        .filter(ReturnRequest.user_id == user_id)
        .order_by(ReturnRequest.created_at.desc())
        .all()
    )


@app.get("/returns", response_model=list[ReturnResponse])
def get_all_returns(
    user: dict = Depends(require_roles("administrator")),
    db: Session = Depends(get_db),
):
    return (
        db.query(ReturnRequest)
        .order_by(ReturnRequest.created_at.desc())
        .all()
    )


@app.get("/returns/{return_id}", response_model=ReturnResponse)
def get_return(
    return_id: int,
    user: dict = Depends(require_roles("customer", "administrator")),
    db: Session = Depends(get_db),
):
    record = (
        db.query(ReturnRequest)
        .filter(ReturnRequest.id == return_id)
        .first()
    )

    if record is None:
        raise HTTPException(status_code=404, detail="Return request not found")

    if user.get("role") != "administrator":
        user_id = user.get("user_id", user.get("id", user.get("sub")))

        try:
            user_id = int(user_id)
        except (TypeError, ValueError):
            raise HTTPException(status_code=401, detail="Invalid user ID in token")

        if record.user_id != user_id:
            raise HTTPException(status_code=403, detail="Access denied")

    return record


@app.patch("/returns/{return_id}/status", response_model=ReturnResponse)
def update_return_status(
    return_id: int,
    data: ReturnStatusUpdate,
    credentials: HTTPAuthorizationCredentials = Depends(bearer_scheme),
    user: dict = Depends(require_roles("administrator")),
    db: Session = Depends(get_db),
):
    record = (
        db.query(ReturnRequest)
        .filter(ReturnRequest.id == return_id)
        .first()
    )

    if record is None:
        raise HTTPException(status_code=404, detail="Return request not found")

    if record.status == "completed" and data.status != "completed":
        raise HTTPException(status_code=409, detail="A completed return cannot be reopened")

    if data.status == "refunded":
        raise HTTPException(
            status_code=409,
            detail="Use refund_processing to initiate the simulated refund",
        )

    if data.status == "refund_processing":
        if record.status not in {"approved", "refund_processing"}:
            raise HTTPException(
                status_code=409,
                detail="Only approved returns can enter refund processing",
            )

        token = credentials.credentials
        headers = {"Authorization": f"Bearer {token}"}

        try:
            response = httpx.get(
                f"{PAYMENT_SERVICE_URL}/payments",
                headers=headers,
                timeout=REQUEST_TIMEOUT,
            )
            response.raise_for_status()
            payments = response.json()

            matching = [
                payment for payment in payments
                if payment.get("order_id") == record.order_id
                and payment.get("status") == "succeeded"
            ]

            if not matching:
                raise HTTPException(
                    status_code=409,
                    detail="No successful payment was found for this order",
                )

            payment = matching[0]

            if (
                data.refund_amount is not None
                and abs(data.refund_amount - payment["amount"]) > 0.01
            ):
                raise HTTPException(
                    status_code=409,
                    detail="Refund amount must match the successful payment",
                )

            refund_response = httpx.post(
                f"{PAYMENT_SERVICE_URL}/payments/{payment['id']}/refund",
                headers=headers,
                timeout=REQUEST_TIMEOUT,
            )
            refund_response.raise_for_status()
            refunded_payment = refund_response.json()

            if refunded_payment.get("status") != "refunded":
                raise HTTPException(
                    status_code=502,
                    detail="Payment Service did not confirm the refund",
                )

            record.status = "refunded"
            record.refund_amount = refunded_payment["amount"]

        except HTTPException:
            raise
        except httpx.HTTPStatusError as exc:
            raise HTTPException(
                status_code=502,
                detail=(
                    "Payment Service rejected the refund request: "
                    f"HTTP {exc.response.status_code}"
                ),
            ) from exc
        except httpx.HTTPError as exc:
            raise HTTPException(
                status_code=502,
                detail=f"Could not contact Payment Service: {exc}",
            ) from exc

    else:
        allowed_transitions = {
            "requested": {"approved", "rejected"},
            "approved": {"approved", "rejected"},
            "rejected": set(),
            "refund_processing": {"refund_processing"},
            "refunded": {"completed"},
            "completed": {"completed"},
        }

        if data.status not in allowed_transitions.get(record.status, set()):
            raise HTTPException(
                status_code=409,
                detail=f"Cannot transition return from {record.status} to {data.status}",
            )

        record.status = data.status

        if data.refund_amount is not None:
            record.refund_amount = data.refund_amount

    if data.admin_notes is not None:
        record.admin_notes = data.admin_notes

    db.commit()
    db.refresh(record)
    return record
