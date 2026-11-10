import httpx
BASE_URL = "http://127.0.0.1:8020"
def test_analytics_health_endpoint():
    response = httpx.get(
        f"{BASE_URL}/health",
        timeout=10.0,
    )
    assert response.status_code == 200
    assert response.json()["status"] == "healthy"
def test_analytics_summary_returns_order_metrics():
    token = None
    try:
        with open(".analytics_token", "r", encoding="utf-8") as file:
            token = file.read().strip()
    except FileNotFoundError:
        pass
    if not token:
        response = httpx.get(
            f"{BASE_URL}/analytics/summary",
            timeout=10.0,
        )
        assert response.status_code == 502
        return
    response = httpx.get(
        f"{BASE_URL}/analytics/summary",
        headers={"Authorization": f"Bearer {token}"},
        timeout=15.0,
    )
    assert response.status_code == 200
    summary = response.json()
    assert summary["total_orders"] >= 0
    assert summary["completed_orders"] >= 0
    assert summary["cancelled_orders"] >= 0
    assert summary["total_sales"] >= 0
