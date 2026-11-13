
import httpx


BASE_URL = "http://127.0.0.1:8015"


def test_list_orders_requires_authentication():
    response = httpx.get(
        f"{BASE_URL}/orders",
        timeout=5.0,
    )

    assert response.status_code in (401, 403)


def test_order_health_endpoint():
    response = httpx.get(
        f"{BASE_URL}/health",
        timeout=5.0,
    )

    assert response.status_code == 200
    assert response.json()["status"] == "healthy"
