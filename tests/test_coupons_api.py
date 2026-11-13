
import httpx


BASE_URL = "http://127.0.0.1:8019"


def test_coupon_health_endpoint():
    response = httpx.get(
        f"{BASE_URL}/health",
        timeout=5.0,
    )

    assert response.status_code == 200
    assert response.json()["status"] == "healthy"


def test_nonexistent_coupon_is_rejected():
    response = httpx.post(
        f"{BASE_URL}/coupons/validate",
        json={
            "code": "TEST-CODE-DOES-NOT-EXIST",
            "user_id": 999999,
            "order_amount": 1000,
        },
        timeout=5.0,
    )

    assert response.status_code in (400, 404, 422)
