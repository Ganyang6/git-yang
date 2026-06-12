"""
RED Phase — decimal→percentage format unification (batch 1)

Verify all percentage fields return 0-100 format (frontend uses {value}% template).

Current state:
  - yieldRate:    already *100 (0-100 format ✓)
  - other fields: return 0-1 decimal (RED)

Assertion strategy:
  - When hasData=true and data exists, percentage values >= 1 (distinguishes 0-1 decimal from 0-100 percentage)
  - When no data, value is 0 or None

Note:
  - Current login password is "12345678" (bcrypt hash of admin password in config.yaml)
  - conftest DEFAULT_ADMIN_PASSWORD="changeme" is overridden by config.yaml users
  - Hence the custom auth_headers_local fixture
"""

import pytest


@pytest.fixture(scope="session")
def auth_headers_local(client):
    """Replace conftest auth_headers, using actual admin password from config.yaml."""
    resp = client.post("/api/auth/login", json={
        "username": "admin",
        "password": "12345678",
    })
    assert resp.status_code == 200, f"Login failed: {resp.text}"
    token = resp.json()["data"]["access_token"]
    return {"Authorization": f"Bearer {token}"}


# ---------------------------------------------------------------------------
# Independent seed fixtures (don't use conftest shared seed_data)
# Each test can depend on these independently, data written to shared test DB
# ---------------------------------------------------------------------------


@pytest.fixture(scope="module")
def seed_on_time_orders(client):
    """Seed on-time completed orders to make onTimeRate a non-integer fraction.

    seed_data creates 1 completed order (ORD-002, due 2026-05-15, overdue).
    This fixture adds 2 more: 1 on-time, 1 late.
    With 3 completed orders (1 on-time), onTimeRate = 1/3 ≈ 0.3333.
    """
    import os
    from app.models.database import get_session, Order, OrderStatus, OrderPriority, Customer

    db_url = os.environ.get("MES_DB_URL", "")
    session = get_session(db_url)

    os_comp = session.query(OrderStatus).filter_by(code="completed").first()
    op_norm = session.query(OrderPriority).filter_by(code="normal").first()
    c1 = session.query(Customer).filter_by(name="TestCustomer1").first()
    c2 = session.query(Customer).filter_by(name="TestCustomer2").first()

    # On-time completed order (due after today 2026-06-12)
    o_on_time = Order(
        code="ORD-ON-TIME", product="Widget A", spec="v1.0",
        customer_id=c1.id, quantity=50, completed_qty=50,
        due_date="2026-07-01",
        priority=op_norm.id, status=os_comp.id,
    )
    session.add(o_on_time)

    # Another late completed order (due before today)
    o_late = Order(
        code="ORD-LATE", product="Gadget D", spec="v2.0",
        customer_id=c2.id, quantity=30, completed_qty=30,
        due_date="2026-04-01",
        priority=op_norm.id, status=os_comp.id,
    )
    session.add(o_late)

    session.commit()
    session.close()
    return True


@pytest.fixture(scope="module")
def seed_quality_data(client):
    """Seed a QualityCheck record so yieldRate is computed.

    yieldRate = ok_qty / checked_qty * 100, already returns 0-100 format.
    Without seed data, yieldRate = None and the test assertion is skipped.
    """
    import os
    from app.models.database import get_session, Order, OrderStatus
    from app.models.quality_check import QualityCheck

    db_url = os.environ.get("MES_DB_URL", "")
    session = get_session(db_url)

    os_comp = session.query(OrderStatus).filter_by(code="completed").first()
    completed_order = session.query(Order).filter_by(status=os_comp.id).first()

    if completed_order:
        qc = QualityCheck(
            order_id=completed_order.id,
            checked_qty=100,
            ok_qty=85,
        )
        session.add(qc)
        session.commit()

    session.close()
    return True


@pytest.fixture(scope="module")
def seed_worktime_data(client):
    """Seed WorktimeRecord + TherbligDetail records.

    efficiency = standard_ms / actual_ms (0-1 decimal, currently un-fixed).
    avgEfficiency, wasteRatio, and per-operation efficiency are all 0-1.
    With data, assertions like ``avgEfficiency >= 1`` will fail.
    Includes a waste operation ("waiting") so wasteRatio > 0 for percentage format validation.
    """
    import os
    from app.models.database import get_session, WorktimeRecord, TherbligDetail

    db_url = os.environ.get("MES_DB_URL", "")
    session = get_session(db_url)

    # efficiency = standard_ms / actual_ms -> 0-1 decimal format
    r1 = WorktimeRecord(
        operation="reach",
        station_id="default",
        actual_ms=500.0,
        standard_ms=400.0,
        efficiency=0.8,
        mod_total=50.0,
        shift="morning",
    )
    r2 = WorktimeRecord(
        operation="grasp",
        station_id="default",
        actual_ms=300.0,
        standard_ms=250.0,
        efficiency=0.8333,
        mod_total=45.0,
        shift="morning",
    )
    # Waste operation — ensures wasteRatio > 0 for percentage format validation
    r3 = WorktimeRecord(
        operation="waiting",
        station_id="default",
        actual_ms=100.0,
        standard_ms=0.0,
        efficiency=0.0,
        mod_total=0.0,
        shift="morning",
    )
    session.add_all([r1, r2, r3])
    session.flush()

    d1 = TherbligDetail(
        worktime_record_id=r1.id, symbol="R", name="Reach",
        mod=5.0, actual_ms=500.0, pct=50.0, is_waste=False,
    )
    d2 = TherbligDetail(
        worktime_record_id=r2.id, symbol="G", name="Grasp",
        mod=4.0, actual_ms=300.0, pct=30.0, is_waste=False,
    )
    session.add_all([d1, d2])

    session.commit()
    session.close()
    return True


# ===========================================================================
# Test classes
# ===========================================================================


class TestReportsKpiPercentages:
    """/api/reports/kpi percentage fields"""

    def test_completion_rate_is_percentage(self, client, seed_data, auth_headers_local):
        resp = client.get("/api/reports/kpi", headers=auth_headers_local)
        assert resp.status_code == 200
        data = resp.json()["data"]

        assert "completionRate" in data
        assert "completionRate_hasData" in data

        # When hasData, value should be >= 1 (0-100 percentage, not 0-1 decimal)
        if data["completionRate_hasData"]:
            assert data["completionRate"] >= 1, (
                f"completionRate={data['completionRate']} is 0-1 decimal, "
                f"should be 0-100 percentage"
            )

        # Basic range validation
        assert data["completionRate"] >= 0
        assert data["completionRate"] <= 100

    def test_on_time_rate_is_percentage(self, client, seed_data, seed_on_time_orders, auth_headers_local):
        res = client.get("/api/reports/kpi", headers=auth_headers_local)
        assert res.status_code == 200
        data = res.json()["data"]

        assert "onTimeRate" in data
        assert data["onTimeRate"] >= 0
        assert data["onTimeRate"] <= 100

        # When hasData, value should be >= 1 (0-100 percentage)
        if data["onTimeRate_hasData"]:
            assert data["onTimeRate"] >= 1, (
                f"onTimeRate={data['onTimeRate']} is 0-1 decimal, "
                f"should be 0-100 percentage"
            )

    def test_yield_rate_is_percentage(self, client, seed_data, seed_quality_data, auth_headers_local):
        res = client.get("/api/reports/kpi", headers=auth_headers_local)
        assert res.status_code == 200
        data = res.json()["data"]

        assert "yieldRate" in data
        val = data["yieldRate"]
        # GREEN phase: yieldRate is already *100 (0-100 format), verify 0-100 range
        if val is not None:
            assert val >= 1, (
                f"yieldRate={val} is 0-1 decimal format, "
                f"should be 0-100 percentage"
            )
            assert val <= 100

    def test_utilization_is_percentage(self, client, seed_data, auth_headers_local):
        """Verify utilization field exists and is 0-100 percentage."""
        res = client.get("/api/reports/kpi", headers=auth_headers_local)
        assert res.status_code == 200
        data = res.json()["data"]

        assert "utilization" in data, "Missing utilization field in ReportKpi"
        assert "utilization_hasData" in data, "Missing utilization_hasData field"

        val = data["utilization"]
        assert val >= 0.0
        assert val <= 100.0

        # When hasData, it should be 0-100 percentage (not 0-1 decimal)
        if data["utilization_hasData"]:
            assert val >= 1, (
                f"utilization={val} is 0-1 decimal format, "
                f"should be 0-100 percentage"
            )


class TestTopCustomersSharePercentages:
    """/api/reports/top-customers share field"""

    def test_top_customers_share_is_percentage(self, client, seed_data, auth_headers_local):
        resp = client.get("/api/reports/top-customers", headers=auth_headers_local)
        assert resp.status_code == 200
        items = resp.json()["data"]

        assert len(items) >= 1
        for item in items:
            share = item["share"]
            assert share >= 0, f"share for {item['name']} is negative: {share}"
            assert share <= 100, f"share for {item['name']} > 100: {share}"
            # When share > 0, it should be 0-100 percentage (>= 1)
            if share > 0:
                assert share >= 1, (
                    f"share for {item['name']} is {share} (should be 0-100 percentage, "
                    f"got 0-1 decimal)"
                )


class TestWorktimeSummaryPercentages:
    """/api/v1/worktime/summary percentage fields"""

    def test_worktime_summary_percentages(self, client, seed_data, seed_worktime_data, auth_headers_local):
        resp = client.get("/api/v1/worktime/summary", headers=auth_headers_local)
        assert resp.status_code == 200
        data = resp.json()["data"]

        # avgEfficiency: should be 0-100 percentage
        assert "avgEfficiency" in data
        assert data["avgEfficiency"] >= 0
        assert data["avgEfficiency"] <= 100
        if data["totalOps"] > 0:
            assert data["avgEfficiency"] >= 1, (
                f"avgEfficiency={data['avgEfficiency']} is 0-1 decimal, "
                f"should be 0-100 percentage"
            )

        # wasteRatio: should be 0-100 percentage
        assert "wasteRatio" in data
        assert data["wasteRatio"] >= 0
        assert data["wasteRatio"] <= 100
        if data["totalOps"] > 0 and data["wasteRatio"] > 0:
            assert data["wasteRatio"] >= 1, (
                f"wasteRatio={data['wasteRatio']} is 0-1 decimal, "
                f"should be 0-100 percentage"
            )


class TestOperationsEfficiencyPercentages:
    """/api/v1/worktime/operations efficiency field"""

    def test_operations_efficiency_is_percentage(self, client, seed_data, seed_worktime_data, auth_headers_local):
        resp = client.get("/api/v1/worktime/operations", headers=auth_headers_local)
        assert resp.status_code == 200
        items = resp.json()["data"]

        assert len(items) >= 1, "No worktime operations returned"
        for item in items:
            eff = item["efficiency"]
            assert eff >= 0, f"efficiency for {item['id']} is negative: {eff}"
            assert eff <= 100, f"efficiency for {item['id']} > 100: {eff}"
            if eff > 0:
                assert eff >= 1, (
                    f"efficiency for operation {item['id']} ({item['operation']}) "
                    f"is {eff} (should be 0-100 percentage, got 0-1 decimal)"
                )
