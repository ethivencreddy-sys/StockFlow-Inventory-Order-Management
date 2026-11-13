import csv
import io
import os
import logging
from pathlib import Path
from datetime import date
from decimal import Decimal, ROUND_HALF_UP
import httpx
from fastapi import FastAPI, HTTPException, Query, Request
from fastapi.responses import StreamingResponse
from app.database import init_db
from app.audit import get_user_id, record_audit
logger = logging.getLogger(__name__)
app = FastAPI(
    title="StockFlow Analytics Service",
    version="1.0.0",
)
@app.on_event("startup")
def startup():
    init_db()
TOKEN_FILE = Path(
    os.getenv(
        "ANALYTICS_TOKEN_FILE",
        str(Path(__file__).resolve().parents[2] / ".analytics_token"),
    )
)
API_GATEWAY_URL = os.getenv(
    "API_GATEWAY_URL",
    "http://stockflow-gateway:8000",
)
ORDER_SERVICE_URL = os.getenv(
    "ORDER_SERVICE_URL",
    "http://stockflow-order:8005",
)
PRODUCT_SERVICE_URL = os.getenv(
    "PRODUCT_SERVICE_URL",
    "http://stockflow-product:8002",
)
INVENTORY_SERVICE_URL = os.getenv(
    "INVENTORY_SERVICE_URL",
    "http://stockflow-inventory:8003",
)
def get_authorization(authorization: str | None = None) -> dict:
    """Use the incoming request token, or fall back to the configured token."""
    if authorization:
        return {"Authorization": authorization}
    token = None
    if TOKEN_FILE.exists():
        token = TOKEN_FILE.read_text(encoding="utf-8").strip()
    if not token:
        token = os.getenv("ANALYTICS_ACCESS_TOKEN")
    if token:
        return {"Authorization": f"Bearer {token}"}
    return {}
def fetch_list(
    url: str,
    path: str,
    authorization: str | None = None,
) -> list[dict]:
    """Fetch a list from another StockFlow service."""
    headers = get_authorization(authorization)
    try:
        response = httpx.get(
            f"{url}{path}",
            headers=headers,
            timeout=10.0,
        )
        response.raise_for_status()
        data = response.json()
        if isinstance(data, list):
            return data
        if isinstance(data, dict):
            for key in ("items", "data", "results", "value"):
                if isinstance(data.get(key), list):
                    return data[key]
        return []
    except httpx.HTTPError as exc:
        raise HTTPException(
            status_code=502,
            detail=f"Could not retrieve data from {url}{path}: {exc}",
        ) from exc
def fetch_orders(
    authorization: str | None = None,
) -> list[dict]:
    """Fetch orders, using the gateway as a fallback."""
    try:
        return fetch_list(
            ORDER_SERVICE_URL,
            "/orders",
            authorization,
        )
    except HTTPException:
        return fetch_list(
            API_GATEWAY_URL,
            "/orders",
            authorization,
        )
def to_decimal(value) -> Decimal:
    try:
        return Decimal(str(value or 0))
    except Exception:
        return Decimal("0")
def money(value: Decimal) -> float:
    return float(
        value.quantize(
            Decimal("0.01"),
            rounding=ROUND_HALF_UP,
        )
    )
def filter_orders(
    orders: list[dict],
    start_date: date | None = None,
    end_date: date | None = None,
) -> list[dict]:
    filtered = []
    for order in orders:
        order_date = (
            order.get("created_at")
            or order.get("order_date")
            or order.get("created")
        )
        if order_date:
            try:
                parsed_date = date.fromisoformat(str(order_date)[:10])
            except (ValueError, TypeError):
                parsed_date = None
            if parsed_date:
                if start_date and parsed_date < start_date:
                    continue
                if end_date and parsed_date > end_date:
                    continue
        filtered.append(order)
    return filtered
def audit_request(request: Request, action: str, details: str):
    authorization = request.headers.get("authorization")
    record_audit(
        action=action,
        details=details,
        ip_address=(
            request.client.host
            if request.client
            else None
        ),
        user_id=get_user_id(authorization),
    )
@app.get("/health")
def health():
    return {
        "service": "analytics-service",
        "status": "healthy",
    }
@app.get("/analytics/summary")
def sales_summary(
    request: Request,
    start_date: date | None = Query(None),
    end_date: date | None = Query(None),
):
    orders = fetch_orders(request.headers.get("authorization"))
    orders = filter_orders(orders, start_date, end_date)
    total_orders = len(orders)
    total_revenue = Decimal("0")
    completed_orders = 0
    pending_orders = 0
    cancelled_orders = 0
    for order in orders:
        amount = to_decimal(
            order.get("total_amount")
            or order.get("total")
            or order.get("amount")
        )
        total_revenue += amount
        status = str(order.get("status", "")).lower()
        if status in ("completed", "delivered", "paid"):
            completed_orders += 1
        elif status in ("pending", "processing", "created"):
            pending_orders += 1
        elif status in ("cancelled", "canceled"):
            cancelled_orders += 1
    result = {
        "total_orders": total_orders,
        "total_revenue": money(total_revenue),
        "total_sales": money(total_revenue),
        "completed_orders": completed_orders,
        "pending_orders": pending_orders,
        "cancelled_orders": cancelled_orders,
    }
    audit_request(
        request,
        "analytics_summary_generated",
        f"Generated sales summary for {total_orders} orders",
    )
    return result
@app.get("/analytics/daily-sales")
def daily_sales(
    request: Request,
    start_date: date | None = Query(None),
    end_date: date | None = Query(None),
):
    orders = fetch_orders(request.headers.get("authorization"))
    orders = filter_orders(orders, start_date, end_date)
    daily_totals = {}
    for order in orders:
        order_date = (
            order.get("created_at")
            or order.get("order_date")
            or order.get("created")
        )
        if not order_date:
            continue
        day = str(order_date)[:10]
        amount = to_decimal(
            order.get("total_amount")
            or order.get("total")
            or order.get("amount")
        )
        daily_totals[day] = (
            daily_totals.get(day, Decimal("0")) + amount
        )
    result = [
        {
            "date": day,
            "sales": money(amount),
        }
        for day, amount in sorted(daily_totals.items())
    ]
    audit_request(
        request,
        "analytics_daily_sales_generated",
        f"Generated daily sales report for {len(result)} days",
    )
    return result
@app.get("/analytics/top-products")
def top_products(
    request: Request,
    limit: int = Query(10, ge=1, le=100),
):
    orders = fetch_orders(request.headers.get("authorization"))
    product_sales = {}
    for order in orders:
        items = order.get("items", [])
        if not isinstance(items, list):
            continue
        for item in items:
            product_id = (
                item.get("product_id")
                or item.get("id")
            )
            product_name = (
                item.get("product_name")
                or item.get("name")
                or f"Product {product_id}"
            )
            quantity = int(item.get("quantity", 1) or 1)
            if product_id is None:
                continue
            if product_id not in product_sales:
                product_sales[product_id] = {
                    "product_id": product_id,
                    "product_name": product_name,
                    "quantity_sold": 0,
                    "revenue": Decimal("0"),
                }
            product_sales[product_id]["quantity_sold"] += quantity
            price = to_decimal(
                item.get("price")
                or item.get("unit_price")
            )
            product_sales[product_id]["revenue"] += price * quantity
    results = list(product_sales.values())
    results.sort(
        key=lambda item: item["quantity_sold"],
        reverse=True,
    )
    result = [
        {
            **item,
            "revenue": money(item["revenue"]),
        }
        for item in results[:limit]
    ]
    audit_request(
        request,
        "analytics_top_products_generated",
        f"Generated top products report with limit {limit}",
    )
    return result

@app.get("/analytics/low-stock")
def low_stock(request: Request):
    inventory = fetch_list(
        INVENTORY_SERVICE_URL,
        "/inventory",
        request.headers.get("authorization"),
    )

    low_stock_items = []

    for item in inventory:
        available_quantity = item.get("available_quantity")

        if available_quantity is None:
            available_quantity = (
                item.get("quantity")
                if item.get("quantity") is not None
                else item.get("stock", 0)
            )

        threshold = item.get("low_stock_threshold")

        if threshold is None:
            threshold = item.get("reorder_level", 10)

        quantity = int(available_quantity)
        threshold = int(threshold)

        if quantity <= threshold:
            low_stock_items.append(item)

    result = {
        "low_stock_count": len(low_stock_items),
        "items": low_stock_items,
    }

    audit_request(
        request,
        "analytics_low_stock_generated",
        f"Generated low-stock report with {len(low_stock_items)} items",
    )

    return result

@app.get("/analytics/export/csv")
def export_sales_csv(
    request: Request,
    start_date: date | None = Query(None),
    end_date: date | None = Query(None),
):
    authorization = request.headers.get("authorization")
    orders = fetch_orders(authorization)
    orders = filter_orders(orders, start_date, end_date)
    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow([
        "Order ID",
        "Order Date",
        "Status",
        "Total Amount",
    ])
    for order in orders:
        writer.writerow([
            order.get("id") or order.get("order_id", ""),
            order.get("created_at")
            or order.get("order_date", ""),
            order.get("status", ""),
            order.get("total_amount")
            or order.get("total")
            or order.get("amount", 0),
        ])
    output.seek(0)
    audit_request(
        request,
        "analytics_csv_exported",
        f"Exported sales CSV containing {len(orders)} orders",
    )
    return StreamingResponse(
        iter([output.getvalue()]),
        media_type="text/csv",
        headers={
            "Content-Disposition": "attachment; filename=stockflow_sales_report.csv"
        },
    )

# --------------------------------------------------
# ADDITIONAL ANALYTICS REPORTS
# --------------------------------------------------
from datetime import timedelta
def sales_report_by_period(
    orders: list[dict],
    period: str,
    start_date: date | None = None,
    end_date: date | None = None,
):
    orders = filter_orders(orders, start_date, end_date)
    totals = {}
    for order in orders:
        status = str(order.get("status", "")).lower()
        if status in ("cancelled", "canceled"):
            continue
        raw_date = (
            order.get("created_at")
            or order.get("order_date")
            or order.get("created")
        )
        if not raw_date:
            continue
        try:
            order_date = date.fromisoformat(str(raw_date)[:10])
        except (ValueError, TypeError):
            continue
        if period == "weekly":
            key = (order_date - timedelta(days=order_date.weekday())).isoformat()
        else:
            key = order_date.strftime("%Y-%m")
        amount = to_decimal(
            order.get("total_amount")
            or order.get("total")
            or order.get("amount")
        )
        totals[key] = totals.get(key, Decimal("0")) + amount
    return [
        {"period": key, "sales": money(value)}
        for key, value in sorted(totals.items())
    ]
@app.get("/analytics/weekly-sales")
def weekly_sales(
    request: Request,
    start_date: date | None = Query(None),
    end_date: date | None = Query(None),
):
    orders = fetch_orders(request.headers.get("authorization"))
    result = sales_report_by_period(
        orders, "weekly", start_date, end_date
    )
    audit_request(
        request,
        "analytics_weekly_sales_generated",
        f"Generated weekly sales report for {len(result)} weeks",
    )
    return result
@app.get("/analytics/monthly-sales")
def monthly_sales(
    request: Request,
    start_date: date | None = Query(None),
    end_date: date | None = Query(None),
):
    orders = fetch_orders(request.headers.get("authorization"))
    result = sales_report_by_period(
        orders, "monthly", start_date, end_date
    )
    audit_request(
        request,
        "analytics_monthly_sales_generated",
        f"Generated monthly sales report for {len(result)} months",
    )
    return result
@app.get("/analytics/top-categories")
def top_categories(
    request: Request,
    limit: int = Query(10, ge=1, le=100),
):
    authorization = request.headers.get("authorization")
    orders = fetch_orders(authorization)
    products = fetch_list(
        PRODUCT_SERVICE_URL,
        "/products",
        authorization,
    )
    product_categories = {
        product.get("id"): product.get("category") or "Uncategorized"
        for product in products
    }
    category_sales = {}
    for order in orders:
        if str(order.get("status", "")).lower() in (
            "cancelled", "canceled"
        ):
            continue
        items = order.get("items", [])
        if not isinstance(items, list):
            continue
        for item in items:
            product_id = item.get("product_id")
            if product_id is None:
                continue
            category = product_categories.get(
                product_id, "Uncategorized"
            )
            quantity = int(item.get("quantity", 1) or 1)
            revenue = to_decimal(
                item.get("subtotal")
                or (
                    item.get("unit_price")
                    or item.get("price")
                    or 0
                )
            )
            if category not in category_sales:
                category_sales[category] = {
                    "category": category,
                    "quantity_sold": 0,
                    "revenue": Decimal("0"),
                }
            category_sales[category]["quantity_sold"] += quantity
            category_sales[category]["revenue"] += revenue
    results = sorted(
        category_sales.values(),
        key=lambda item: item["quantity_sold"],
        reverse=True,
    )
    result = [
        {
            **item,
            "revenue": money(item["revenue"]),
        }
        for item in results[:limit]
    ]
    audit_request(
        request,
        "analytics_top_categories_generated",
        f"Generated top categories report with limit {limit}",
    )
    return result
@app.get("/analytics/cancellation-rate")
def cancellation_rate(request: Request):
    orders = fetch_orders(request.headers.get("authorization"))
    total_orders = len(orders)
    cancelled_orders = sum(
        1
        for order in orders
        if str(order.get("status", "")).lower()
        in ("cancelled", "canceled")
    )
    rate = (
        cancelled_orders / total_orders * 100
        if total_orders
        else 0
    )
    result = {
        "total_orders": total_orders,
        "cancelled_orders": cancelled_orders,
        "cancellation_rate": round(rate, 2),
    }
    audit_request(
        request,
        "analytics_cancellation_rate_generated",
        f"Calculated cancellation rate for {total_orders} orders",
    )
    return result
@app.get("/analytics/return-rate")
def return_rate(request: Request):
    authorization = request.headers.get("authorization")
    orders = fetch_orders(authorization)
    returns = fetch_list(
        os.getenv(
            "RETURN_SERVICE_URL",
            "http://stockflow-return:8011",
        ),
        "/returns",
        authorization,
    )
    total_orders = len(orders)
    returned_order_ids = {
        item.get("order_id")
        for item in returns
        if item.get("order_id") is not None
    }
    returned_orders = len(returned_order_ids)
    rate = (
        returned_orders / total_orders * 100
        if total_orders
        else 0
    )
    result = {
        "total_orders": total_orders,
        "orders_with_returns": returned_orders,
        "total_return_requests": len(returns),
        "return_rate": round(rate, 2),
    }
    audit_request(
        request,
        "analytics_return_rate_generated",
        f"Calculated return rate for {total_orders} orders",
    )
    return result
