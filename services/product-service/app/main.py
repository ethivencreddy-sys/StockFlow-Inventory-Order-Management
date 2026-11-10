
from typing import Literal

from fastapi import Depends, FastAPI, HTTPException, Query, Response, status
from sqlalchemy import or_
from sqlalchemy.orm import Session

from app.database import Base, engine, get_db
from app.models import Product
from app.schemas import ProductCreate, ProductResponse, ProductUpdate
from app.security import require_roles

Base.metadata.create_all(bind=engine)

app = FastAPI(
    title="Product Catalog Service",
    description="Product management, search, and filtering API",
    version="1.1.0",
)


@app.get("/health")
def health():
    return {
        "status": "healthy",
        "service": "product-service",
    }


@app.post(
    "/products",
    response_model=ProductResponse,
    status_code=status.HTTP_201_CREATED,
)
def create_product(
    data: ProductCreate,
    db: Session = Depends(get_db),
    admin: dict = Depends(require_roles("administrator")),
):
    product_data = data.model_dump()

    if product_data.get("image_url") is not None:
        product_data["image_url"] = str(product_data["image_url"])

    product = Product(**product_data)
    db.add(product)
    db.commit()
    db.refresh(product)
    return product


@app.get("/products", response_model=list[ProductResponse])
def list_products(
    search: str | None = Query(default=None, max_length=100),
    category: str | None = Query(default=None, max_length=100),
    min_price: float | None = Query(default=None, ge=0),
    max_price: float | None = Query(default=None, ge=0),
    min_rating: float | None = Query(default=None, ge=0, le=5),
    in_stock: bool | None = None,
    sort_by: Literal["name", "price", "rating", "created_at"] = "created_at",
    sort_order: Literal["asc", "desc"] = "desc",
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=10, ge=1, le=100),
    db: Session = Depends(get_db),
):
    query = db.query(Product).filter(Product.is_active.is_(True))

    if search:
        term = f"%{search.strip()}%"
        query = query.filter(
            or_(
                Product.name.ilike(term),
                Product.description.ilike(term),
                Product.brand.ilike(term),
            )
        )

    if category:
        query = query.filter(Product.category.ilike(category.strip()))

    if min_price is not None:
        query = query.filter(Product.price >= min_price)

    if max_price is not None:
        query = query.filter(Product.price <= max_price)

    if min_rating is not None:
        query = query.filter(Product.rating >= min_rating)

    if (
        min_price is not None
        and max_price is not None
        and min_price > max_price
    ):
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="min_price cannot exceed max_price",
        )

    # Stock filtering requires integration with the Inventory Service.
    if in_stock is not None:
        raise HTTPException(
            status_code=status.HTTP_501_NOT_IMPLEMENTED,
            detail=(
                "Stock filtering will be available after "
                "Inventory Service integration"
            ),
        )

    sort_column = getattr(Product, sort_by)
    query = query.order_by(
        sort_column.asc() if sort_order == "asc" else sort_column.desc()
    )

    offset = (page - 1) * page_size
    return query.offset(offset).limit(page_size).all()


@app.get("/products/{product_id}", response_model=ProductResponse)
def get_product(
    product_id: int,
    db: Session = Depends(get_db),
):
    product = (
        db.query(Product)
        .filter(
            Product.id == product_id,
            Product.is_active.is_(True),
        )
        .first()
    )

    if product is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Product not found",
        )

    return product


@app.put("/products/{product_id}", response_model=ProductResponse)
def update_product(
    product_id: int,
    data: ProductUpdate,
    db: Session = Depends(get_db),
    admin: dict = Depends(require_roles("administrator")),
):
    product = db.query(Product).filter(Product.id == product_id).first()

    if product is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Product not found",
        )

    updates = data.model_dump(exclude_unset=True)

    if not updates:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Provide at least one field to update",
        )

    if "image_url" in updates and updates["image_url"] is not None:
        updates["image_url"] = str(updates["image_url"])

    for field, value in updates.items():
        if value is None:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail=f"{field} cannot be null",
            )
        setattr(product, field, value)

    db.commit()
    db.refresh(product)
    return product


@app.delete(
    "/products/{product_id}",
    status_code=status.HTTP_204_NO_CONTENT,
)
def delete_product(
    product_id: int,
    db: Session = Depends(get_db),
    admin: dict = Depends(require_roles("administrator")),
):
    product = db.query(Product).filter(Product.id == product_id).first()

    if product is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Product not found",
        )

    # Soft delete preserves product history for future order references.
    product.is_active = False
    db.commit()

    return Response(status_code=status.HTTP_204_NO_CONTENT)
