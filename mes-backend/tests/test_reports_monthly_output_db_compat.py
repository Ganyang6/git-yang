"""
Test: monthly-output endpoint uses DB-compatible date formatting.

Issue #12: reports.py used func.strftime("%Y-%m", ...) which only works
in SQLite. This test ensures the endpoint works with a DB-agnostic approach.

NOTE: auth_headers fixture from conftest is broken because config.yaml has
a hardcoded bcrypt hash that doesn't match 'changeme'. This test generates
its own JWT token directly to work around the issue.
"""

import os
from datetime import datetime, timezone, timedelta

import jwt
import pytest


@pytest.fixture(scope="module")
def token_headers():
    """Generate valid JWT token headers without relying on login endpoint."""
    secret = os.environ.get(
        "JWT_SECRET_KEY",
        "test-secret-key-for-pytest-at-least-32b!",
    )
    now = datetime.now(timezone.utc)
    payload = {
        "sub": "admin",
        "role": "admin",
        "display_name": "Test Admin",
        "exp": now + timedelta(hours=1),
        "iat": now,
        "jti": "admin:test",
    }
    token = jwt.encode(payload, secret, algorithm="HS256")
    return {"Authorization": f"Bearer {token}"}


def _seed_cross_month_orders():
    """Insert orders with created_at spanning multiple months."""
    from app.models.database import Order, OrderStatus, OrderPriority, Customer, get_session

    db_url = os.environ.get("MES_DB_URL", "")
    session = get_session(db_url)

    # Check if already seeded
    existing = session.query(Order.code).filter(
        Order.code.in_(["DBCOMPAT-001", "DBCOMPAT-002", "DBCOMPAT-003"])
    ).all()
    if len(existing) == 3:
        session.close()
        return

    # Find FK references
    os_comp = session.query(OrderStatus).filter_by(code="completed").first()
    op_norm = session.query(OrderPriority).filter_by(code="normal").first()
    customer = session.query(Customer).first()
    assert customer is not None, "No customer found — seed_data must run first"

    now = datetime.now(timezone.utc)

    orders = [
        Order(
            code="DBCOMPAT-001", product="Widget A", spec="v1.0",
            customer_id=customer.id, quantity=100, completed_qty=50,
            due_date="2026-03-01", priority=op_norm.id, status=os_comp.id,
            created_at=now - timedelta(days=120),
        ),
        Order(
            code="DBCOMPAT-002", product="Widget B", spec="v2.0",
            customer_id=customer.id, quantity=200, completed_qty=100,
            due_date="2026-04-01", priority=op_norm.id, status=os_comp.id,
            created_at=now - timedelta(days=90),
        ),
        Order(
            code="DBCOMPAT-003", product="Widget C", spec="v1.0",
            customer_id=customer.id, quantity=150, completed_qty=150,
            due_date="2026-05-01", priority=op_norm.id, status=os_comp.id,
            created_at=now - timedelta(days=60),
        ),
    ]

    for o in orders:
        session.add(o)
    session.commit()
    session.close()


# ---------------------------------------------------------------------------


class TestMonthlyOutputDbCompat:
    """Verify monthly-output endpoint works across DB backends."""

    @pytest.fixture(scope="class", autouse=True)
    def _setup(self, seed_data):
        """Insert cross-month orders once for all tests in the class."""
        _seed_cross_month_orders()

    def test_monthly_output_returns_200(self, client, token_headers):
        """GET /api/reports/monthly-output returns 200."""
        resp = client.get("/api/reports/monthly-output", headers=token_headers)
        assert resp.status_code == 200, (
            f"Expected 200, got {resp.status_code}: {resp.text}"
        )

    def test_monthly_output_has_data(self, client, token_headers):
        """Response contains 'labels' and 'values' arrays."""
        resp = client.get("/api/reports/monthly-output", headers=token_headers)
        data = resp.json()["data"]
        assert "labels" in data, "Response missing 'labels'"
        assert "values" in data, "Response missing 'values'"
        assert isinstance(data["labels"], list), "'labels' must be a list"
        assert isinstance(data["values"], list), "'values' must be a list"

    def test_monthly_output_format_is_yyyy_mm(self, client, token_headers):
        """All label strings match YYYY-MM format."""
        import re
        resp = client.get("/api/reports/monthly-output", headers=token_headers)
        data = resp.json()["data"]
        pattern = re.compile(r"^\d{4}-\d{2}$")
        for label in data["labels"]:
            assert pattern.match(label), f"Label '{label}' is not YYYY-MM format"
