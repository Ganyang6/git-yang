#!/usr/bin/env python
"""Seed business data for development and testing.

Creates sample customers, orders, equipment, and inventory items
in the SQLite database.

Usage:
    python scripts/seed_business_data.py
    python -m scripts.seed_business_data
"""

from __future__ import annotations

import logging
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

# Ensure project root is on sys.path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.models.database import init_db, get_session, Customer, Order, Equipment, InventoryItem

logging.basicConfig(level=logging.INFO, format="%(message)s")
logger = logging.getLogger(__name__)


def seed_customers(session) -> list[Customer]:
    """Create sample customers."""
    data = [
        Customer(name="Shenzhen Electronics Co.", contact="Zhang Wei", phone="0755-12345678",
                  city="Shenzhen", customer_type="strategic", level="SA", status="active"),
        Customer(name="Guangzhou Auto Parts Ltd.", contact="Li Ming", phone="020-87654321",
                  city="Guangzhou", customer_type="normal", level="A", status="active"),
        Customer(name="Dongguan Hardware Inc.", contact="Wang Fang", phone="0769-22334455",
                  city="Dongguan", customer_type="normal", level="B", status="active"),
        Customer(name="Foshan Ceramics Co.", contact="Chen Jian", phone="0757-99887766",
                  city="Foshan", customer_type="normal", level="B", status="active"),
        Customer(name="Zhuhai Tech Corp.", contact="Liu Yang", phone="0756-11223344",
                  city="Zhuhai", customer_type="strategic", level="SA", status="active"),
    ]
    for c in data:
        session.add(c)
    session.commit()
    for c in data:
        session.refresh(c)
    logger.info("Created %d customers", len(data))
    return data


def seed_orders(session, customers: list[Customer]) -> list[Order]:
    """Create sample production orders."""
    products = [
        ("PCB Board A", "FR4 1.6mm"),
        ("PCB Board B", "FR4 0.8mm"),
        ("Assembly Module X", "Standard"),
        ("Connector Housing", "ABS Plastic"),
        ("LED Driver Board", "Aluminum"),
    ]
    statuses = ["completed", "completed", "in_progress", "in_progress", "pending", "pending", "pending"]
    priorities = ["high", "normal", "normal", "normal", "low", "normal", "high"]

    now = datetime.now(timezone.utc)
    orders = []
    for i, (product, spec) in enumerate(products * 2):
        customer = customers[i % len(customers)]
        due_date = (now + timedelta(days=7 + i * 3)).strftime("%Y-%m-%d")
        order = Order(
            code=f"PO-{now.strftime('%Y%m%d')}-{i+1:04d}",
            product=product,
            spec=spec,
            customer_id=customer.id,
            quantity=100 + i * 50,
            completed_qty=(100 + i * 50) if i < 2 else (50 + i * 20) if i < 4 else 0,
            due_date=due_date,
            priority=priorities[i % len(priorities)],
            status=statuses[i % len(statuses)],
            remark="",
        )
        session.add(order)
        orders.append(order)
    session.commit()
    for o in orders:
        session.refresh(o)
    logger.info("Created %d orders", len(orders))
    return orders


def seed_equipment(session) -> list[Equipment]:
    """Create sample equipment/workstations."""
    data = [
        Equipment(name="Station 01 - SMT", model="Yamaha YSM20", workshop="Line A",
                   status="running", oee=0.88, utilization=0.92, fault_count=2,
                   mtbf_hours=168.5, today_util_pct=0.91,
                   next_maintenance=(datetime.now(timezone.utc) + timedelta(days=15)).strftime("%Y-%m-%d")),
        Equipment(name="Station 02 - Solder", model="JT Solder 3000", workshop="Line A",
                   status="running", oee=0.82, utilization=0.87, fault_count=5,
                   mtbf_hours=120.0, today_util_pct=0.85,
                   next_maintenance=(datetime.now(timezone.utc) + timedelta(days=8)).strftime("%Y-%m-%d")),
        Equipment(name="Station 03 - Assembly", model="FANUC LR-200iC", workshop="Line A",
                   status="running", oee=0.90, utilization=0.95, fault_count=1,
                   mtbf_hours=240.0, today_util_pct=0.93,
                   next_maintenance=(datetime.now(timezone.utc) + timedelta(days=30)).strftime("%Y-%m-%d")),
        Equipment(name="Station 04 - Inspection", model="Keyence CV-X420F", workshop="Line A",
                   status="idle", oee=0.78, utilization=0.65, fault_count=0,
                   mtbf_hours=999.0, today_util_pct=0.60,
                   next_maintenance=(datetime.now(timezone.utc) + timedelta(days=45)).strftime("%Y-%m-%d")),
        Equipment(name="Station 05 - Packaging", model="AutoPack AP-100", workshop="Line A",
                   status="maintenance", oee=0.70, utilization=0.50, fault_count=8,
                   mtbf_hours=72.0, today_util_pct=0.0,
                   next_maintenance=(datetime.now(timezone.utc) + timedelta(days=1)).strftime("%Y-%m-%d")),
    ]
    for e in data:
        session.add(e)
    session.commit()
    for e in data:
        session.refresh(e)
    logger.info("Created %d equipment entries", len(data))
    return data


def seed_inventory(session) -> list[InventoryItem]:
    """Create sample inventory items."""
    data = [
        InventoryItem(code="RM-001", name="FR4 Copper Clad", spec="1.6mm Double",
                       category="material", unit="sheet", stock=500.0, safe_stock=100.0,
                       location="WH-A01", warehouse="Warehouse A", price=25.50),
        InventoryItem(code="RM-002", name="Solder Paste", spec="Sn96.5/Ag3.0/Cu0.5",
                       category="material", unit="kg", stock=12.0, safe_stock=5.0,
                       location="WH-A02", warehouse="Warehouse A", price=180.00),
        InventoryItem(code="RM-003", name="IC Chip STM32F103", spec="LQFP-48",
                       category="component", unit="pcs", stock=15000.0, safe_stock=3000.0,
                       location="WH-B01", warehouse="Warehouse B", price=8.50),
        InventoryItem(code="RM-004", name="0402 Resistor 10k", spec="0402 1%",
                       category="component", unit="pcs", stock=85000.0, safe_stock=20000.0,
                       location="WH-B02", warehouse="Warehouse B", price=0.005),
        InventoryItem(code="RM-005", name="ESD Wrist Strap", spec="Adjustable",
                       category="consumable", unit="pcs", stock=30.0, safe_stock=10.0,
                       location="WH-C01", warehouse="Warehouse C", price=3.20),
        InventoryItem(code="RM-006", name="Flux Pen", spec="No-clean",
                       category="consumable", unit="pcs", stock=8.0, safe_stock=5.0,
                       location="WH-C02", warehouse="Warehouse C", price=12.00),
    ]
    for item in data:
        session.add(item)
    session.commit()
    for item in data:
        session.refresh(item)
    logger.info("Created %d inventory items", len(data))
    return data


def main() -> None:
    """Run all seed functions."""
    logger.info("Initializing database...")
    init_db(echo=False)
    session = get_session()

    try:
        customers = seed_customers(session)
        orders = seed_orders(session, customers)
        equipment = seed_equipment(session)
        inventory = seed_inventory(session)

        logger.info("--- Seed Summary ---")
        logger.info("Customers:  %d", len(customers))
        logger.info("Orders:     %d", len(orders))
        logger.info("Equipment:  %d", len(equipment))
        logger.info("Inventory:  %d", len(inventory))
        logger.info("Seed complete.")
    finally:
        session.close()


if __name__ == "__main__":
    main()
