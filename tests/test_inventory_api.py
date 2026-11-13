
import httpx


BASE_URL = "http://127.0.0.1:8013"


def test_list_inventory_returns_success():
    response = httpx.get(
        f"{BASE_URL}/inventory",
        timeout=5.0,
    )

    assert response.status_code == 200
    assert isinstance(response.json(), list)


def test_inventory_records_have_valid_quantities():
    response = httpx.get(
        f"{BASE_URL}/inventory",
        timeout=5.0,
    )

    assert response.status_code == 200

    records = response.json()

    for record in records:
        assert record["quantity"] >= 0
        assert record["reserved_quantity"] >= 0
        assert record["reserved_quantity"] <= record["quantity"]
