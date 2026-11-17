import httpx
BASE_URL = "http://127.0.0.1:8019"
def test_coupon_health_endpoint():
    response = httpx.get(f"{BASE_URL}/health", timeout=5.0)
    assert response.status_code == 200
    assert response.json()["status"] == "healthy"
def test_coupon_validation_requires_authentication():
    response = httpx.post(
        f"{BASE_URL}/coupons/validate",
        json={"code": "TEST-CODE", "order_amount": 1000},
        timeout=5.0,
    )
    assert response.status_code == 401
