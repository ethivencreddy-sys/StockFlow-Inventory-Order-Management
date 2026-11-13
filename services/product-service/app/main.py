
import csv
import io
import os
from typing import Literal

import httpx

from fastapi import (
    Depends,
    FastAPI,
    File,
    HTTPException,
    Query,
    Request,
    Response,
    UploadFile,
    status,
)
from sqlalchemy import or_
from sqlalchemy.orm import Session

from app.database import Base, engine, get_db
from app.models import Product, AuditLog
from app.schemas import ProductCreate, ProductResponse, ProductUpdate
from app.security import require_roles


Base.metadata.create_all(bind=engine)

INVENTORY_SERVICE_URL = os.getenv(
    "INVENTORY_SERVICE_URL",
    "http://localhost:8013",
).rstrip("/")

app = FastAPI(
    title="Product Catalog Service",
    description=(
        "Product management, search, filtering, CSV bulk import, "
        "inventory integration, and audit logging API"
    ),
    version="1.4.0",
)


def record_audit(
    db: Session,
    request: Request,
    user: dict,
    action: str,
    resource_id: int,
    details: str,
):
    try:
        audit = AuditLog(
            user_id=user.get("user_id"),
            action=action,
            resource_type="product",
            resource_id=str(resource_id),
            status="success",
            details=details[:500],
            ip_address=request.client.host if request.client else None,
        )
        db.add(audit)
        db.commit()
    except Exception as exc:
        db.rollback()
        print(f"Product audit logging failed: {type(exc).__name__}")


def fetch_inventory():
    try:
        response = httpx.get(
            f"{INVENTORY_SERVICE_URL}/inventory",
            timeout=5.0,
        )
        response.raise_for_status()
        inventory_data = response.json()

        if not isinstance(inventory_data, list):
            raise ValueError("Unexpected inventory response format")

        return inventory_data

    except (httpx.HTTPError, ValueError) as exc:
        print(f"Inventory Service request failed: {type(exc).__name__}")
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Inventory Service is currently unavailable",
        )


@app.get("/health")
def health():
    return {"status": "healthy", "service": "product-service"}


@app.post(
    "/products",
    response_model=ProductResponse,
    status_code=status.HTTP_201_CREATED,
)
def create_product(
    data: ProductCreate,
    request: Request,
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

    record_audit(
        db, request, admin, "product_created",
        product.id, f"Created product: {product.name}",
    )
    return product


@app.post(
    "/products/bulk-import",
    status_code=status.HTTP_201_CREATED,
)
def bulk_import_products(
    request: Request,
    file: UploadFile = File(...),
    db: Session = Depends(get_db),
    admin: dict = Depends(require_roles("administrator")),
):
    if not file.filename or not file.filename.lower().endswith(".csv"):
        raise HTTPException(
            status_code=400,
            detail="Please upload a CSV file",
        )

    try:
        raw_content = file.file.read(2_000_001)

        if len(raw_content) > 2_000_000:
            raise HTTPException(
                status_code=413,
                detail="CSV file must not exceed 2 MB",
            )

        content = raw_content.decode("utf-8-sig")
        reader = csv.DictReader(io.StringIO(content))

        required_headers = {
            "name",
            "description",
            "category",
            "brand",
            "price",
        }

        headers = set(reader.fieldnames or [])

        if not required_headers.issubset(headers):
            missing = sorted(required_headers - headers)
            raise HTTPException(
                status_code=422,
                detail=f"Missing CSV columns: {', '.join(missing)}",
            )

        rows = list(reader)

        if not rows:
            raise HTTPException(
                status_code=422,
                detail="CSV file contains no product records",
            )

        if len(rows) > 1000:
            raise HTTPException(
                status_code=413,
                detail="Maximum 1000 products per import",
            )

        products_to_create = []
        seen_names = set()

        for row_number, row in enumerate(rows, start=2):
            try:
                product_data = {
                    "name": (row.get("name") or "").strip(),
                    "description": (row.get("description") or "").strip(),
                    "category": (row.get("category") or "").strip(),
                    "brand": (row.get("brand") or "").strip(),
                    "price": float(row.get("price") or ""),
                    "image_url": (
                        (row.get("image_url") or "").strip() or None
                    ),
                }

                validated = ProductCreate.model_validate(product_data)
                data = validated.model_dump()

                if data.get("image_url") is not None:
                    data["image_url"] = str(data["image_url"])

                duplicate_key = (
                    data["name"].strip().casefold(),
                    data["category"].strip().casefold(),
                    data["brand"].strip().casefold(),
                )

                if duplicate_key in seen_names:
                    raise ValueError("Duplicate product in CSV")

                existing = (
                    db.query(Product)
                    .filter(
                        Product.is_active.is_(True),
                        Product.name.ilike(data["name"]),
                        Product.category.ilike(data["category"]),
                        Product.brand.ilike(data["brand"]),
                    )
                    .first()
                )

                if existing:
                    raise ValueError(
                        f"Product already exists (ID {existing.id})"
                    )

                seen_names.add(duplicate_key)
                products_to_create.append(Product(**data))

            except Exception as exc:
                raise HTTPException(
                    status_code=422,
                    detail=f"Invalid CSV row {row_number}: {str(exc)}",
                )

        db.add_all(products_to_create)
        db.flush()

        imported_ids = [product.id for product in products_to_create]

        audit = AuditLog(
            user_id=admin.get("user_id"),
            action="products_bulk_imported",
            resource_type="product",
            resource_id=",".join(map(str, imported_ids))[:100],
            status="success",
            details=f"Imported {len(products_to_create)} products",
            ip_address=request.client.host if request.client else None,
        )

        db.add(audit)
        db.commit()

        return {
            "message": "Products imported successfully",
            "imported_count": len(products_to_create),
            "product_ids": imported_ids,
        }

    except HTTPException:
        db.rollback()
        raise
    except UnicodeDecodeError:
        db.rollback()
        raise HTTPException(
            status_code=422,
            detail="CSV must use UTF-8 encoding",
        )
    except Exception:
        db.rollback()
        raise HTTPException(
            status_code=500,
            detail="Product CSV import failed",
        )
    finally:
        file.file.close()


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

    if min_price is not None and max_price is not None:
        if min_price > max_price:
            raise HTTPException(
                status_code=422,
                detail="min_price cannot exceed max_price",
            )

    if in_stock is not None:
        inventory_records = fetch_inventory()
        available_stock = {}

        for item in inventory_records:
            if not isinstance(item, dict):
                continue

            try:
                product_id = int(item["product_id"])
                quantity = item.get("available_quantity")

                if quantity is None:
                    quantity = (
                        int(item.get("quantity", 0))
                        - int(item.get("reserved_quantity", 0))
                    )

                available_stock[product_id] = int(quantity)

            except (KeyError, TypeError, ValueError):
                continue

        if in_stock:
            matching_ids = [
                product_id
                for product_id, quantity in available_stock.items()
                if quantity > 0
            ]
        else:
            existing_ids = [
                product_id
                for (product_id,) in query.with_entities(Product.id).all()
        ]
            matching_ids = [
                product_id
                for product_id in existing_ids
                if available_stock.get(product_id, 0) <= 0
            ]

        query = query.filter(Product.id.in_(matching_ids))

    sort_column = getattr(Product, sort_by)

    query = query.order_by(
        sort_column.asc()
        if sort_order == "asc"
        else sort_column.desc()
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
        raise HTTPException(status_code=404, detail="Product not found")

    return product


@app.put("/products/{product_id}", response_model=ProductResponse)
def update_product(
    product_id: int,
    data: ProductUpdate,
    request: Request,
    db: Session = Depends(get_db),
    admin: dict = Depends(require_roles("administrator")),
):
    product = db.query(Product).filter(Product.id == product_id).first()

    if product is None:
        raise HTTPException(status_code=404, detail="Product not found")

    updates = data.model_dump(exclude_unset=True)

    if not updates:
        raise HTTPException(
            status_code=400,
            detail="Provide at least one field to update",
        )

    if "image_url" in updates and updates["image_url"] is not None:
        updates["image_url"] = str(updates["image_url"])

    for field, value in updates.items():
        if value is None:
            raise HTTPException(
                status_code=422,
                detail=f"{field} cannot be null",
            )
        setattr(product, field, value)

    db.commit()
    db.refresh(product)

    record_audit(
        db, request, admin, "product_updated",
        product.id, f"Updated product: {product.name}",
    )
    return product


@app.delete(
    "/products/{product_id}",
    status_code=status.HTTP_204_NO_CONTENT,
)
def delete_product(
    product_id: int,
    request: Request,
    db: Session = Depends(get_db),
    admin: dict = Depends(require_roles("administrator")),
):
    product = db.query(Product).filter(Product.id == product_id).first()

    if product is None:
        raise HTTPException(status_code=404, detail="Product not found")

    product.is_active = False
    db.commit()

    record_audit(
        db, request, admin, "product_deleted",
        product.id, f"Soft-deleted product: {product.name}",
    )

    return Response(status_code=status.HTTP_204_NO_CONTENT)
