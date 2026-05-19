"""Tests for demo data seeding script (T5-10).

Verifies that the seeding script populates all tables correctly
and data relationships are consistent.
"""

from __future__ import annotations

import os
import tempfile
import shutil
import pytest

from app.models.database import (
    Base,
    Customer,
    Equipment,
    InventoryItem,
    InventoryLog,
    Order,
    ProcessSegment,
    TherbligDetail,
    WorktimeRecord,
    init_db,
)

# Use a fixed temp directory to avoid Windows file locking issues
_SEED_TEST_DIR = os.path.join(tempfile.gettempdir(), "mes_seed_test")
_SEED_DB_PATH = os.path.join(_SEED_TEST_DIR, "test_mes.db")


@pytest.fixture(scope="module")
def seeded_session():
    """Create a temporary database, seed it, and return the session."""
    # Clean up any previous test artifacts
    if os.path.exists(_SEED_TEST_DIR):
        try:
            shutil.rmtree(_SEED_TEST_DIR, ignore_errors=True)
        except OSError:
            pass
    os.makedirs(_SEED_TEST_DIR, exist_ok=True)

    db_url = f"sqlite:///{_SEED_DB_PATH}"
    os.environ["MES_DB_URL"] = db_url
    session = init_db(db_url)

    # Import and run the seeding script
    from scripts.seed_demo_data import (
        seed_customers,
        seed_orders,
        seed_equipment,
        seed_inventory,
        seed_process_segments,
        seed_worktime_and_therblig,
    )

    seed_customers(session)
    seed_orders(session)
    seed_equipment(session)
    seed_inventory(session)
    seed_process_segments(session)
    seed_worktime_and_therblig(session)

    yield session
    session.close()


class TestSeedCustomers:
    def test_customers_created(self, seeded_session):
        count = seeded_session.query(Customer).count()
        assert count == len(CUSTOMERS_DATA)

    def test_customer_fields(self, seeded_session):
        customer = seeded_session.query(Customer).first()
        assert customer.name
        assert customer.contact
        assert customer.phone
        assert customer.status == "active"

    def test_vip_customers_exist(self, seeded_session):
        vip_count = seeded_session.query(Customer).filter(
            Customer.customer_type == "vip"
        ).count()
        assert vip_count >= 2


# Reference data for assertions
CUSTOMERS_DATA = [
    ("Huawei Technologies", "Zhang Wei", "138-0001-0001", "Shenzhen"),
    ("BYD Auto", "Li Na", "139-0002-0002", "Xi'an"),
    ("Foxconn Electronics", "Wang Jun", "137-0003-0003", "Zhengzhou"),
    ("Midea Group", "Chen Fang", "136-0004-0004", "Foshan"),
    ("Gree Electric", "Zhao Qiang", "135-0005-0005", "Zhuhai"),
    ("CATL", "Liu Yang", "134-0006-0006", "Ningde"),
    ("Luxshare Precision", "Sun Li", "133-0007-0007", "Dongguan"),
    ("Goertek Inc", "Zhou Ming", "132-0008-0008", "Weifang"),
]


class TestSeedOrders:
    def test_orders_created(self, seeded_session):
        count = seeded_session.query(Order).count()
        assert count >= 20  # 8 customers * 3-8 orders each

    def test_order_has_customer(self, seeded_session):
        order = seeded_session.query(Order).first()
        assert order.customer_id is not None
        customer = seeded_session.get(Customer, order.customer_id)
        assert customer is not None

    def test_order_code_format(self, seeded_session):
        order = seeded_session.query(Order).first()
        assert order.code.startswith("PO-2026-")

    def test_completed_orders(self, seeded_session):
        completed = seeded_session.query(Order).filter(
            Order.status == "completed"
        ).count()
        assert completed > 0


class TestSeedEquipment:
    def test_equipment_created(self, seeded_session):
        count = seeded_session.query(Equipment).count()
        assert count == 8

    def test_equipment_fields(self, seeded_session):
        eq = seeded_session.query(Equipment).first()
        assert eq.name
        assert eq.model
        assert eq.workshop
        assert eq.status in ("running", "idle", "maintenance", "fault")

    def test_running_equipment_has_oee(self, seeded_session):
        running = seeded_session.query(Equipment).filter(
            Equipment.status == "running"
        ).all()
        for eq in running:
            assert eq.oee > 0


class TestSeedInventory:
    def test_inventory_items_created(self, seeded_session):
        count = seeded_session.query(InventoryItem).count()
        assert count == 8

    def test_inventory_logs_created(self, seeded_session):
        count = seeded_session.query(InventoryLog).count()
        assert count >= 16  # 8 items * 2-6 logs each

    def test_item_code_unique(self, seeded_session):
        codes = [item.code for item in seeded_session.query(InventoryItem).all()]
        assert len(codes) == len(set(codes))

    def test_log_references_item(self, seeded_session):
        log = seeded_session.query(InventoryLog).first()
        item = seeded_session.get(InventoryItem, log.inventory_item_id)
        assert item is not None


class TestSeedProcessSegments:
    def test_segments_created(self, seeded_session):
        count = seeded_session.query(ProcessSegment).count()
        assert count >= 500  # substantial data for demo

    def test_segments_have_stations(self, seeded_session):
        stations = set(
            seg.station_id for seg in seeded_session.query(ProcessSegment).all()
        )
        assert len(stations) >= 3  # at least 3 different stations

    def test_segments_have_shifts(self, seeded_session):
        shifts = set(
            seg.shift for seg in seeded_session.query(ProcessSegment).all()
        )
        assert "morning" in shifts or "afternoon" in shifts

    def test_segments_have_actions(self, seeded_session):
        actions = set(
            seg.action for seg in seeded_session.query(ProcessSegment).all()
        )
        assert len(actions) >= 3

    def test_segments_have_durations(self, seeded_session):
        seg = seeded_session.query(ProcessSegment).first()
        assert seg.duration_ms > 0

    def test_segments_span_multiple_days(self, seeded_session):
        dates = set(
            seg.start_time.date()
            for seg in seeded_session.query(ProcessSegment).all()
        )
        assert len(dates) >= 3  # at least 3 days of data


class TestSeedWorktimeAndTherblig:
    def test_worktime_records_created(self, seeded_session):
        count = seeded_session.query(WorktimeRecord).count()
        assert count >= 50

    def test_worktime_has_efficiency(self, seeded_session):
        wr = seeded_session.query(WorktimeRecord).first()
        assert 0 <= wr.efficiency <= 1

    def test_therblig_details_created(self, seeded_session):
        count = seeded_session.query(TherbligDetail).count()
        assert count >= 100

    def test_therblig_links_to_worktime(self, seeded_session):
        td = seeded_session.query(TherbligDetail).first()
        wr = seeded_session.get(WorktimeRecord, td.worktime_record_id)
        assert wr is not None

    def test_segments_linked_to_worktime(self, seeded_session):
        """At least some segments should be linked to worktime records."""
        linked = seeded_session.query(ProcessSegment).filter(
            ProcessSegment.worktime_record_id.isnot(None)
        ).count()
        total = seeded_session.query(ProcessSegment).count()
        if total > 0:
            assert linked > total * 0.5  # majority linked

    def test_waste_therbligs_marked(self, seeded_session):
        waste = seeded_session.query(TherbligDetail).filter(
            TherbligDetail.is_waste.is_(True)
        ).count()
        total = seeded_session.query(TherbligDetail).count()
        if total > 0:
            # Should have some waste therbligs (delay, inspect)
            assert waste > 0
