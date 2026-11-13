import uuid
import threading
import time

from datetime import timedelta

from fastapi import Depends, FastAPI, HTTPException, Request, status
from sqlalchemy import update, inspect, text
from sqlalchemy.orm import Session

from app.database import Base, engine, get_db, SessionLocal
from app.models import (
    Inventory,
    InventoryTransaction,
    StockReservation,
    AuditLog,
    utc_now,
)
from app.schemas import (
    InventoryCreate,
    InventoryResponse,
    StockAdjustment,
    ReservationCreate,
    ReservationRelease,
    ReservationResponse,
    TransactionResponse,
)
from app.security import get_current_user, require_roles


# ---------------------------------------------------------
# DATABASE INITIALIZATION AND SAFE MIGRATION
# ---------------------------------------------------------

Base.metadata.create_all(bind=engine)

# Add released_quantity to existing reservation tables.
# Existing reservation records are preserved and default to 0.

if "released_quantity" not in {
    column["name"]
    for column in inspect(engine).get_columns("stock_reservations")
}:
    with engine.begin() as connection:
        connection.execute(
            text(
                "ALTER TABLE stock_reservations "
                "ADD COLUMN released_quantity INTEGER NOT NULL DEFAULT 0"
            )
        )


app = FastAPI(
    title="Inventory Service",
    description="Inventory, stock reservation, transaction management, and auditing",
    version="1.3.0",
)


# ---------------------------------------------------------
# RESERVATION EXPIRY WORKER
# ---------------------------------------------------------

def release_expired_reservations():
    db = SessionLocal()

    try:
        now = utc_now()

        expired_reservations = (
            db.query(StockReservation)
            .filter(
                StockReservation.status == "reserved",
                StockReservation.expires_at <= now,
            )
            .with_for_update()
            .all()
        )

        released_count = 0

        for reservation in expired_reservations:
            item = db.get(Inventory, reservation.product_id)

            if item is None:
                continue

            remaining_quantity = (
                reservation.quantity - reservation.released_quantity
            )

            if remaining_quantity > 0:
                if item.reserved_quantity < remaining_quantity:
                    print(
                        f"Inventory expiry warning: reservation "
                        f"{reservation.id} exceeds current reserved stock",
                        flush=True,
                    )
                    continue

                item.reserved_quantity -= remaining_quantity

                db.add(
                    InventoryTransaction(
                        product_id=item.product_id,
                        change_quantity=0,
                        reason=(
                            f"Reservation expired: "
                            f"{reservation.order_reference}; "
                            f"released {remaining_quantity} units"
                        ),
                        responsible_user_id=None,
                    )
                )

            item.updated_at = now
            reservation.released_quantity = reservation.quantity
            reservation.status = "expired"

            db.add(
                AuditLog(
                    user_id=None,
                    action="stock_reservation_expired",
                    resource_type="inventory",
                    resource_id=str(reservation.id),
                    status="success",
                    details=(
                        f"Automatically expired reservation "
                        f"for order {reservation.order_reference}; "
                        f"released {remaining_quantity} units"
                    ),
                    ip_address=None,
                )
            )

            released_count += 1

        if released_count:
            db.commit()

            print(
                f"Inventory expiry worker: "
                f"released {released_count} expired reservation(s)",
                flush=True,
            )

    except Exception as exc:
        db.rollback()

        print(
            f"Inventory expiry worker error: "
            f"{type(exc).__name__}: {exc}",
            flush=True,
        )

    finally:
        db.close()


def reservation_expiry_worker():
    while True:
        release_expired_reservations()
        time.sleep(30)


@app.on_event("startup")
def start_reservation_expiry_worker():
    worker = threading.Thread(
        target=reservation_expiry_worker,
        daemon=True,
        name="reservation-expiry-worker",
    )

    worker.start()

    print("Inventory reservation expiry worker started", flush=True)


# ---------------------------------------------------------
# AUDIT LOGGING
# ---------------------------------------------------------

def record_audit(
    db: Session,
    request: Request,
    user: dict,
    action: str,
    resource_id: str,
    details: str,
):
    try:
        audit = AuditLog(
            user_id=user.get("user_id"),
            action=action,
            resource_type="inventory",
            resource_id=str(resource_id),
            status="success",
            details=details[:500],
            ip_address=request.client.host if request.client else None,
        )

        db.add(audit)
        db.commit()

    except Exception as exc:
        db.rollback()
        print(f"Inventory audit logging failed: {type(exc).__name__}")


# ---------------------------------------------------------
# HEALTH CHECK
# ---------------------------------------------------------

@app.get("/health")
def health():
    return {
        "status": "healthy",
        "service": "inventory-service",
    }


# ---------------------------------------------------------
# CREATE INVENTORY
# ---------------------------------------------------------

@app.post(
    "/inventory",
    response_model=InventoryResponse,
    status_code=status.HTTP_201_CREATED,
)
def create_inventory(
    data: InventoryCreate,
    request: Request,
    db: Session = Depends(get_db),
    user: dict = Depends(
        require_roles("administrator", "inventory_manager")
    ),
):
    existing = db.get(Inventory, data.product_id)

    if existing:
        raise HTTPException(
            status_code=409,
            detail="Inventory already exists for this product",
        )

    item = Inventory(
        product_id=data.product_id,
        quantity=data.quantity,
        reserved_quantity=0,
        low_stock_threshold=data.low_stock_threshold,
    )

    db.add(item)

    db.add(
        InventoryTransaction(
            product_id=data.product_id,
            change_quantity=data.quantity,
            reason="Initial stock",
            responsible_user_id=user["user_id"],
        )
    )

    db.commit()
    db.refresh(item)

    record_audit(
        db,
        request,
        user,
        "inventory_created",
        data.product_id,
        f"Created inventory with initial quantity {data.quantity}",
    )

    return item


# ---------------------------------------------------------
# LIST INVENTORY
# ---------------------------------------------------------

@app.get(
    "/inventory",
    response_model=list[InventoryResponse],
)
def list_inventory(
    db: Session = Depends(get_db),
):
    return (
        db.query(Inventory)
        .order_by(Inventory.product_id.asc())
        .all()
    )


# ---------------------------------------------------------
# GET INVENTORY BY PRODUCT
# ---------------------------------------------------------

@app.get(
    "/inventory/{product_id}",
    response_model=InventoryResponse,
)
def get_inventory(
    product_id: int,
    db: Session = Depends(get_db),
):
    item = db.get(Inventory, product_id)

    if item is None:
        raise HTTPException(
            status_code=404,
            detail="Inventory not found",
        )

    return item


# ---------------------------------------------------------
# ADJUST STOCK
# ---------------------------------------------------------

@app.patch(
    "/inventory/{product_id}/stock",
    response_model=InventoryResponse,
)
def adjust_stock(
    product_id: int,
    data: StockAdjustment,
    request: Request,
    db: Session = Depends(get_db),
    user: dict = Depends(
        require_roles("administrator", "inventory_manager")
    ),
):
    item = db.get(Inventory, product_id)

    if item is None:
        raise HTTPException(
            status_code=404,
            detail="Inventory not found",
        )

    if item.quantity + data.change_quantity < item.reserved_quantity:
        raise HTTPException(
            status_code=409,
            detail=(
                "Stock adjustment would reduce quantity "
                "below reserved stock"
            ),
        )

    item.quantity += data.change_quantity
    item.updated_at = utc_now()

    db.add(
        InventoryTransaction(
            product_id=product_id,
            change_quantity=data.change_quantity,
            reason=data.reason,
            responsible_user_id=user["user_id"],
        )
    )

    db.commit()
    db.refresh(item)

    record_audit(
        db,
        request,
        user,
        "stock_adjusted",
        product_id,
        f"Stock changed by {data.change_quantity}: {data.reason}",
    )

    return item


# ---------------------------------------------------------
# CREATE STOCK RESERVATION
# ---------------------------------------------------------

@app.post(
    "/inventory/reservations",
    response_model=ReservationResponse,
    status_code=status.HTTP_201_CREATED,
)
def reserve_stock(
    data: ReservationCreate,
    request: Request,
    db: Session = Depends(get_db),
    user: dict = Depends(get_current_user),
):
    now = utc_now()

    result = db.execute(
        update(Inventory)
        .where(Inventory.product_id == data.product_id)
        .where(
            Inventory.quantity - Inventory.reserved_quantity
            >= data.quantity
        )
        .values(
            reserved_quantity=Inventory.reserved_quantity + data.quantity,
            updated_at=now,
        )
    )

    if result.rowcount == 0:
        db.rollback()

        if not db.get(Inventory, data.product_id):
            raise HTTPException(
                status_code=404,
                detail="Inventory not found",
            )

        raise HTTPException(
            status_code=409,
            detail="Insufficient available stock",
        )

    reservation = StockReservation(
        reservation_code=uuid.uuid4().hex,
        order_reference=data.order_reference,
        product_id=data.product_id,
        quantity=data.quantity,
        released_quantity=0,
        status="reserved",
        expires_at=now + timedelta(minutes=data.expires_in_minutes),
    )

    db.add(reservation)

    db.add(
        InventoryTransaction(
            product_id=data.product_id,
            change_quantity=0,
            reason=f"Stock reserved for {data.order_reference}",
            responsible_user_id=user["user_id"],
        )
    )

    db.commit()
    db.refresh(reservation)

    record_audit(
        db,
        request,
        user,
        "stock_reserved",
        reservation.id,
        (
            f"Reserved {data.quantity} units of product "
            f"{data.product_id} for order {data.order_reference}"
        ),
    )

    return reservation


# ---------------------------------------------------------
# GET RESERVATIONS BY ORDER
# ---------------------------------------------------------

@app.get(
    "/inventory/reservations/by-order/{order_reference}",
    response_model=list[ReservationResponse],
)
def get_reservations_by_order(
    order_reference: str,
    db: Session = Depends(get_db),
    user: dict = Depends(
        require_roles("administrator", "inventory_manager")
    ),
):
    return (
        db.query(StockReservation)
        .filter(StockReservation.order_reference == order_reference)
        .order_by(StockReservation.id.asc())
        .all()
    )


# ---------------------------------------------------------
# RELEASE ALL OR PART OF A RESERVATION
# ---------------------------------------------------------

@app.post(
    "/inventory/reservations/{reservation_id}/release",
    response_model=ReservationResponse,
)
def release_reservation(
    reservation_id: int,
    request: Request,
    data: ReservationRelease | None = None,
    db: Session = Depends(get_db),
    user: dict = Depends(
        require_roles("administrator", "inventory_manager")
    ),
):
    reservation = (
        db.query(StockReservation)
        .filter(StockReservation.id == reservation_id)
        .with_for_update()
        .first()
    )

    if reservation is None:
        raise HTTPException(
            status_code=404,
            detail="Reservation not found",
        )

    if reservation.status != "reserved":
        raise HTTPException(
            status_code=409,
            detail=f"Reservation is already {reservation.status}",
        )

    item = db.get(Inventory, reservation.product_id)

    if item is None:
        raise HTTPException(
            status_code=500,
            detail="Inventory record missing",
        )

    remaining_quantity = (
        reservation.quantity - reservation.released_quantity
    )

    if remaining_quantity <= 0:
        raise HTTPException(
            status_code=409,
            detail="No remaining reserved quantity to release",
        )

    release_quantity = (
        data.quantity
        if data and data.quantity is not None
        else remaining_quantity
    )

    if release_quantity > remaining_quantity:
        raise HTTPException(
            status_code=409,
            detail=(
                f"Only {remaining_quantity} units remain reserved"
            ),
        )

    if item.reserved_quantity < release_quantity:
        raise HTTPException(
            status_code=409,
            detail="Reserved inventory quantity is inconsistent",
        )

    item.reserved_quantity -= release_quantity
    item.updated_at = utc_now()

    reservation.released_quantity += release_quantity

    if reservation.released_quantity >= reservation.quantity:
        reservation.status = "released"

    db.add(
        InventoryTransaction(
            product_id=item.product_id,
            change_quantity=0,
            reason=(
                f"Released {release_quantity} units from reservation "
                f"{reservation.order_reference}"
            ),
            responsible_user_id=user["user_id"],
        )
    )

    db.commit()
    db.refresh(reservation)

    record_audit(
        db,
        request,
        user,
        "stock_reservation_released",
        reservation.id,
        (
            f"Released {release_quantity} units from reservation "
            f"{reservation.order_reference}; "
            f"total released: {reservation.released_quantity}"
        ),
    )

    return reservation


# ---------------------------------------------------------
# INVENTORY TRANSACTION HISTORY
# ---------------------------------------------------------

@app.get(
    "/inventory/{product_id}/transactions",
    response_model=list[TransactionResponse],
)
def get_transactions(
    product_id: int,
    db: Session = Depends(get_db),
):
    if not db.get(Inventory, product_id):
        raise HTTPException(
            status_code=404,
            detail="Inventory not found",
        )

    return (
        db.query(InventoryTransaction)
        .filter(InventoryTransaction.product_id == product_id)
        .order_by(InventoryTransaction.created_at.desc())
        .all()
    )