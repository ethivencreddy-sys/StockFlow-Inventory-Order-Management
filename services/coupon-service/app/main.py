
from datetime import datetime
from decimal import Decimal, ROUND_HALF_UP
import logging

from fastapi import Depends, FastAPI, HTTPException, Request, status
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.database import Base, engine, get_db
from app.models import Coupon, CouponRedemption, AuditLog
from app.schemas import (
    CouponCreate,
    CouponRedeem,
    CouponResponse,
    CouponValidate,
    CouponValidationResponse,
)

Base.metadata.create_all(bind=engine)

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

app = FastAPI(
    title="StockFlow Coupon Service",
    description="Create, validate, and redeem discount coupons.",
    version="1.1.0",
)


def record_audit(
    db: Session,
    user_id: int | None,
    action: str,
    resource_id: int,
    details: str,
    request: Request,
):
    try:
        audit = AuditLog(
            user_id=user_id,
            action=action,
            resource_type="coupon",
            resource_id=str(resource_id),
            status="success",
            details=details,
            ip_address=request.client.host if request.client else None,
        )
        db.add(audit)
        db.commit()
    except Exception as exc:
        db.rollback()
        logger.error("Coupon audit logging failed: %s", type(exc).__name__)


def calculate_discount(
    coupon: Coupon,
    order_amount: Decimal,
) -> Decimal:
    if coupon.discount_type == "percentage":
        discount = order_amount * Decimal(coupon.discount_value) / Decimal("100")
    else:
        discount = Decimal(coupon.discount_value)

    if coupon.maximum_discount is not None:
        discount = min(discount, Decimal(coupon.maximum_discount))

    discount = min(discount, order_amount)

    return discount.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)


def get_valid_coupon(
    db: Session,
    code: str,
    user_id: int,
    order_amount: Decimal,
) -> Coupon:
    coupon = (
        db.query(Coupon)
        .filter(Coupon.code == code)
        .with_for_update()
        .first()
    )

    if coupon is None:
        raise HTTPException(status_code=404, detail="Coupon not found.")

    if not coupon.is_active:
        raise HTTPException(status_code=400, detail="Coupon is inactive.")

    now = datetime.utcnow()

    if coupon.expires_at is not None:
        expiry = coupon.expires_at

        if expiry.tzinfo is not None:
            from datetime import timezone
            now = datetime.now(timezone.utc)

        if expiry <= now:
            raise HTTPException(status_code=400, detail="Coupon has expired.")

    if order_amount < Decimal(coupon.minimum_purchase):
        raise HTTPException(
            status_code=400,
            detail=f"Minimum purchase is {coupon.minimum_purchase}.",
        )

    if (
        coupon.usage_limit is not None
        and coupon.usage_count >= coupon.usage_limit
    ):
        raise HTTPException(
            status_code=400,
            detail="Coupon usage limit has been reached.",
        )

    existing_redemption = (
        db.query(CouponRedemption)
        .filter(
            CouponRedemption.coupon_id == coupon.id,
            CouponRedemption.user_id == user_id,
        )
        .first()
    )

    if existing_redemption is not None:
        raise HTTPException(
            status_code=409,
            detail="You have already redeemed this coupon.",
        )

    return coupon


@app.get("/health")
def health():
    return {"status": "healthy", "service": "coupon-service"}


@app.post(
    "/coupons",
    response_model=CouponResponse,
    status_code=status.HTTP_201_CREATED,
)
def create_coupon(
    payload: CouponCreate,
    request: Request,
    db: Session = Depends(get_db),
):
    if payload.expires_at is not None and payload.expires_at <= datetime.utcnow():
        raise HTTPException(
            status_code=400,
            detail="Expiry date must be in the future.",
        )

    coupon = Coupon(**payload.model_dump())

    try:
        db.add(coupon)
        db.commit()
        db.refresh(coupon)
    except IntegrityError:
        db.rollback()
        raise HTTPException(
            status_code=409,
            detail="A coupon with this code already exists.",
        )

    record_audit(
        db,
        None,
        "coupon_created",
        coupon.id,
        f"Created coupon: {coupon.code}",
        request,
    )

    return coupon


@app.get("/coupons", response_model=list[CouponResponse])
def list_coupons(db: Session = Depends(get_db)):
    return db.query(Coupon).order_by(Coupon.id.desc()).all()


@app.get("/coupons/{code}", response_model=CouponResponse)
def get_coupon(code: str, db: Session = Depends(get_db)):
    coupon = (
        db.query(Coupon)
        .filter(Coupon.code == code.strip().upper())
        .first()
    )

    if coupon is None:
        raise HTTPException(status_code=404, detail="Coupon not found.")

    return coupon


@app.post("/coupons/validate", response_model=CouponValidationResponse)
def validate_coupon(
    payload: CouponValidate,
    db: Session = Depends(get_db),
):
    coupon = get_valid_coupon(
        db=db,
        code=payload.code,
        user_id=payload.user_id,
        order_amount=payload.order_amount,
    )

    discount = calculate_discount(coupon, payload.order_amount)
    final_amount = payload.order_amount - discount

    return CouponValidationResponse(
        valid=True,
        code=coupon.code,
        discount_amount=discount,
        final_amount=final_amount,
        message="Coupon is valid.",
    )


@app.post("/coupons/redeem", response_model=CouponValidationResponse)
def redeem_coupon(
    payload: CouponRedeem,
    request: Request,
    db: Session = Depends(get_db),
):
    try:
        coupon = get_valid_coupon(
            db=db,
            code=payload.code,
            user_id=payload.user_id,
            order_amount=payload.order_amount,
        )

        discount = calculate_discount(coupon, payload.order_amount)
        final_amount = payload.order_amount - discount

        redemption = CouponRedemption(
            coupon_id=coupon.id,
            user_id=payload.user_id,
            order_id=payload.order_id,
            discount_amount=discount,
        )

        coupon.usage_count += 1
        db.add(redemption)
        db.commit()
        db.refresh(redemption)

        record_audit(
            db,
            payload.user_id,
            "coupon_redeemed",
            coupon.id,
            (
                f"Redeemed coupon {coupon.code} for order "
                f"{payload.order_id}, discount {discount}"
            ),
            request,
        )

        return CouponValidationResponse(
            valid=True,
            code=coupon.code,
            discount_amount=discount,
            final_amount=final_amount,
            message="Coupon redeemed successfully.",
        )

    except HTTPException:
        db.rollback()
        raise
    except IntegrityError:
        db.rollback()
        raise HTTPException(
            status_code=409,
            detail="This coupon has already been redeemed by this user.",
        )
