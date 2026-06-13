"""
RED Phase — P1 fixes: top-customers trend, amount duplication, radar effective ratio.

Tests:
  1. test_top_customers_trend_not_empty — seed cross-period orders, verify trend is
     non-empty float with reasonable values
  2. test_top_customers_amount_not_qty — amount field removed/zeroed (no longer
     duplicates qty)
  3. test_radar_effective_ratio_differs_by_station — stations with different
     waste ratios have different efficiency values
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
def seed_cross_period_topcust(client, auth_headers_local, seed_data):
    """Seed orders that cross period boundaries for trend calculation.

    Creates:
      - 2 orders for TestCustomer1: one old (prev period), one recent (current period)
      - 2 orders for TestCustomer2: one old (prev period), one recent (current period)

    Also seed ProcessSegments with different waste ratios per station for the
    radar effective-ratio test.
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

    # ── Cross-period orders for trend test ──

    # TestCustomer1: prev period (qty=200), current period (qty=300)
    # Trend should be (300-200)/200*100 = 50%
    prev_o1 = Order(
        code="ORD-P1-PREV-C1", product="Widget A", spec="v1.0",
        customer_id=c1.id, quantity=200, completed_qty=200,
        due_date="2026-05-01",
        priority=op_norm.id, status=os_comp.id,
        created_at=now - timedelta(days=45),
    )
    session.add(prev_o1)

    cur_o1 = Order(
        code="ORD-P1-CUR-C1", product="Widget A", spec="v1.0",
        customer_id=c1.id, quantity=300, completed_qty=300,
        due_date="2026-07-01",
        priority=op_norm.id, status=os_comp.id,
        created_at=now - timedelta(days=5),
    )
    session.add(cur_o1)

    # TestCustomer2: prev period (qty=100), current period (qty=50)
    # Trend should be (50-100)/100*100 = -50%
    prev_o2 = Order(
        code="ORD-P1-PREV-C2", product="Gadget C", spec="v1.0",
        customer_id=c2.id, quantity=100, completed_qty=100,
        due_date="2026-05-01",
        priority=op_norm.id, status=os_comp.id,
        created_at=now - timedelta(days=45),
    )
    session.add(prev_o2)

    cur_o2 = Order(
        code="ORD-P1-CUR-C2", product="Gadget C", spec="v1.0",
        customer_id=c2.id, quantity=50, completed_qty=50,
        due_date="2026-07-01",
        priority=op_norm.id, status=os_comp.id,
        created_at=now - timedelta(days=5),
    )
    session.add(cur_o2)

    # ── ProcessSegments for radar efficiency test ──
    # Station STN-001: mostly work (high efficiency ~90%)
    # Station STN-002: mostly wait/idle (low efficiency ~30%)

    # STN-001: 9 work segments (100ms each) + 1 wait segment (100ms)
    for i in range(9):
        session.add(ProcessSegment(
            camera_id="cam1", station_id="STN-001", line="line1",
            action="work", duration_ms=100,
            start_time=now - timedelta(hours=1, minutes=5*i),
            end_time=now - timedelta(hours=1, minutes=5*i) + timedelta(milliseconds=100),
        ))
    session.add(ProcessSegment(
        camera_id="cam1", station_id="STN-001", line="line1",
        action="wait", duration_ms=100,
        start_time=now - timedelta(hours=1, minutes=1),
        end_time=now - timedelta(hours=1, minutes=1) + timedelta(milliseconds=100),
    ))

    # STN-002: 3 work segments (100ms each) + 7 wait/idle segments (100ms each)
    for i in range(3):
        session.add(ProcessSegment(
            camera_id="cam2", station_id="STN-002", line="line1",
            action="work", duration_ms=100,
            start_time=now - timedelta(hours=2, minutes=5*i),
            end_time=now - timedelta(hours=2, minutes=5*i) + timedelta(milliseconds=100),
        ))
    for i in range(4):
        session.add(ProcessSegment(
            camera_id="cam2", station_id="STN-002", line="line1",
            action="wait", duration_ms=100,
            start_time=now - timedelta(hours=2, minutes=5*i),
            end_time=now - timedelta(hours=2, minutes=5*i) + timedelta(milliseconds=100),
        ))
    for i in range(3):
        session.add(ProcessSegment(
            camera_id="cam2", station_id="STN-002", line="line1",
            action="idle", duration_ms=100,
            start_time=now - timedelta(hours=2, minutes=5*i),
            end_time=now - timedelta(hours=2, minutes=5*i) + timedelta(milliseconds=100),
        ))

    session.flush()
    session.commit()
    session.close()
    return {}


# ---------------------------------------------------------------------------
# Test 1: top-customers trend is non-empty
# ---------------------------------------------------------------------------


def test_top_customers_trend_not_empty(client, auth_headers_local, seed_cross_period_topcust):
    """GET /api/reports/top-customers returns trend as non-zero float.

    After seeding:
      - TestCustomer1: prev=200, cur=300 → trend ≈ 50.0
      - TestCustomer2: prev=100, cur=50  → trend ≈ -50.0

    All trends should be float (not empty string), and at least one
    customer should have non-zero trend given the seeded data.
    """
    resp = client.get(
        "/api/reports/top-customers?period=month",
        headers=auth_headers_local,
    )
    assert resp.status_code == 200, f"top-customers failed: {resp.status_code}"
    items = resp.json()["data"]
    assert len(items) > 0, "Expected at least one top customer"

    # Verify at least one customer has non-zero trend
    trends = [i.get("trend") for i in items]
    non_zero = [t for t in trends if t != 0]
    assert len(non_zero) > 0, (
        f"All trends are zero: {trends}. "
        f"Expected at least one non-zero trend from cross-period seed data. "
        f"Items: {[(i['name'], i['qty'], i['trend']) for i in items]}"
    )

    # Verify trend is numeric (not empty string)
    for item in items:
        trend = item.get("trend")
        assert isinstance(trend, (int, float)), (
            f"Expected numeric trend, got {type(trend).__name__}: {trend}"
        )
        assert trend != "", "trend should not be empty string"


# ---------------------------------------------------------------------------
# Test 2: top-customers amount field no longer duplicates qty
# ---------------------------------------------------------------------------


def test_top_customers_amount_not_qty(client, auth_headers_local, seed_cross_period_topcust):
    """GET /api/reports/top-customers should NOT have amount duplicating qty.

    The amount field is removed from the API response to eliminate
    confusion with qty. If amount is present, it must not equal qty.
    """
    resp = client.get(
        "/api/reports/top-customers?period=month",
        headers=auth_headers_local,
    )
    assert resp.status_code == 200, f"top-customers failed: {resp.status_code}"
    items = resp.json()["data"]
    assert len(items) > 0, "Expected at least one top customer"

    for item in items:
        qty = item.get("qty", 0)
        # amount should either be absent, 0.0, or differ from qty
        if "amount" in item:
            amt = item["amount"]
            if amt != 0.0:
                assert amt != qty, (
                    f"amount ({amt}) should not equal qty ({qty}) for {item['name']}"
                )


# ---------------------------------------------------------------------------
# Test 3: radar chart effective ratio differs by station
# ---------------------------------------------------------------------------


def test_radar_effective_ratio_differs_by_station(client, auth_headers_local, seed_cross_period_topcust):
    """GET /api/line-balance/full returns stations with different efficiency.

    STN-001 has 9 work + 1 wait (total=1000ms, waste=100ms → eff=0.9)
    STN-002 has 3 work + 4 wait + 3 idle (total=1000ms, waste=700ms → eff=0.3)

    The two stations should have noticeably different efficiency values.
    """
    resp = client.get(
        "/api/line-balance/full?line=line1",
        headers=auth_headers_local,
    )
    assert resp.status_code == 200, f"line-balance/full failed: {resp.status_code}"
    data = resp.json().get("data", {})
    stations = data.get("stations", [])

    assert len(stations) >= 2, (
        f"Expected at least 2 stations, got {len(stations)}: "
        f"{[s['name'] for s in stations]}"
    )

    # Build station lookup
    station_map = {s["name"]: s for s in stations}

    # Check that both STN-001 and STN-002 are present
    for st_name in ["STN-001", "STN-002"]:
        assert st_name in station_map, (
            f"Station {st_name} not found in response. "
            f"Available: {list(station_map.keys())}"
        )

    s1_eff = station_map["STN-001"].get("efficiency", 0)
    s2_eff = station_map["STN-002"].get("efficiency", 0)

    # STN-001 should have much higher efficiency than STN-002
    assert s1_eff > s2_eff, (
        f"Expected STN-001 efficiency ({s1_eff}) > STN-002 efficiency ({s2_eff}). "
        f"STN-001 has 9 work + 1 wait (90%), STN-002 has 3 work + 7 waste (30%). "
        f"Full station data: {stations}"
    )

    # STN-001 should be >= 0.8 (10% waste)
    assert s1_eff >= 0.8, (
        f"Expected STN-001 efficiency >= 0.8, got {s1_eff}. "
        f"STN-001 has 9 work + 1 wait."
    )

    # STN-002 should be < 0.5 (70% waste)
    assert s2_eff < 0.5, (
        f"Expected STN-002 efficiency < 0.5, got {s2_eff}. "
        f"STN-002 has 3 work + 4 wait + 3 idle."
    )

    # Difference should be at least 0.4
    diff = s1_eff - s2_eff
    assert diff >= 0.4, (
        f"Efficiency difference between STN-001 and STN-002 should be >= 0.4, "
        f"got {diff:.4f}. s1={s1_eff}, s2={s2_eff}. "
        f"Full station data: {stations}"
    )
