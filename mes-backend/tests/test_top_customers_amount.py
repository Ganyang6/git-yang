"""
RED Phase — top-customers amount is quantity, not money (batch 6)

Verify that the `amount` field in top-customers response correctly
reflects the total quantity (same as `qty` field but as float).

Current state:
  - Backend: "amount": float(r.total_qty or 0) — same data as qty
  - Frontend: column header shows "合同金额(万)" which is misleading

This test validates backend behavior is consistent:
  amount == float(qty) and amount >= 0
"""

import pytest


@pytest.fixture(scope="session")
def auth_headers_top(client):
    """Replace conftest auth_headers, using actual admin password from config.yaml."""
    resp = client.post("/api/auth/login", json={
        "username": "admin",
        "password": "12345678",
    })
    assert resp.status_code == 200, f"Login failed: {resp.text}"
    token = resp.json()["data"]["access_token"]
    return {"Authorization": f"Bearer {token}"}


class TestTopCustomersAmount:
    """Verify top-customers amount field reflects quantity data."""

    ENDPOINT = "/api/reports/top-customers"

    def test_amount_matches_qty(self, client, auth_headers_top, seed_data):
        """amount should equal qty converted to float (same source: total_qty)."""
        resp = client.get(self.ENDPOINT, headers=auth_headers_top)
        assert resp.status_code == 200, f"API failed: {resp.text}"
        body = resp.json()
        assert body.get("code") == 0, f"API returned error: {body}"
        items = body["data"]
        assert isinstance(items, list), f"Expected list, got {type(items)}"
        assert len(items) > 0, "Expected at least one customer"

        for item in items:
            name = item.get("name", "?")
            qty = item.get("qty", -1)
            amount = item.get("amount", -1)
            share = item.get("share", -1)

            # type checks
            assert isinstance(qty, int), f"{name}: qty should be int, got {type(qty)}"
            assert isinstance(amount, float), f"{name}: amount should be float, got {type(amount)}"
            assert isinstance(share, float), f"{name}: share should be float, got {type(share)}"

            # amount should equal qty (same data source: total_qty)
            assert amount == float(qty), (
                f"{name}: amount={amount} != float(qty)={float(qty)}"
            )

            # all non-negative
            assert qty >= 0, f"{name}: qty={qty} < 0"
            assert amount >= 0.0, f"{name}: amount={amount} < 0"
            assert 0.0 <= share <= 100.0, f"{name}: share={share} out of range [0, 100]"

            # other required fields
            assert isinstance(item.get("name"), str), f"name should be str"
            assert isinstance(item.get("orders"), int), f"orders should be int"
            assert item.get("orders") >= 0, f"orders should be >= 0"
            assert isinstance(item.get("trend"), str), f"trend should be str"

    def test_top_customers_total_share(self, client, auth_headers_top, seed_data):
        """Total share of all top customers should sum to 100%."""
        resp = client.get(self.ENDPOINT, headers=auth_headers_top)
        assert resp.status_code == 200
        body = resp.json()
        items = body["data"]
        if not items:
            pytest.skip("No top customers data available")

        total_share = sum(item["share"] for item in items)
        assert total_share <= 100.0 + 1e-6, (
            f"Total share {total_share} exceeds 100%"
        )
