import os
import httpx
from fastapi import Depends, FastAPI, HTTPException, Request, Response, status
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session
from app.database import Base, engine, get_db
from app.models import AuditLog, CartItem, WishlistItem
from app.schemas import (
    CartItemCreate,
    CartItemResponse,
    CartItemUpdate,
    CartSummary,
    WishlistItemCreate,
    WishlistItemResponse,
)
from app.security import get_current_user
Base.metadata.create_all(bind=engine)
PRODUCT_SERVICE_URL = os.getenv(
    "PRODUCT_SERVICE_URL", "http://localhost:8002"
).rstrip("/")
INVENTORY_SERVICE_URL = os.getenv(
    "INVENTORY_SERVICE_URL", "http://localhost:8003"
).rstrip("/")
HTTP_TIMEOUT = 5.0
app = FastAPI(
    title="Cart and Wishlist Service",
    description="Persistent shopping cart and wishlist APIs",
    version="1.3.0",
)
def service_get(url: str, service_name: str) -> dict:
    try:
        response = httpx.get(url, timeout=HTTP_TIMEOUT)
        if response.status_code == 404:
            raise HTTPException(
                status_code=404,
                detail=f"{service_name} record not found",
            )
        response.raise_for_status()
        return response.json()
    except HTTPException:
        raise
    except httpx.HTTPError:
        raise HTTPException(
            status_code=503,
            detail=f"{service_name} is currently unavailable",
        )
    except ValueError:
        raise HTTPException(
            status_code=502,
            detail=f"{service_name} returned an invalid response",
        )
def get_product(product_id: int) -> dict:
    product = service_get(
        f"{PRODUCT_SERVICE_URL}/products/{product_id}",
        "Product Service",
    )
    if not product.get("is_active", False):
        raise HTTPException(
            status_code=404,
            detail="Product is not active",
        )
    try:
        price = float(product["price"])
        if price <= 0:
            raise ValueError
    except (KeyError, TypeError, ValueError):
        raise HTTPException(
            status_code=502,
            detail="Product Service returned an invalid product price",
        )
    return product
def validate_available_stock(product_id: int, requested_quantity: int):
    inventory = service_get(
        f"{INVENTORY_SERVICE_URL}/inventory/{product_id}",
        "Inventory Service",
    )
    try:
        available = int(inventory["available_quantity"])
    except (KeyError, TypeError, ValueError):
        raise HTTPException(
            status_code=502,
            detail="Inventory Service returned invalid stock information",
        )
    if available < requested_quantity:
        raise HTTPException(
            status_code=409,
            detail=(
                f"Insufficient available stock for product {product_id}. "
                f"Available: {available}, requested: {requested_quantity}"
            ),
        )
def record_audit(
    db: Session,
    request: Request,
    user_id: int,
    action: str,
    resource_type: str,
    resource_id: str | None,
    details: str,
):
    try:
        audit = AuditLog(
            user_id=user_id,
            action=action,
            resource_type=resource_type,
            resource_id=resource_id,
            status="success",
            details=details[:500],
            ip_address=request.client.host if request.client else None,
        )
        db.add(audit)
        db.commit()
    except Exception as exc:
        db.rollback()
        print(f"Audit logging failed: {type(exc).__name__}")
@app.get("/health")
def health():
    return {"status": "healthy", "service": "cart-service"}
@app.get("/cart", response_model=CartSummary)
def get_cart(
    user: dict = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    user_id = user["user_id"]
    items = (
        db.query(CartItem)
        .filter(CartItem.user_id == user_id)
        .order_by(CartItem.id)
        .all()
    )
    total_amount = 0.0
    for item in items:
        product = get_product(item.product_id)
        total_amount += float(product["price"]) * item.quantity
    return {
        "user_id": user_id,
        "items": items,
        "total_items": sum(item.quantity for item in items),
        "total_amount": round(total_amount, 2),
    }
@app.post(
    "/cart/items",
    response_model=CartItemResponse,
    status_code=status.HTTP_201_CREATED,
)
def add_cart_item(
    data: CartItemCreate,
    request: Request,
    user: dict = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    user_id = user["user_id"]
    get_product(data.product_id)
    existing = (
        db.query(CartItem)
        .filter(
            CartItem.user_id == user_id,
            CartItem.product_id == data.product_id,
        )
        .first()
    )
    requested_quantity = data.quantity
    if existing:
        requested_quantity += existing.quantity
    if requested_quantity > 100:
        raise HTTPException(
            status_code=422,
            detail="Total quantity cannot exceed 100",
        )
    validate_available_stock(data.product_id, requested_quantity)
    if existing:
        existing.quantity = requested_quantity
        db.commit()
        db.refresh(existing)
        record_audit(
            db, request, user_id,
            "cart_item_quantity_increased",
            "cart_item", str(existing.id),
            f"Increased product {existing.product_id} quantity to {existing.quantity}",
        )
        return existing
    item = CartItem(
        user_id=user_id,
        product_id=data.product_id,
        quantity=data.quantity,
    )
    db.add(item)
    try:
        db.commit()
        db.refresh(item)
    except IntegrityError:
        db.rollback()
        raise HTTPException(
            status_code=409,
            detail="Cart item already exists; retry the request",
        )
    record_audit(
        db, request, user_id,
        "cart_item_added",
        "cart_item", str(item.id),
        f"Added product {item.product_id} with quantity {item.quantity}",
    )
    return item
@app.patch("/cart/items/{item_id}", response_model=CartItemResponse)
def update_cart_item(
    item_id: int,
    data: CartItemUpdate,
    request: Request,
    user: dict = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    item = (
        db.query(CartItem)
        .filter(
            CartItem.id == item_id,
            CartItem.user_id == user["user_id"],
        )
        .first()
    )
    if item is None:
        raise HTTPException(status_code=404, detail="Cart item not found")
    get_product(item.product_id)
    validate_available_stock(item.product_id, data.quantity)
    item.quantity = data.quantity
    db.commit()
    db.refresh(item)
    record_audit(
        db, request, user["user_id"],
        "cart_item_updated",
        "cart_item", str(item.id),
        f"Updated product {item.product_id} quantity to {item.quantity}",
    )
    return item
@app.delete("/cart/items/{item_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_cart_item(
    item_id: int,
    request: Request,
    user: dict = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    item = (
        db.query(CartItem)
        .filter(
            CartItem.id == item_id,
            CartItem.user_id == user["user_id"],
        )
        .first()
    )
    if item is None:
        raise HTTPException(status_code=404, detail="Cart item not found")
    product_id = item.product_id
    db.delete(item)
    db.commit()
    record_audit(
        db, request, user["user_id"],
        "cart_item_deleted",
        "cart_item", str(item_id),
        f"Deleted product {product_id} from cart",
    )
    return Response(status_code=status.HTTP_204_NO_CONTENT)
@app.get("/wishlist", response_model=list[WishlistItemResponse])
def get_wishlist(
    user: dict = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    return (
        db.query(WishlistItem)
        .filter(WishlistItem.user_id == user["user_id"])
        .order_by(WishlistItem.id)
        .all()
    )
@app.post(
    "/wishlist/items",
    response_model=WishlistItemResponse,
    status_code=status.HTTP_201_CREATED,
)
def add_wishlist_item(
    data: WishlistItemCreate,
    request: Request,
    user: dict = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    user_id = user["user_id"]
    get_product(data.product_id)
    existing = (
        db.query(WishlistItem)
        .filter(
            WishlistItem.user_id == user_id,
            WishlistItem.product_id == data.product_id,
        )
        .first()
    )
    if existing:
        raise HTTPException(
            status_code=409,
            detail="Product is already in the wishlist",
        )
    item = WishlistItem(
        user_id=user_id,
        product_id=data.product_id,
    )
    db.add(item)
    try:
        db.commit()
        db.refresh(item)
    except IntegrityError:
        db.rollback()
        raise HTTPException(
            status_code=409,
            detail="Product is already in the wishlist",
        )
    record_audit(
        db, request, user_id,
        "wishlist_item_added",
        "wishlist_item", str(item.id),
        f"Added product {item.product_id} to wishlist",
    )
    return item
@app.delete(
    "/wishlist/items/{item_id}",
    status_code=status.HTTP_204_NO_CONTENT,
)
def delete_wishlist_item(
    item_id: int,
    request: Request,
    user: dict = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    item = (
        db.query(WishlistItem)
        .filter(
            WishlistItem.id == item_id,
            WishlistItem.user_id == user["user_id"],
        )
        .first()
    )
    if item is None:
        raise HTTPException(
            status_code=404,
            detail="Wishlist item not found",
        )
    product_id = item.product_id
    db.delete(item)
    db.commit()
    record_audit(
        db, request, user["user_id"],
        "wishlist_item_deleted",
        "wishlist_item", str(item_id),
        f"Removed product {product_id} from wishlist",
    )
    return Response(status_code=status.HTTP_204_NO_CONTENT)
