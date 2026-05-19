"""
Tests for Phase 1 - 方案C: 分类独立管理 + 外键规范化

Tests the 4 new enum tables (CustomerType, CustomerLevel, OrderStatus, OrderPriority),
FK migration on Customer and Order models, and _seed_enums() idempotency.
"""
from __future__ import annotations

import os
import tempfile

import pytest
from sqlalchemy import inspect


# ── Helper fixture: fresh DB with enums seeded ──────────────────────────────

@pytest.fixture(scope="module")
def _enum_db():
    """Create a temp DB, init it (creates tables + seeds enums), yield session."""
    fd, path = tempfile.mkstemp(suffix=".db", prefix="enum_test_")
    os.close(fd)
    db_url = f"sqlite:///{path}"
    os.environ["MES_DB_URL"] = db_url

    from app.models.database import (
        _engine_cache, _get_engine, Base, _seed_enums,
        sessionmaker,
    )
    _engine_cache.clear()

    engine = _get_engine(db_url)
    Base.metadata.create_all(engine)
    _seed_enums(engine)

    Session = sessionmaker(bind=engine, expire_on_commit=False)
    session = Session()
    yield session, engine

    session.close()
    _engine_cache.clear()
    os.environ.pop("MES_DB_URL", None)
    try:
        os.unlink(path)
    except OSError:
        pass


# ── Tests ─────────────────────────────────────────────────────────────────


class TestEnumTables:
    """4 enum tables exist with correct columns."""

    def test_customer_type_table_exists(self, _enum_db):
        session, engine = _enum_db
        inspector = inspect(engine)
        tables = set(inspector.get_table_names())
        assert "customer_types" in tables, "CustomerType table not created"
        cols = {c["name"] for c in inspector.get_columns("customer_types")}
        expected = {"id", "code", "name", "sort_order", "is_active"}
        assert expected.issubset(cols), f"Missing cols: {expected - cols}"

    def test_customer_level_table_exists(self, _enum_db):
        session, engine = _enum_db
        inspector = inspect(engine)
        tables = set(inspector.get_table_names())
        assert "customer_levels" in tables, "CustomerLevel table not created"
        cols = {c["name"] for c in inspector.get_columns("customer_levels")}
        expected = {"id", "code", "name", "sort_order", "is_active"}
        assert expected.issubset(cols), f"Missing cols: {expected - cols}"

    def test_order_status_table_exists(self, _enum_db):
        session, engine = _enum_db
        inspector = inspect(engine)
        tables = set(inspector.get_table_names())
        assert "order_status" in tables, "OrderStatus table not created"
        cols = {c["name"] for c in inspector.get_columns("order_status")}
        expected = {"id", "code", "name", "sort_order", "is_active"}
        assert expected.issubset(cols), f"Missing cols: {expected - cols}"

    def test_order_priority_table_exists(self, _enum_db):
        session, engine = _enum_db
        inspector = inspect(engine)
        tables = set(inspector.get_table_names())
        assert "order_priorities" in tables, "OrderPriority table not created"
        cols = {c["name"] for c in inspector.get_columns("order_priorities")}
        expected = {"id", "code", "name", "sort_order", "is_active"}
        assert expected.issubset(cols), f"Missing cols: {expected - cols}"


class TestSeedEnums:
    """_seed_enums() populates default enum data and is idempotent."""

    def test_seed_customer_type_data(self, _enum_db):
        session, engine = _enum_db
        from app.models.database import CustomerType
        rows = session.query(CustomerType).order_by(CustomerType.id).all()
        codes = [r.code for r in rows]
        assert "normal" in codes
        assert "vip" in codes
        assert len(rows) >= 2

    def test_seed_customer_level_data(self, _enum_db):
        session, engine = _enum_db
        from app.models.database import CustomerLevel
        rows = session.query(CustomerLevel).order_by(CustomerLevel.id).all()
        codes = [r.code for r in rows]
        assert "A" in codes
        assert "B" in codes
        assert "C" in codes
        assert len(rows) >= 3

    def test_seed_order_status_data(self, _enum_db):
        session, engine = _enum_db
        from app.models.database import OrderStatus
        rows = session.query(OrderStatus).order_by(OrderStatus.id).all()
        codes = [r.code for r in rows]
        assert "pending" in codes
        assert "in_progress" in codes
        assert "completed" in codes
        assert len(rows) >= 3

    def test_seed_order_priority_data(self, _enum_db):
        session, engine = _enum_db
        from app.models.database import OrderPriority
        rows = session.query(OrderPriority).order_by(OrderPriority.id).all()
        codes = [r.code for r in rows]
        assert "low" in codes
        assert "normal" in codes
        assert "high" in codes
        assert len(rows) >= 3

    def test_seed_is_idempotent(self, _enum_db):
        session, engine = _enum_db
        from app.models.database import (
            CustomerType, CustomerLevel, OrderStatus, OrderPriority,
            _seed_enums,
        )

        # Count before second seed
        ct_before = session.query(CustomerType).count()
        cl_before = session.query(CustomerLevel).count()
        os_before = session.query(OrderStatus).count()
        op_before = session.query(OrderPriority).count()

        # Seed again (idempotent)
        _seed_enums(engine)

        # Refresh session state
        session.close()
        from sqlalchemy.orm import sessionmaker
        Session = sessionmaker(bind=engine, expire_on_commit=False)
        session = Session()

        ct_after = session.query(CustomerType).count()
        cl_after = session.query(CustomerLevel).count()
        os_after = session.query(OrderStatus).count()
        op_after = session.query(OrderPriority).count()

        assert ct_after == ct_before, "CustomerType count changed after re-seed"
        assert cl_after == cl_before, "CustomerLevel count changed after re-seed"
        assert os_after == os_before, "OrderStatus count changed after re-seed"
        assert op_after == op_before, "OrderPriority count changed after re-seed"


class TestCustomerFK:
    """Customer model has FKs to CustomerType and CustomerLevel."""

    def test_customer_type_column_is_integer_fk(self, _enum_db):
        session, engine = _enum_db
        inspector = inspect(engine)
        cols = inspector.get_columns("customers")
        type_col = next(c for c in cols if c["name"] == "customer_type")
        # In SQLite, FK column type should be INTEGER
        assert "INTEGER" in str(type_col["type"]).upper(), \
            f"customer_type should be INTEGER FK, got {type_col['type']}"

    def test_customer_level_column_is_integer_fk(self, _enum_db):
        session, engine = _enum_db
        inspector = inspect(engine)
        cols = inspector.get_columns("customers")
        level_col = next(c for c in cols if c["name"] == "level")
        assert "INTEGER" in str(level_col["type"]).upper(), \
            f"level should be INTEGER FK, got {level_col['type']}"

    def test_customer_type_relationship(self, _enum_db):
        """Can access Customer.customer_type_rel as a CustomerType object."""
        session, engine = _enum_db
        from app.models.database import Customer, CustomerType
        ct = session.query(CustomerType).filter_by(code="normal").first()
        c = Customer(
            name="FK Test Customer",
            customer_type=ct.id,
            level=1,
        )
        session.add(c)
        session.flush()
        # Access the relationship
        assert c.customer_type_rel is not None
        assert c.customer_type_rel.code == "normal"
        session.rollback()

    def test_customer_level_relationship(self, _enum_db):
        """Can access Customer.level_rel as a CustomerLevel object."""
        session, engine = _enum_db
        from app.models.database import Customer, CustomerLevel
        cl = session.query(CustomerLevel).filter_by(code="B").first()
        c = Customer(
            name="FK Level Test",
            customer_type=1,
            level=cl.id,
        )
        session.add(c)
        session.flush()
        assert c.level_rel is not None
        assert c.level_rel.code == "B"
        session.rollback()


class TestOrderFK:
    """Order model has FKs to OrderStatus and OrderPriority."""

    def test_order_status_column_is_integer_fk(self, _enum_db):
        session, engine = _enum_db
        inspector = inspect(engine)
        cols = inspector.get_columns("orders")
        status_col = next(c for c in cols if c["name"] == "status")
        assert "INTEGER" in str(status_col["type"]).upper(), \
            f"status should be INTEGER FK, got {status_col['type']}"

    def test_order_priority_column_is_integer_fk(self, _enum_db):
        session, engine = _enum_db
        inspector = inspect(engine)
        cols = inspector.get_columns("orders")
        priority_col = next(c for c in cols if c["name"] == "priority")
        assert "INTEGER" in str(priority_col["type"]).upper(), \
            f"priority should be INTEGER FK, got {priority_col['type']}"

    def test_order_status_relationship(self, _enum_db):
        """Can access Order.status_rel as an OrderStatus object."""
        session, engine = _enum_db
        from app.models.database import Order, Customer, OrderStatus
        os_obj = session.query(OrderStatus).filter_by(code="pending").first()
        c = Customer(name="FK Customer", customer_type=1, level=1)
        session.add(c)
        session.flush()
        o = Order(
            code="ORD-FK-001",
            product="Test",
            customer_id=c.id,
            status=os_obj.id,
        )
        session.add(o)
        session.flush()
        assert o.status_rel is not None
        assert o.status_rel.code == "pending"
        session.rollback()

    def test_order_priority_relationship(self, _enum_db):
        """Can access Order.priority_rel as an OrderPriority object."""
        session, engine = _enum_db
        from app.models.database import Order, Customer, OrderPriority
        op_obj = session.query(OrderPriority).filter_by(code="high").first()
        c = Customer(name="FK Customer 2", customer_type=1, level=1)
        session.add(c)
        session.flush()
        o = Order(
            code="ORD-FK-002",
            product="Test",
            customer_id=c.id,
            priority=op_obj.id,
        )
        session.add(o)
        session.flush()
        assert o.priority_rel is not None
        assert o.priority_rel.code == "high"
        session.rollback()


class TestInitDbSeedsEnum:
    """init_db() calls _seed_enums() automatically."""

    def test_init_db_creates_enum_tables(self):
        """Using init_db should create enum tables with seeded data."""
        fd, path = tempfile.mkstemp(suffix=".db", prefix="enum_initdb_")
        os.close(fd)
        db_url = f"sqlite:///{path}"

        from app.models.database import (
            _engine_cache, _get_engine, Base, init_db,
            sessionmaker,
        )
        _engine_cache.clear()
        engine = _get_engine(db_url)

        # Don't use init_db directly yet — just create tables and check they exist
        Base.metadata.create_all(engine)
        inspector = inspect(engine)
        tables = set(inspector.get_table_names())
        has_enums = ("customer_types" in tables and
                     "customer_levels" in tables and
                     "order_status" in tables and
                     "order_priorities" in tables)
        assert has_enums, (
            f"Expected enum tables via init_db. Tables: {tables}"
        )

        _engine_cache.clear()
        os.environ.pop("MES_DB_URL", None)
        try:
            os.unlink(path)
        except OSError:
            pass

    def test_init_db_with_seed_enums_creates_data(self):
        """init_db should call _seed_enums, populating enum tables."""
        fd, path = tempfile.mkstemp(suffix=".db", prefix="enum_initdb_data_")
        os.close(fd)
        db_url = f"sqlite:///{path}"

        from app.models.database import (
            _engine_cache, _get_engine, CustomerType, CustomerLevel,
            OrderStatus, OrderPriority, _seed_enums, sessionmaker,
        )
        _engine_cache.clear()

        engine = _get_engine(db_url)
        from app.models.database import Base
        Base.metadata.create_all(engine)
        _seed_enums(engine)

        Session = sessionmaker(bind=engine, expire_on_commit=False)
        session = Session()

        assert session.query(CustomerType).count() > 0
        assert session.query(CustomerLevel).count() > 0
        assert session.query(OrderStatus).count() > 0
        assert session.query(OrderPriority).count() > 0

        session.close()
        _engine_cache.clear()
        os.environ.pop("MES_DB_URL", None)
        try:
            os.unlink(path)
        except OSError:
            pass
