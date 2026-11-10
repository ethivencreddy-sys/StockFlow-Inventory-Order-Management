
from fastapi import Depends, FastAPI, HTTPException, Response, status
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.database import Base, engine, get_db
from app.models import CartItem, WishlistItem
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

app = FastAPI(
    title="Cart and Wishlist Service",
    description="Persistent shopping cart and wishlist APIs",
    version="1.1.0",
)


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

    return {
        "user_id": user_id,
        "items": items,
        "total_items": sum(item.quantity for item in items),
    }


@app.post(
    "/cart/items",
    response_model=CartItemResponse,
    status_code=status.HTTP_201_CREATED,
)
def add_cart_item(
    data: CartItemCreate,
    user: dict = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    user_id = user["user_id"]

    existing = (
        db.query(CartItem)
        .filter(
            CartItem.user_id == user_id,
            CartItem.product_id == data.product_id,
        )
        .first()
    )

    if existing:
        new_quantity = existing.quantity + data.quantity

        if new_quantity > 100:
            raise HTTPException(
                status_code=422,
                detail="Total quantity cannot exceed 100",
            )

        existing.quantity = new_quantity
        db.commit()
        db.refresh(existing)
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

    return item


@app.patch("/cart/items/{item_id}", response_model=CartItemResponse)
def update_cart_item(
    item_id: int,
    data: CartItemUpdate,
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

    item.quantity = data.quantity
    db.commit()
    db.refresh(item)
    return item


@app.delete("/cart/items/{item_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_cart_item(
    item_id: int,
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

    db.delete(item)
    db.commit()
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
    user: dict = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    user_id = user["user_id"]

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

    return item


@app.delete(
    "/wishlist/items/{item_id}",
    status_code=status.HTTP_204_NO_CONTENT,
)
def delete_wishlist_item(
    item_id: int,
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

    db.delete(item)
    db.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)
