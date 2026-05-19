"""
Tests for Phase 3 business API endpoints.

Covers: auth, orders, customers, inventory, equipment, reports,
dashboard, and line_balance routes.

Uses session-scoped fixtures from conftest.py (MES_DB_URL + TestClient).
"""

from __future__ import annotations

import pytest


# -- Auth tests ---

class TestAuth:
    def test_login_default_admin(self, client):
        resp = client.post("/api/auth/login", json={
            "username": "admin", "password": "changeme",
        })
        assert resp.status_code == 200
        data = resp.json()["data"]
        assert "access_token" in data
        assert data["token_type"] == "bearer"
        assert data["user"]["username"] == "admin"

    def test_login_wrong_password(self, client):
        resp = client.post("/api/auth/login", json={
            "username": "admin", "password": "wrong",
        })
        assert resp.status_code == 401

    def test_login_unknown_user(self, client):
        resp = client.post("/api/auth/login", json={
            "username": "nobody", "password": "whatever",
        })
        assert resp.status_code == 401

    def test_login_remember_me(self, client):
        resp = client.post("/api/auth/login", json={
            "username": "admin", "password": "changeme", "remember": True,
        })
        data = resp.json()["data"]
        assert data["expires_in"] >= 604800

    def test_me_without_token(self, client):
        resp = client.get("/api/auth/me")
        assert resp.status_code == 401

    def test_me_with_valid_token(self, client):
        login_resp = client.post("/api/auth/login", json={
            "username": "admin", "password": "changeme",
        })
        token = login_resp.json()["data"]["access_token"]
        resp = client.get("/api/auth/me", headers={
            "Authorization": f"Bearer {token}",
        })
        assert resp.status_code == 200
        assert resp.json()["data"]["username"] == "admin"


# -- Order tests ---

class TestOrders:
    def _unique_code(self):
        import time
        return f"PO-T{int(time.time() * 1000)}"

    def test_create_order(self, client):
        resp = client.post("/api/orders", json={
            "code": self._unique_code(), "product": "Test Product",
            "qty": 50, "priority": "high",
        })
        assert resp.status_code == 200
        assert resp.json()["data"]["qty"] == 50

    def test_list_orders(self, client):
        resp = client.get("/api/orders")
        assert resp.status_code == 200
        assert "total" in resp.json()["data"]

    def test_create_order_with_status_priority(self, client):
        """P0-2: create order with string status/priority maps to int FK."""
        resp = client.post("/api/orders", json={
            "code": self._unique_code(), "product": "Test Product",
            "qty": 100, "priority": "urgent", "status": "completed",
        })
        assert resp.status_code == 200
        data = resp.json()["data"]
        # P0-4: response returns readable codes not raw int IDs
        assert data["priority"] == "urgent"
        assert data["status"] == "completed"

    def test_list_orders_filter_by_status(self, client):
        """P0-3: filter orders by status string vs Integer FK."""
        code = self._unique_code()
        client.post("/api/orders", json={
            "code": code, "product": "STATUS-TEST",
            "qty": 10, "status": "completed",
        })
        resp = client.get("/api/orders?status=completed")
        assert resp.status_code == 200
        codes = [i["code"] for i in resp.json()["data"]["items"]]
        assert code in codes

    def test_list_orders_filter_by_priority(self, client):
        """P0-3: filter orders by priority string vs Integer FK."""
        code = self._unique_code()
        client.post("/api/orders", json={
            "code": code, "product": "PRIORITY-TEST",
            "qty": 10, "priority": "urgent",
        })
        resp = client.get("/api/orders?priority=urgent")
        assert resp.status_code == 200
        codes = [i["code"] for i in resp.json()["data"]["items"]]
        assert code in codes

    def test_update_order(self, client):
        code = self._unique_code()
        create = client.post("/api/orders", json={
            "code": code, "product": "Upd", "qty": 10,
        })
        order_id = create.json()["data"]["id"]
        resp = client.put(f"/api/orders/{order_id}", json={
            "status": "in_progress",
        })
        assert resp.status_code == 200

    def test_delete_order(self, client):
        code = self._unique_code()
        create = client.post("/api/orders", json={
            "code": code, "product": "Del", "qty": 10,
        })
        order_id = create.json()["data"]["id"]
        resp = client.delete(f"/api/orders/{order_id}")
        assert resp.status_code == 200

    def test_order_not_found(self, client):
        resp = client.get("/api/orders/99999")
        assert resp.status_code == 404


# -- Customer tests ---

class TestCustomers:
    def _unique_name(self):
        import time
        return f"Corp{int(time.time() * 1000)}"

    def test_create_customer(self, client):
        resp = client.post("/api/customers", json={
            "name": self._unique_name(), "level": "A", "type": "vip",
        })
        assert resp.status_code == 200
        data = resp.json()["data"]
        # P0-4: response returns readable code strings not raw int IDs
        assert data["level"] == "A"
        assert data["type"] == "vip"

    def test_create_customer_defaults(self, client):
        """P0-6: create with no type/level uses valid defaults."""
        resp = client.post("/api/customers", json={
            "name": self._unique_name(),
        })
        assert resp.status_code == 200
        data = resp.json()["data"]
        assert data["type"] == "normal"
        assert data["level"] == "B"

    def test_list_customers(self, client):
        resp = client.get("/api/customers")
        assert resp.status_code == 200

    def test_list_customers_filter_by_type(self, client):
        """P0-3: filter by customer type (string param vs Integer FK)."""
        name1 = self._unique_name()
        client.post("/api/customers", json={"name": name1, "type": "normal"})
        name2 = self._unique_name()
        client.post("/api/customers", json={"name": name2, "type": "vip"})
        # Filter by 'normal' should find only name1
        resp = client.get(f"/api/customers?type=normal")
        assert resp.status_code == 200
        items = resp.json()["data"]["items"]
        names = [i["name"] for i in items]
        assert name1 in names, f"Expected {name1} in filtered results: {names}"
        assert name2 not in names, f"Did not expect {name2} in filtered results: {names}"

    def test_list_customers_filter_by_level(self, client):
        """P0-3: filter by customer level (string param vs Integer FK)."""
        name1 = self._unique_name()
        client.post("/api/customers", json={"name": name1, "level": "A"})
        name2 = self._unique_name()
        client.post("/api/customers", json={"name": name2, "level": "B"})
        resp = client.get(f"/api/customers?level=A")
        assert resp.status_code == 200
        items = resp.json()["data"]["items"]
        names = [i["name"] for i in items]
        assert name1 in names, f"Expected {name1} in filtered results: {names}"
        assert name2 not in names, f"Did not expect {name2} in filtered results: {names}"

    def test_customer_stats(self, client):
        resp = client.get("/api/customers/stats")
        assert resp.status_code == 200
        data = resp.json()["data"]
        assert "total" in data

    def test_update_customer_type_level(self, client):
        """P0-1/P0-6: update customer type/level via mapping."""
        name = self._unique_name()
        resp = client.post("/api/customers", json={"name": name})
        cust_id = resp.json()["data"]["id"]
        resp = client.put(f"/api/customers/{cust_id}", json={
            "type": "vip", "level": "A",
        })
        assert resp.status_code == 200
        data = resp.json()["data"]
        assert data["type"] == "vip"
        assert data["level"] == "A" 


# -- Inventory tests ---

class TestInventory:
    def _unique_code(self):
        import time
        return f"I{int(time.time() * 1000)}"

    def test_inbound(self, client):
        code = self._unique_code()
        client.post("/api/inventory", json={"code": code, "name": "Resistor"})
        resp = client.post("/api/inventory/inbound", json={
            "code": code, "qty": 500,
        })
        assert resp.status_code == 200
        assert resp.json()["data"]["stock"] == 500.0

    def test_outbound(self, client):
        code = self._unique_code()
        client.post("/api/inventory", json={"code": code, "name": "IC"})
        client.post("/api/inventory/inbound", json={"code": code, "qty": 200})
        resp = client.post("/api/inventory/outbound", json={
            "code": code, "qty": 50,
        })
        assert resp.status_code == 200
        assert resp.json()["data"]["stock"] == 150.0

    def test_outbound_insufficient(self, client):
        code = self._unique_code()
        client.post("/api/inventory", json={"code": code, "name": "Wire"})
        resp = client.post("/api/inventory/outbound", json={
            "code": code, "qty": 999,
        })
        assert resp.status_code == 400

    def test_inventory_stats(self, client):
        resp = client.get("/api/inventory/stats")
        assert resp.status_code == 200


# -- Equipment tests ---

class TestEquipment:
    def test_create_and_list(self, client):
        client.post("/api/equipment", json={"name": "TestMachine123"})
        resp = client.get("/api/equipment")
        assert resp.status_code == 200
        assert len(resp.json()["data"]) >= 1

    def test_equipment_stats(self, client):
        resp = client.get("/api/equipment/stats")
        assert resp.status_code == 200
        assert "running" in resp.json()["data"]


# -- Report tests ---

class TestReports:
    def test_report_kpi(self, client):
        resp = client.get("/api/reports/kpi")
        assert resp.status_code == 200
        data = resp.json()["data"]
        assert "totalOutput" in data
        assert "oee" in data
        assert "changes" in data

    def test_monthly_output(self, client):
        resp = client.get("/api/reports/monthly-output?months=3")
        assert resp.status_code == 200
        assert len(resp.json()["data"]["labels"]) == 3

    def test_product_mix(self, client):
        resp = client.get("/api/reports/product-mix")
        assert resp.status_code == 200

    def test_top_customers(self, client, seed_data, auth_headers):
        resp = client.get("/api/reports/top-customers", headers=auth_headers)
        assert resp.status_code == 200


# -- Dashboard tests ---

class TestDashboard:
    def test_dashboard_kpi(self, client):
        resp = client.get("/api/dashboard/kpi?range=today")
        assert resp.status_code == 200
        data = resp.json()["data"]
        assert "utilization" in data

    def test_ai_context(self, client):
        resp = client.get("/api/dashboard/ai-context")
        assert resp.status_code == 200
        assert "wasteRatio" in resp.json()["data"]

    def test_station_timeline(self, client):
        resp = client.get("/api/stations/timeline")
        assert resp.status_code == 200

    def test_therblig_distribution(self, client):
        resp = client.get("/api/worktime/therblig-distribution")
        assert resp.status_code == 200

    def test_bottleneck_diagnosis(self, client):
        resp = client.get("/api/line-balance/bottleneck-diagnosis")
        assert resp.status_code == 200


# -- Line balance tests ---

class TestLineBalance:
    def test_summary(self, client):
        resp = client.get("/api/line-balance/summary")
        assert resp.status_code == 200
        data = resp.json()["data"]
        assert "balanceRate" in data
        assert "smoothIndex" in data

    def test_full(self, client):
        resp = client.get("/api/line-balance/full?line=line1")
        assert resp.status_code == 200
        data = resp.json()["data"]
        assert "ecrsItems" in data
        assert "causalRules" in data
