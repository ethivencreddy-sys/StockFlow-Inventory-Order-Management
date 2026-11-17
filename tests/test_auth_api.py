import httpx
BASE_URL = "http://127.0.0.1:8011"
def test_auth_health_endpoint():
    response = httpx.get(f"{BASE_URL}/health", timeout=5.0)
    assert response.status_code == 200
    assert response.json()["service"] == "auth-service"
def test_invalid_login_is_rejected():
    response = httpx.post(
        f"{BASE_URL}/auth/login",
        json={
            "email": "invalid-user@example.com",
            "password": "WrongPassword123"
        },
        timeout=5.0,
    )
    assert response.status_code == 401
def test_invalid_refresh_token_is_rejected():
    response = httpx.post(
        f"{BASE_URL}/auth/refresh",
        json={"refresh_token": "definitely-invalid-refresh-token"},
        timeout=5.0,
    )
    assert response.status_code == 401
def test_current_user_requires_authentication():
    response = httpx.get(
        f"{BASE_URL}/auth/me",
        timeout=5.0,
    )
    assert response.status_code in (401, 403)
