"""
pytest 公共 Fixture
所有测试模块共享，pytest 自动发现
"""

import os
import tempfile

import numpy as np
import pytest
from fastapi.testclient import TestClient

# Ensure JWT_SECRET_KEY is set before any app import
os.environ.setdefault("JWT_SECRET_KEY", "test-secret-key-for-pytest-at-least-32b!")
# Enable test mode for auth bypass (defense-in-depth with PYTEST_CURRENT_TEST)
os.environ.setdefault("MES_TEST_MODE", "1")
# Default admin password for tests (P0-4: not set = no default users)
os.environ.setdefault("DEFAULT_ADMIN_PASSWORD", "changeme")


# ---------------------------------------------------------------------------
# Session-scoped test database + FastAPI app
# ---------------------------------------------------------------------------
# All business API tests share ONE temporary SQLite file per session.
# MES_DB_URL is set BEFORE app.main is imported so that lifespan's init_db
# creates tables in the test DB.  This avoids engine-cache pollution and
# cross-test-file deadlocks.


@pytest.fixture(scope="session")
def _test_db_file():
    """Create a temp DB file for the whole test session."""
    fd, path = tempfile.mkstemp(suffix=".db", prefix="mes_test_")
    os.close(fd)
    yield path
    try:
        os.unlink(path)
    except OSError:
        pass


@pytest.fixture(scope="session")
def _app_with_test_db(_test_db_file):
    """Build FastAPI app with test DB URL set BEFORE import.

    This ensures lifespan's init_db creates tables in the test DB.
    """
    db_url = f"sqlite:///{_test_db_file}"
    os.environ["MES_DB_URL"] = db_url

    # Clear any cached engines from prior imports
    from app.models.database import _engine_cache
    _engine_cache.clear()

    # Now import app (triggers lifespan on first TestClient context)
    from app.main import app
    yield app

    os.environ.pop("MES_DB_URL", None)
    _engine_cache.clear()


@pytest.fixture(scope="session")
def client(_app_with_test_db):
    """FastAPI test client backed by the session test database.

    Session-scoped to avoid repeated lifespan startup/shutdown (~3s each).
    All tests sharing this client use the same SQLite temp file.
    """
    with TestClient(_app_with_test_db) as c:
        yield c


@pytest.fixture(scope="session")
def seed_data(client):
    """Seed reference test data into the session database.

    Returns a dict with keys: customers, orders, equipment, inventory.
    Each value is a list of ORM model instances (id populated after flush).

    Session-scoped to seed exactly once before any test uses it.
    """
    from app.models.database import (
        get_session, Customer, CustomerType, CustomerLevel,
        Order, OrderStatus, OrderPriority, Equipment, InventoryItem,
    )

    db_url = os.environ.get("MES_DB_URL", "")
    if not db_url:
        raise RuntimeError(
            "MES_DB_URL must be set before calling seed_data. "
            "Ensure the _app_with_test_db fixture runs first."
        )
    session = get_session(db_url)

    # Look up FK references from seeded enums
    ct_normal = session.query(CustomerType).filter_by(code="normal").first()
    ct_vip = session.query(CustomerType).filter_by(code="vip").first()
    cl_b = session.query(CustomerLevel).filter_by(code="B").first()
    # For 'SA' level, use the closest enum — fallback to A
    cl_a = session.query(CustomerLevel).filter_by(code="A").first()

    c1 = Customer(name="TestCustomer1", contact="Alice", phone="13800001111",
                  city="Shenzhen", customer_type=ct_normal.id, level=cl_b.id,
                  status="active")
    c2 = Customer(name="TestCustomer2", contact="Bob", phone="13800002222",
                  city="Guangzhou", customer_type=ct_vip.id, level=cl_a.id,
                  status="active")
    session.add_all([c1, c2])
    session.flush()

    os_high = session.query(OrderStatus).filter_by(code="in_progress").first()
    os_comp = session.query(OrderStatus).filter_by(code="completed").first()
    os_pend = session.query(OrderStatus).filter_by(code="pending").first()
    op_high = session.query(OrderPriority).filter_by(code="high").first()
    op_norm = session.query(OrderPriority).filter_by(code="normal").first()
    op_low = session.query(OrderPriority).filter_by(code="low").first()

    o1 = Order(code="ORD-001", product="Widget A", spec="v1.0",
               customer_id=c1.id, quantity=100, completed_qty=80,
               due_date="2026-06-01", priority=op_high.id, status=os_high.id)
    o2 = Order(code="ORD-002", product="Widget B", spec="v2.0",
               customer_id=c1.id, quantity=200, completed_qty=200,
               due_date="2026-05-15", priority=op_norm.id, status=os_comp.id)
    o3 = Order(code="ORD-003", product="Gadget C", spec="v1.0",
               customer_id=c2.id, quantity=50, completed_qty=0,
               due_date="2026-07-01", priority=op_low.id, status=os_pend.id)
    session.add_all([o1, o2, o3])
    session.flush()

    e1 = Equipment(name="SMT-Line1", model="SM-481", workshop="Workshop A",
                   status="running", oee=0.85, utilization=0.78,
                   fault_count=2, mtbf_hours=120.0, today_util_pct=0.80)
    e2 = Equipment(name="Assembly-2", model="AS-200", workshop="Workshop A",
                   status="idle", oee=0.0, utilization=0.0,
                   fault_count=0, mtbf_hours=0.0, today_util_pct=0.0)
    session.add_all([e1, e2])
    session.flush()

    i1 = InventoryItem(code="MAT-001", name="Resistor 10K", spec="0603",
                       category="material", unit="pcs", stock=5000.0,
                       safe_stock=1000.0, location="A-01-01", warehouse="WH1",
                       price=0.01)
    i2 = InventoryItem(code="MAT-002", name="Capacitor 100nF", spec="0402",
                       category="material", unit="pcs", stock=200.0,
                       safe_stock=500.0, location="A-01-02", warehouse="WH1",
                       price=0.02)
    session.add_all([i1, i2])
    session.flush()

    session.commit()
    session.close()

    result = {
        "customers": [c1, c2],
        "orders": [o1, o2, o3],
        "equipment": [e1, e2],
        "inventory": [i1, i2],
    }
    return result


@pytest.fixture(scope="session")
def auth_headers(client):
    """Get JWT auth headers for test requests.

    Returns a dict suitable for passing to client.get/post as headers.
    """
    # Login to get a token
    resp = client.post("/api/auth/login", json={
        "username": "admin",
        "password": "changeme",
    })
    assert resp.status_code == 200, f"Login failed: {resp.text}"
    token = resp.json()["data"]["access_token"]
    return {"Authorization": f"Bearer {token}"}


# ---------------------------------------------------------------------------
# Perception / legacy fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def blank_frame_480p():
    """480p 空白帧，用于不需要真实图像的测试"""
    return np.zeros((480, 640, 3), dtype=np.uint8)


@pytest.fixture
def blank_frame_720p():
    """720p 空白帧"""
    return np.zeros((720, 1280, 3), dtype=np.uint8)


@pytest.fixture
def noise_frame_480p():
    """带随机噪点的帧，模拟真实摄像头噪点"""
    rng = np.random.default_rng(seed=42)
    return rng.integers(0, 256, (480, 640, 3), dtype=np.uint8)


@pytest.fixture
def frame_buffer_small():
    """容量为 5、启用丢弃旧帧的小缓冲队列"""
    from frame_buffer import FrameBuffer
    buf = FrameBuffer(max_size=5, drop_old=True)
    yield buf


@pytest.fixture
def frame_buffer_large():
    """容量为 100、不丢弃旧帧的大缓冲队列"""
    from frame_buffer import FrameBuffer
    buf = FrameBuffer(max_size=100, drop_old=False)
    yield buf


@pytest.fixture
def pose_estimator():
    """姿态识别器（model_complexity=0，速度优先，适合单元测试）"""
    from pose_estimator import PoseEstimator
    estimator = PoseEstimator(model_complexity=0, smooth=False)
    yield estimator
    estimator.close()


@pytest.fixture
def system_config():
    """加载默认系统配置"""
    from config import SystemConfig
    return SystemConfig()
