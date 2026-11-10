
import os
from contextlib import asynccontextmanager

import httpx
import redis.asyncio as redis
from redis.exceptions import RedisError

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, Response


AUTH_SERVICE_URL = os.getenv("AUTH_SERVICE_URL", "http://stockflow-auth:8001")
PRODUCT_SERVICE_URL = os.getenv("PRODUCT_SERVICE_URL", "http://stockflow-product:8002")
INVENTORY_SERVICE_URL = os.getenv("INVENTORY_SERVICE_URL", "http://stockflow-inventory:8003")
CART_SERVICE_URL = os.getenv("CART_SERVICE_URL", "http://stockflow-cart:8004")
ORDER_SERVICE_URL = os.getenv("ORDER_SERVICE_URL", "http://stockflow-order:8005")
PAYMENT_SERVICE_URL = os.getenv("PAYMENT_SERVICE_URL", "http://stockflow-payment:8006")
NOTIFICATION_SERVICE_URL = os.getenv("NOTIFICATION_SERVICE_URL", "http://stockflow-notification:8007")
REVIEW_SERVICE_URL = os.getenv("REVIEW_SERVICE_URL", "http://stockflow-review:8008")
COUPON_SERVICE_URL = os.getenv("COUPON_SERVICE_URL", "http://stockflow-coupon:8009")
RETURN_SERVICE_URL = os.getenv("RETURN_SERVICE_URL", "http://stockflow-return:8011")
ANALYTICS_SERVICE_URL = os.getenv("ANALYTICS_SERVICE_URL", "http://stockflow-analytics:8010")

REDIS_URL = os.getenv("REDIS_URL", "redis://stockflow-redis:6379/0")
RATE_LIMIT = int(os.getenv("RATE_LIMIT", "120"))
RATE_LIMIT_WINDOW = int(os.getenv("RATE_LIMIT_WINDOW", "60"))

RATE_LIMIT_SCRIPT = """
local current = redis.call('INCR', KEYS[1])
if current == 1 then
    redis.call('EXPIRE', KEYS[1], ARGV[1])
end
return current
"""


@asynccontextmanager
async def lifespan(app: FastAPI):
    app.state.http_client = httpx.AsyncClient(timeout=30.0)
    app.state.redis = redis.from_url(
        REDIS_URL,
        decode_responses=True,
    )

    try:
        yield
    finally:
        await app.state.http_client.aclose()
        await app.state.redis.aclose()


app = FastAPI(
    title="Inventory and Order Management API Gateway",
    version="1.0.0",
    lifespan=lifespan,
)


app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://localhost:5173",
        "http://127.0.0.1:5173",
        "http://localhost:5174",
        "http://127.0.0.1:5174",
        "http://localhost:5175",
        "http://127.0.0.1:5175",
    ],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.middleware("http")
async def redis_rate_limiter(request: Request, call_next):
    if request.url.path == "/health" or request.method == "OPTIONS":
        return await call_next(request)

    client_ip = (
        request.client.host
        if request.client
        else "unknown"
    )

    redis_client = request.app.state.redis

    try:
        key = f"stockflow:rate-limit:{client_ip}"

        request_count = await redis_client.eval(
            RATE_LIMIT_SCRIPT,
            1,
            key,
            RATE_LIMIT_WINDOW,
        )

        if int(request_count) > RATE_LIMIT:
            return JSONResponse(
                status_code=429,
                content={
                    "detail": "Rate limit exceeded. Please try again later."
                },
                headers={
                    "Retry-After": str(RATE_LIMIT_WINDOW)
                },
            )

    except RedisError:
        # Keep the API available if Redis temporarily becomes unavailable.
        pass

    return await call_next(request)


@app.get("/health")
async def health():
    return {
        "service": "api-gateway",
        "status": "healthy",
    }


async def forward_request(request: Request, target_url: str):
    client: httpx.AsyncClient = request.app.state.http_client
    body = await request.body()

    headers = {
        key: value
        for key, value in request.headers.items()
        if key.lower() not in {
            "host",
            "content-length",
            "connection",
            "transfer-encoding",
        }
    }

    try:
        upstream_response = await client.request(
            method=request.method,
            url=target_url,
            params=request.query_params,
            content=body if body else None,
            headers=headers,
        )
    except httpx.RequestError:
        return JSONResponse(
            status_code=503,
            content={
                "detail": "The requested backend service is unavailable."
            },
        )

    excluded_headers = {
        "content-length",
        "transfer-encoding",
        "connection",
        "content-encoding",
    }

    response_headers = {
        key: value
        for key, value in upstream_response.headers.items()
        if key.lower() not in excluded_headers
    }

    return Response(
        content=upstream_response.content,
        status_code=upstream_response.status_code,
        headers=response_headers,
        media_type=upstream_response.headers.get("content-type"),
    )


# Authentication service
@app.api_route(
    "/auth",
    methods=["GET", "POST", "PUT", "PATCH", "DELETE"],
)
async def auth_root_proxy(request: Request):
    return await forward_request(request, f"{AUTH_SERVICE_URL}/auth")


@app.api_route(
    "/auth/{path:path}",
    methods=["GET", "POST", "PUT", "PATCH", "DELETE"],
)
async def auth_path_proxy(request: Request, path: str):
    return await forward_request(request, f"{AUTH_SERVICE_URL}/auth/{path}")


# Product service
@app.api_route(
    "/products",
    methods=["GET", "POST", "PUT", "PATCH", "DELETE"],
)
async def products_root_proxy(request: Request):
    return await forward_request(request, f"{PRODUCT_SERVICE_URL}/products")


@app.api_route(
    "/products/{path:path}",
    methods=["GET", "POST", "PUT", "PATCH", "DELETE"],
)
async def products_path_proxy(request: Request, path: str):
    return await forward_request(request, f"{PRODUCT_SERVICE_URL}/products/{path}")


# Inventory service
@app.api_route(
    "/inventory",
    methods=["GET", "POST", "PUT", "PATCH", "DELETE"],
)
async def inventory_root_proxy(request: Request):
    return await forward_request(request, f"{INVENTORY_SERVICE_URL}/inventory")


@app.api_route(
    "/inventory/{path:path}",
    methods=["GET", "POST", "PUT", "PATCH", "DELETE"],
)
async def inventory_path_proxy(request: Request, path: str):
    return await forward_request(request, f"{INVENTORY_SERVICE_URL}/inventory/{path}")


# Cart service
@app.api_route(
    "/cart",
    methods=["GET", "POST", "PUT", "PATCH", "DELETE"],
)
async def cart_root_proxy(request: Request):
    return await forward_request(request, f"{CART_SERVICE_URL}/cart")


@app.api_route(
    "/cart/{path:path}",
    methods=["GET", "POST", "PUT", "PATCH", "DELETE"],
)
async def cart_path_proxy(request: Request, path: str):
    return await forward_request(request, f"{CART_SERVICE_URL}/cart/{path}")


# Wishlist service
@app.api_route(
    "/wishlist",
    methods=["GET", "POST", "PUT", "PATCH", "DELETE"],
)
async def wishlist_root_proxy(request: Request):
    return await forward_request(request, f"{CART_SERVICE_URL}/wishlist")


@app.api_route(
    "/wishlist/{path:path}",
    methods=["GET", "POST", "PUT", "PATCH", "DELETE"],
)
async def wishlist_path_proxy(request: Request, path: str):
    return await forward_request(request, f"{CART_SERVICE_URL}/wishlist/{path}")


# Order service
@app.api_route(
    "/orders",
    methods=["GET", "POST", "PUT", "PATCH", "DELETE"],
)
async def orders_root_proxy(request: Request):
    return await forward_request(request, f"{ORDER_SERVICE_URL}/orders")


@app.api_route(
    "/orders/{path:path}",
    methods=["GET", "POST", "PUT", "PATCH", "DELETE"],
)
async def orders_path_proxy(request: Request, path: str):
    return await forward_request(request, f"{ORDER_SERVICE_URL}/orders/{path}")


# Payment service
@app.api_route(
    "/payments",
    methods=["GET", "POST", "PUT", "PATCH", "DELETE"],
)
async def payments_root_proxy(request: Request):
    return await forward_request(request, f"{PAYMENT_SERVICE_URL}/payments")


@app.api_route(
    "/payments/{path:path}",
    methods=["GET", "POST", "PUT", "PATCH", "DELETE"],
)
async def payments_path_proxy(request: Request, path: str):
    return await forward_request(request, f"{PAYMENT_SERVICE_URL}/payments/{path}")


# Notification service
@app.api_route(
    "/notifications",
    methods=["GET", "POST", "PUT", "PATCH", "DELETE"],
)
async def notifications_root_proxy(request: Request):
    return await forward_request(request, f"{NOTIFICATION_SERVICE_URL}/notifications")


@app.api_route(
    "/notifications/{path:path}",
    methods=["GET", "POST", "PUT", "PATCH", "DELETE"],
)
async def notifications_path_proxy(request: Request, path: str):
    return await forward_request(request, f"{NOTIFICATION_SERVICE_URL}/notifications/{path}")


# Review service
@app.api_route(
    "/reviews",
    methods=["GET", "POST", "PUT", "PATCH", "DELETE"],
)
async def reviews_root_proxy(request: Request):
    return await forward_request(request, f"{REVIEW_SERVICE_URL}/reviews")


@app.api_route(
    "/reviews/{path:path}",
    methods=["GET", "POST", "PUT", "PATCH", "DELETE"],
)
async def reviews_path_proxy(request: Request, path: str):
    return await forward_request(request, f"{REVIEW_SERVICE_URL}/reviews/{path}")

# Coupon service
@app.api_route(
    "/coupons",
    methods=["GET", "POST", "PUT", "PATCH", "DELETE"],
)
async def coupons_root_proxy(request: Request):
    return await forward_request(request, f"{COUPON_SERVICE_URL}/coupons")


@app.api_route(
    "/coupons/{path:path}",
    methods=["GET", "POST", "PUT", "PATCH", "DELETE"],
)
async def coupons_path_proxy(request: Request, path: str):
    return await forward_request(request, f"{COUPON_SERVICE_URL}/coupons/{path}")


# Return service
@app.api_route(
    "/returns",
    methods=["GET", "POST", "PUT", "PATCH", "DELETE"],
)
async def returns_root_proxy(request: Request):
    return await forward_request(request, f"{RETURN_SERVICE_URL}/returns")


@app.api_route(
    "/returns/{path:path}",
    methods=["GET", "POST", "PUT", "PATCH", "DELETE"],
)
async def returns_path_proxy(request: Request, path: str):
    return await forward_request(request, f"{RETURN_SERVICE_URL}/returns/{path}")


# Analytics service
@app.api_route(
    "/analytics",
    methods=["GET", "POST", "PUT", "PATCH", "DELETE"],
)
async def analytics_root_proxy(request: Request):
    return await forward_request(request, f"{ANALYTICS_SERVICE_URL}/analytics")


@app.api_route(
    "/analytics/{path:path}",
    methods=["GET", "POST", "PUT", "PATCH", "DELETE"],
)
async def analytics_path_proxy(request: Request, path: str):
    return await forward_request(request, f"{ANALYTICS_SERVICE_URL}/analytics/{path}")
