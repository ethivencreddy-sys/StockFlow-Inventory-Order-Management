import httpx
import pytest
SERVICE_URLS = [
    "http://127.0.0.1:8022/health",  # API Gateway
    "http://127.0.0.1:8011/health",  # Auth
    "http://127.0.0.1:8012/health",  # Product
    "http://127.0.0.1:8013/health",  # Inventory
    "http://127.0.0.1:8014/health",  # Cart
    "http://127.0.0.1:8015/health",  # Order
    "http://127.0.0.1:8016/health",  # Payment
    "http://127.0.0.1:8017/health",  # Notification
    "http://127.0.0.1:8018/health",  # Review
    "http://127.0.0.1:8019/health",  # Coupon
    "http://127.0.0.1:8020/health",  # Analytics
    "http://127.0.0.1:8021/health",  # Return
]
@pytest.mark.parametrize("url", SERVICE_URLS)
def test_service_health(url):
    """Verify that each StockFlow service responds successfully."""
    response = httpx.get(url, timeout=10.0)
    assert response.status_code == 200
    assert response.json()["status"] == "healthy"
