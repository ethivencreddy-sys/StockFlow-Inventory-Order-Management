
import uuid
from datetime import timedelta

from fastapi import Depends, FastAPI, HTTPException, status
from sqlalchemy import update
from sqlalchemy.orm import Session

from app.database import Base, engine, get_db
from app.models import (
    Inventory,
    InventoryTransaction,
    StockReservation,
    utc_now,
)
from app.schemas import (
    InventoryCreate,
    InventoryResponse,
    StockAdjustment,
    ReservationCreate,
    ReservationResponse,
    TransactionResponse,
)
from app.security import get_current_user, require_roles

Base.metadata.create_all(bind=engine)

app = FastAPI(
    title="Inventory Service",
    description="Inventory, stock reservation, and transaction management",
    version="1.1.0",
)


@app.get("/health")
def health():
    return {"status": "healthy", "service": "inventory-service"}


@app.post(
    "/inventory",
    response_model=InventoryResponse,
    status_code=status.HTTP_201_CREATED,
)
def create_inventory(
    data: InventoryCreate,
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
    return item


@app.get("/inventory", response_model=list[InventoryResponse])
def list_inventory(
    db: Session = Depends(get_db),
):
    return db.query(Inventory).order_by(Inventory.product_id.asc()).all()


@app.get("/inventory/{product_id}", response_model=InventoryResponse)
def get_inventory(
    product_id: int,
    db: Session = Depends(get_db),
):
    item = db.get(Inventory, product_id)

    if item is None:
        raise HTTPException(status_code=404, detail="Inventory not found")

    return item


@app.patch(
    "/inventory/{product_id}/stock",
    response_model=InventoryResponse,
)
def adjust_stock(
    product_id: int,
    data: StockAdjustment,
    db: Session = Depends(get_db),
    user: dict = Depends(
        require_roles("administrator", "inventory_manager")
    ),
):
    item = db.get(Inventory, product_id)

    if item is None:
        raise HTTPException(status_code=404, detail="Inventory not found")

    if item.quantity + data.change_quantity < item.reserved_quantity:
        raise HTTPException(
            status_code=409,
            detail="Stock adjustment would reduce quantity below reserved stock",
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
    return item


@app.post(
    "/inventory/reservations",
    response_model=ReservationResponse,
    status_code=status.HTTP_201_CREATED,
)
def reserve_stock(
    data: ReservationCreate,
    db: Session = Depends(get_db),
    user: dict = Depends(get_current_user),
):
    now = utc_now()

    result = db.execute(
        update(Inventory)
        .where(Inventory.product_id == data.product_id)
        .where(
            Inventory.quantity - Inventory.reserved_quantity >= data.quantity
        )
        .values(
            reserved_quantity=Inventory.reserved_quantity + data.quantity,
            updated_at=now,
        )
    )

    if result.rowcount == 0:
        db.rollback()

        if not db.get(Inventory, data.product_id):
            raise HTTPException(status_code=404, detail="Inventory not found")

        raise HTTPException(
            status_code=409,
            detail="Insufficient available stock",
        )

    reservation = StockReservation(
        reservation_code=uuid.uuid4().hex,
        order_reference=data.order_reference,
        product_id=data.product_id,
        quantity=data.quantity,
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
    return reservation


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


@app.post(
    "/inventory/reservations/{reservation_id}/release",
    response_model=ReservationResponse,
)
def release_reservation(
    reservation_id: int,
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
        raise HTTPException(status_code=404, detail="Reservation not found")

    if reservation.status != "reserved":
        raise HTTPException(
            status_code=409,
            detail=f"Reservation is already {reservation.status}",
        )

    item = db.get(Inventory, reservation.product_id)

    if item is None:
        raise HTTPException(status_code=500, detail="Inventory record missing")

    item.reserved_quantity -= reservation.quantity
    item.updated_at = utc_now()
    reservation.status = "released"

    db.add(
        InventoryTransaction(
            product_id=item.product_id,
            change_quantity=0,
            reason=f"Reservation released: {reservation.order_reference}",
            responsible_user_id=user["user_id"],
        )
    )

    db.commit()
    db.refresh(reservation)
    return reservation


@app.get(
    "/inventory/{product_id}/transactions",
    response_model=list[TransactionResponse],
)
def get_transactions(
    product_id: int,
    db: Session = Depends(get_db),
):
    if not db.get(Inventory, product_id):
        raise HTTPException(status_code=404, detail="Inventory not found")

    return (
        db.query(InventoryTransaction)
        .filter(InventoryTransaction.product_id == product_id)
        .order_by(InventoryTransaction.created_at.desc())
        .all()
    )
