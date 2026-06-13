"""
RED Phase — P0 fixes: export endpoint, KPI period filter, top-customers period filter.

Tests:
  1. test_export_endpoint_exists — GET /api/reports/worktime/pdf returns 200
  2. test_kpi_period_filters_data — seed cross-month orders, verify different period
     filters return different KPI data
  3. test_top_customers_period_filters_data — same for top-customers
"""

import pytest
from datetime import datetime, timezone, timedelta


@pytest.fixture(scope="module")
def auth_headers_local(client):
    """Login using the actual admin password from config.yaml."""
    resp = client.post("/api/auth/login", json={
        "username": "admin",
        "password": "12345678",
    })
    assert resp.status_code == 200, f"Login failed: {resp.text}"
    token = resp.json()["data"]["access_token"]
    return {"Authorization": f"Bearer {token}"}


@pytest.fixture(scope="module")
def seed_cross_period_orders(client, auth_headers_local, seed_data):
    """Seed orders with created_at dates crossing month boundary.

    Creates:
      - 1 old order (created 60 days ago) — customer1, qty=100, completed_qty=100
      - 1 recent order (created 2 days ago) — customer2, qty=50, completed_qty=50

    Also seed ProcessSegments for the purpose of KPI utilization.
    """
    import os
    from app.models.database import get_session, Order, OrderStatus, OrderPriority, \
        Customer, ProcessSegment

    db_url = os.environ.get("MES_DB_URL", "")
    session = get_session(db_url)

    os_comp = session.query(OrderStatus).filter_by(code="completed").first()
    op_norm = session.query(OrderPriority).filter_by(code="normal").first()
    c1 = session.query(Customer).filter_by(name="TestCustomer1").first()
    c2 = session.query(Customer).filter_by(name="TestCustomer2").first()

    now = datetime.now(timezone.utc)

    # Old order: 60 days ago — should only appear in quarter filter
    old_order = Order(
        code="ORD-P0-OLD", product="Widget A", spec="v1.0",
        customer_id=c1.id, quantity=100, completed_qty=100,
        due_date="2026-06-01",
        priority=op_norm.id, status=os_comp.id,
        created_at=now - timedelta(days=60),
    )
    session.add(old_order)
    session.flush()

    # Recent order: 2 days ago — should appear in all filters (week/month/quarter)
    recent_order = Order(
        code="ORD-P0-RECENT", product="Widget B", spec="v2.0",
        customer_id=c2.id, quantity=50, completed_qty=50,
        due_date="2026-07-01",
        priority=op_norm.id, status=os_comp.id,
        created_at=now - timedelta(days=2),
    )
    session.add(recent_order)
    session.flush()

    # Seed ProcessSegments for utilization calculation
    old_seg = ProcessSegment(
        camera_id="cam1",
        station_id="STN-001",
        line="L1",
        action="work",
        start_time=now - timedelta(days=60),
        end_time=now - timedelta(days=60) + timedelta(seconds=10),
        duration_ms=10000,
    )
    session.add(old_seg)

    recent_seg = ProcessSegment(
        camera_id="cam1",
        station_id="STN-001",
        line="L1",
        action="work",
        start_time=now - timedelta(days=2),
        end_time=now - timedelta(days=2) + timedelta(seconds=5),
        duration_ms=5000,
    )
    session.add(recent_seg)

    session.commit()
    session.close()
    return {
        "old_order_id": old_order.id,
        "recent_order_id": recent_order.id,
    }


# ---------------------------------------------------------------------------
# Test 1: Export endpoint exists
# ---------------------------------------------------------------------------


def test_export_endpoint_exists(client, auth_headers_local, seed_cross_period_orders):
    """GET /api/reports/worktime/pdf should return 200 (not 404)."""
    resp = client.get(
        "/api/reports/worktime/pdf?station_id=all&period=today",
        headers=auth_headers_local,
    )
    assert resp.status_code == 200, (
        f"Export endpoint should return 200, got {resp.status_code}: {resp.text[:200]}"
    )
    assert resp.headers.get("content-type") == "application/pdf", (
        f"Expected PDF content type, got: {resp.headers.get('content-type')}"
    )


# ---------------------------------------------------------------------------
# Test 2: KPI period filters data
# ---------------------------------------------------------------------------


def test_kpi_period_filters_data(client, auth_headers_local, seed_cross_period_orders):
    """GET /api/reports/kpi with different period params returns different data.

    We seed 2 cross-period orders on top of conftest seed_data:
      - old (60 days ago): TestCustomer1, qty=100, completed_qty=100
      - recent (2 days ago): TestCustomer2, qty=50, completed_qty=50

    conftest seed_data orders (ORD-001/002/003) have auto-generated
    created_at=now, so they fall within all filters.

    Relative assertions:
      - Week totalOutput < Quarter totalOutput (quarter sees old order)
      - Difference == 100 (completed_qty of the old order)
    """
    resp_week = client.get(
        "/api/reports/kpi?period=week",
        headers=auth_headers_local,
    )
    assert resp_week.status_code == 200
    week_data = resp_week.json()["data"]

    resp_month = client.get(
        "/api/reports/kpi?period=month",
        headers=auth_headers_local,
    )
    assert resp_month.status_code == 200
    month_data = resp_month.json()["data"]

    resp_quarter = client.get(
        "/api/reports/kpi?period=quarter",
        headers=auth_headers_local,
    )
    assert resp_quarter.status_code == 200
    quarter_data = resp_quarter.json()["data"]

    # Week and month should return same values (both exclude 60-day-old order)
    assert week_data["totalOutput"] == month_data["totalOutput"], (
        f"Week and month totalOutput should be equal (both exclude old order), "
        f"week={week_data['totalOutput']} month={month_data['totalOutput']}"
    )

    # Quarter should return MORE data than week (quarter includes 60-day-old order)
    assert quarter_data["totalOutput"] > week_data["totalOutput"], (
        f"Quarter totalOutput ({quarter_data['totalOutput']}) should be "
        f"greater than week ({week_data['totalOutput']}) — old order only in quarter"
    )

    # The difference should be exactly 100 (completed_qty of old order)
    diff = quarter_data["totalOutput"] - week_data["totalOutput"]
    assert diff == 100, (
        f"Difference between quarter and week totalOutput should be 100 "
        f"(old order completed_qty), got {diff}. "
        f"week={week_data['totalOutput']}, quarter={quarter_data['totalOutput']}"
    )


# ---------------------------------------------------------------------------
# Test 3: Top customers period filters data
# ---------------------------------------------------------------------------


def test_top_customers_period_filters_data(client, auth_headers_local, seed_cross_period_orders):
    """GET /api/reports/top-customers with different period params returns different data.

    Old order (60 days, qty=100, TestCustomer1) should only appear in quarter.
    Recent order (2 days, qty=50, TestCustomer2) appears in all filters.

    conftest seed_data orders for TestCustomer1 (ORD-001 qty=100, ORD-002 qty=200)
    and TestCustomer2 (ORD-003 qty=50) have created_at=now, in all filters.

    Relative assertions:
      - Week TestCustomer1 qty == Month TestCustomer1 qty (same data set)
      - Quarter TestCustomer1 qty == Week TestCustomer1 qty + 100 (old order)
      - TestCustomer2 qty is constant across all filters (no old orders)
    """
    resp_week = client.get(
        "/api/reports/top-customers?period=week",
        headers=auth_headers_local,
    )
    assert resp_week.status_code == 200
    week_items = resp_week.json()["data"]

    resp_month = client.get(
        "/api/reports/top-customers?period=month",
        headers=auth_headers_local,
    )
    assert resp_month.status_code == 200
    month_items = resp_month.json()["data"]

    resp_quarter = client.get(
        "/api/reports/top-customers?period=quarter",
        headers=auth_headers_local,
    )
    assert resp_quarter.status_code == 200
    quarter_items = resp_quarter.json()["data"]

    week_map = {i["name"]: i["qty"] for i in week_items}
    month_map = {i["name"]: i["qty"] for i in month_items}
    quarter_map = {i["name"]: i["qty"] for i in quarter_items}

    # Week and month should have same data for TestCustomer1
    assert week_map.get("TestCustomer1") == month_map.get("TestCustomer1"), (
        f"Week and month TestCustomer1 qty should match: "
        f"week={week_map.get('TestCustomer1')}, month={month_map.get('TestCustomer1')}"
    )

    # Quarter TestCustomer1 should have 100 more qty (old order)
    week_c1 = week_map.get("TestCustomer1", 0)
    quarter_c1 = quarter_map.get("TestCustomer1", 0)
    assert quarter_c1 == week_c1 + 100, (
        f"Quarter TestCustomer1 qty ({quarter_c1}) should be "
        f"week + 100 ({week_c1 + 100}). "
        f"Difference indicates old order (qty=100) is {'not' if quarter_c1 == week_c1 else ''} "
        f"being filtered correctly."
    )

    # TestCustomer2 should be same across all filters (no old orders)
    assert week_map.get("TestCustomer2") == quarter_map.get("TestCustomer2"), (
        f"TestCustomer2 qty should be constant across filters: "
        f"week={week_map.get('TestCustomer2')}, quarter={quarter_map.get('TestCustomer2')}"
    )
    assert week_map.get("TestCustomer2") == month_map.get("TestCustomer2"), (
        f"TestCustomer2 qty should match: "
        f"week={week_map.get('TestCustomer2')}, month={month_map.get('TestCustomer2')}"
    )
