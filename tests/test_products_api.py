
import httpx


BASE_URL = "http://127.0.0.1:8012"


def test_list_products_returns_active_products():
    response = httpx.get(
        f"{BASE_URL}/products",
        timeout=5.0,
    )

    assert response.status_code == 200

    products = response.json()
    assert isinstance(products, list)
    assert len(products) > 0

    for product in products:
        assert product["is_active"] is True
        assert product["name"]


def test_get_existing_product():
    response = httpx.get(
        f"{BASE_URL}/products/2",
        timeout=5.0,
    )

    assert response.status_code == 200

    product = response.json()
    assert product["id"] == 2
    assert product["name"] == "Wireless Headphones"
