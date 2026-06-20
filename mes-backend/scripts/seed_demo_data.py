"""Demo data seeding script for MES backend (T5-10).

Populates all database tables with realistic manufacturing data for
competition demonstration purposes.

Usage:
    python -m scripts.seed_demo_data

Or from project root:
    python mes-backend/scripts/seed_demo_data.py

The script is idempotent: it checks for existing data and skips
tables that already have records.
"""

from __future__ import annotations

import logging
import os
import sys
import random
import argparse
from datetime import datetime, timedelta, timezone
from decimal import Decimal

# Ensure project root is on path
_project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _project_root not in sys.path:
    sys.path.insert(0, _project_root)

from app.models.database import (
        get_session,
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

logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")
logger = logging.getLogger(__name__)

random.seed(42)

# ── Constants ────────────────────────────────────────────────────────────────

# ── CLI Arguments ────────────────────────────────────────────────────────────

parser = argparse.ArgumentParser(description="Seed demo data for MES backend")
parser.add_argument(
    "--tables",
    nargs="*",
    default=None,
    help="Tables to seed: customers orders equipment inventory segments worktime_therblig (default: all)",
)
args = parser.parse_args()

# ─────────────────────────────────────────────────────────────────────────────

STATIONS = ["WS-01", "WS-02", "WS-03", "WS-04", "WS-05"]
ACTIONS = [
    ("reach", "RE", 12, False),
    ("grasp", "G", 5, False),
    ("move", "TL", 11, False),
    ("position", "P", 6, False),
    ("assemble", "A", 9, False),
    ("use", "U", 8, False),
    ("disassemble", "DA", 10, False),
    ("inspect", "I", 9, True),
    ("wait", "AD", 7, True),
    ("idle", "UD", 10, True),
    ("release", "RL", 3, False),
    ("transport", "TE", 15, False),
]
SHIFTS = ["morning", "afternoon", "night"]
CAMERAS = [f"cam_{s.lower()}" for s in STATIONS]

CUSTOMERS = [
    ("Huawei Technologies", "Zhang Wei", "138-0001-0001", "Shenzhen", "vip", "A", 50),
    ("BYD Auto", "Li Na", "139-0002-0002", "Xi'an", "vip", "A", 45),
    ("Foxconn Electronics", "Wang Jun", "137-0003-0003", "Zhengzhou", "normal", "B", 40),
    ("Midea Group", "Chen Fang", "136-0004-0004", "Foshan", "normal", "B", 35),
    ("Gree Electric", "Zhao Qiang", "135-0005-0005", "Zhuhai", "normal", "B", 30),
    ("CATL", "Liu Yang", "134-0006-0006", "Ningde", "vip", "A", 55),
    ("Luxshare Precision", "Sun Li", "133-0007-0007", "Dongguan", "normal", "C", 25),
    ("Goertek Inc", "Zhou Ming", "132-0008-0008", "Weifang", "normal", "B", 30),
]

PRODUCTS = [
    ("PCB Assembly A1", "FR4 1.6mm 4-layer"),
    ("PCB Assembly B2", "FR4 1.0mm 2-layer"),
    ("Connector Module C3", "Type-C 24pin"),
    ("Sensor Housing D4", "Aluminum alloy"),
    ("Display Bracket E5", "Stainless steel 304"),
    ("Battery Pack F6", "LiFePO4 48V20Ah"),
    ("Control Board G7", "CEM-1 1.6mm"),
    ("Power Module H8", "Ceramic substrate"),
]

EQUIPMENT_DATA = [
    ("Auto Soldering Station", "Yamaha YSM-20R", "SMT Workshop A", "running", 85.2),
    ("Pick & Place Machine", "Fuji NXT-III", "SMT Workshop A", "running", 92.1),
    ("Reflow Oven", "Heller 1913 MK5", "SMT Workshop B", "maintenance", 78.5),
    ("AOI Inspector", "Omron VT-S1080", "QA Workshop", "running", 90.3),
    ("Manual Assembly Bench", "Custom WS-05", "Assembly Line 1", "running", 72.8),
    ("Function Test Rig", "Chroma 29082", "Test Workshop", "idle", 0.0),
    ("Packaging Machine", "Bosch CUC 3001", "Packaging Line", "running", 88.6),
    ("Laser Marker", "Keyence MD-X5000", "Marking Station", "running", 94.2),
]

INVENTORY_ITEMS = [
    ("RES-001", "SMD Resistor 10K", "0402 10Kohm 1%", "component", "pcs", 150000, 20000, "A01-01", "WH-A"),
    ("CAP-001", "MLCC Capacitor 100nF", "0402 100nF 16V", "component", "pcs", 80000, 15000, "A01-02", "WH-A"),
    ("IC-001", "MCU STM32F103", "LQFP-64", "component", "pcs", 5000, 1000, "A02-01", "WH-A"),
    ("PCB-001", "Bare PCB 4-Layer", "FR4 1.6mm 200x150mm", "material", "pcs", 3000, 500, "B01-01", "WH-B"),
    ("CTR-001", "Type-C Connector 24P", "USB-C Female", "component", "pcs", 20000, 3000, "A03-01", "WH-A"),
    ("WIR-001", "AWG24 Hookup Wire", "Red 22AWG 100m/roll", "material", "roll", 50, 10, "B02-01", "WH-B"),
    ("SLD-001", "Lead-Free Solder Paste", "SAC305 Type4 500g", "material", "jar", 30, 5, "B03-01", "WH-B"),
    ("PCK-001", "ESD Bag 200x300mm", "Anti-static PE bag", "packaging", "pcs", 10000, 2000, "C01-01", "WH-C"),
]

# ── Seeding Functions ─────────────────────────────────────────────────────────


def _count(session, model) -> int:
    return session.query(model).count()


def seed_customers(session) -> int:
    if _count(session, Customer) > 0:
        logger.info("Customers already exist, skipping")
        return 0

    now = datetime.now(timezone.utc)
    for name, contact, phone, city, ctype, level, orders_count in CUSTOMERS:
        c = Customer(
            name=name,
            contact=contact,
            phone=phone,
            city=city,
            customer_type=ctype,
            level=level,
            status="active",
            remark=f"Demo customer - {orders_count} historical orders",
            created_at=now - timedelta(days=random.randint(30, 365)),
        )
        session.add(c)
    session.commit()
    count = _count(session, Customer)
    logger.info("Seeded %d customers", count)
    return count


def seed_orders(session) -> int:
    if _count(session, Order) > 0:
        logger.info("Orders already exist, skipping")
        return 0

    customers = session.query(Customer).all()
    if not customers:
        logger.warning("No customers found, skipping orders")
        return 0

    now = datetime.now(timezone.utc)
    order_idx = 0
    statuses = ["pending", "in_progress", "completed", "completed", "completed", "completed"]
    priorities = ["urgent", "high", "normal", "normal", "normal", "low"]

    for customer in customers:
        n_orders = random.randint(3, 8)
        for _ in range(n_orders):
            product_idx = order_idx % len(PRODUCTS)
            product_name, spec = PRODUCTS[product_idx]

            status = random.choice(statuses)
            qty = random.randint(100, 5000)
            completed = qty if status == "completed" else random.randint(0, qty - 1) if status == "in_progress" else 0

            due_offset = random.randint(-30, 60)
            due_date = (now + timedelta(days=due_offset)).strftime("%Y-%m-%d")

            o = Order(
                code=f"PO-2026-{order_idx + 1:04d}",
                product=product_name,
                spec=spec,
                customer_id=customer.id,
                quantity=qty,
                completed_qty=completed,
                due_date=due_date,
                priority=random.choice(priorities),
                status=status,
                remark="Demo order" if order_idx % 5 == 0 else None,
                created_at=now - timedelta(days=random.randint(1, 90)),
            )
            session.add(o)
            order_idx += 1

    session.commit()
    count = _count(session, Order)
    logger.info("Seeded %d orders", count)
    return count


def seed_equipment(session) -> int:
    if _count(session, Equipment) > 0:
        logger.info("Equipment already exist, skipping")
        return 0

    now = datetime.now(timezone.utc)
    for name, model, workshop, status, oee in EQUIPMENT_DATA:
        util = oee * random.uniform(0.85, 1.05) if oee > 0 else 0
        faults = random.randint(0, 8) if status != "idle" else 0
        mtbf = random.uniform(120, 800) if faults > 0 else 0

        e = Equipment(
            name=name,
            model=model,
            workshop=workshop,
            status=status,
            oee=min(oee, 99.9),
            utilization=min(util, 99.9),
            fault_count=faults,
            mtbf_hours=round(mtbf, 1),
            today_util_pct=min(util * random.uniform(0.9, 1.1), 99.9),
            next_maintenance=(now + timedelta(days=random.randint(3, 30))).strftime("%Y-%m-%d"),
            created_at=now - timedelta(days=random.randint(60, 365)),
        )
        session.add(e)
    session.commit()
    count = _count(session, Equipment)
    logger.info("Seeded %d equipment records", count)
    return count


def seed_inventory(session) -> int:
    if _count(session, InventoryItem) > 0:
        logger.info("Inventory items already exist, skipping")
        return 0

    now = datetime.now(timezone.utc)
    for code, name, spec, category, unit, stock, safe_stock, location, warehouse in INVENTORY_ITEMS:
        item = InventoryItem(
            code=code,
            name=name,
            spec=spec,
            category=category,
            unit=unit,
            stock=float(stock),
            safe_stock=float(safe_stock),
            location=location,
            warehouse=warehouse,
            price=Decimal(str(round(random.uniform(0.01, 50.0), 2))),
            last_inbound=now - timedelta(days=random.randint(0, 30)),
            created_at=now - timedelta(days=random.randint(30, 365)),
        )
        session.add(item)
    session.commit()

    # Seed some inventory logs
    items = session.query(InventoryItem).all()
    for item in items:
        n_logs = random.randint(2, 6)
        for _ in range(n_logs):
            tx_type = random.choice(["inbound", "outbound"])
            qty = random.randint(10, 5000)
            log = InventoryLog(
                inventory_item_id=item.id,
                transaction_type=tx_type,
                quantity=float(qty),
                remark=f"Demo {tx_type} record",
                created_at=now - timedelta(days=random.randint(0, 30)),
            )
            session.add(log)
    session.commit()

    item_count = _count(session, InventoryItem)
    log_count = _count(session, InventoryLog)
    logger.info("Seeded %d inventory items, %d logs", item_count, log_count)
    return item_count


def seed_process_segments(session) -> int:
    if _count(session, ProcessSegment) > 0:
        logger.info("Process segments already exist, skipping")
        return 0

    now = datetime.now(timezone.utc)
    base_time = now - timedelta(days=7)

    # Generate ~2000 segments across 7 days, 3 shifts
    total = 0
    segment_id = 0
    worktime_records: list[WorktimeRecord] = []

    for day_offset in range(7):
        day_start = base_time + timedelta(days=day_offset)

        for shift_name in SHIFTS:
            if shift_name == "morning":
                shift_start = day_start.replace(hour=8, minute=0, second=0, microsecond=0)
            elif shift_name == "afternoon":
                shift_start = day_start.replace(hour=16, minute=0, second=0, microsecond=0)
            else:
                # Night shift starts at midnight of the next day (day_offset+1)
                shift_start = (base_time + timedelta(days=day_offset + 1)).replace(
                    hour=0, minute=0, second=0, microsecond=0
                )

            # Each shift has some action sequences per station
            for station in STATIONS:
                camera = f"cam_{station.lower().replace('-', '_')}"
                current_time = shift_start
                n_sequences = random.randint(5, 12)

                for _ in range(n_sequences):
                    # Each sequence = a complete operation cycle
                    n_actions = random.randint(4, 10)
                    cycle_actions = random.sample(ACTIONS, min(n_actions, len(ACTIONS)))

                    # Create a worktime record for this cycle
                    operation_name = f"{station}_{shift_name}_cycle_{segment_id}"
                    total_cycle_ms = 0

                    for action_name, symbol, mod_val, is_waste in cycle_actions:
                        # Duration with realistic variation
                        base_ms = mod_val * 129  # 1 MOD = 129ms
                        variation = random.uniform(-0.2, 0.3)
                        duration_ms = max(50, base_ms * (1 + variation))

                        end_time = current_time + timedelta(milliseconds=duration_ms)
                        confidence = random.uniform(0.7, 0.99)

                        seg = ProcessSegment(
                            camera_id=camera,
                            station_id=station,
                            line='组装产线',
                            action=action_name,
                            therblig_symbol=symbol,
                            start_time=current_time,
                            end_time=end_time,
                            duration_ms=round(duration_ms, 1),
                            confidence=round(confidence, 3),
                            shift=shift_name,
                        )
                        session.add(seg)
                        total_cycle_ms += duration_ms
                        current_time = end_time + timedelta(milliseconds=random.uniform(10, 100))
                        segment_id += 1

                    # Create worktime record
                    standard_ms = sum(a[2] * 129 for a in cycle_actions)
                    efficiency = standard_ms / total_cycle_ms if total_cycle_ms > 0 else 0
                    mod_total = total_cycle_ms / 129.0

                    wr = WorktimeRecord(
                        operation=operation_name,
                        station_id=station,
                        actual_ms=round(total_cycle_ms, 1),
                        standard_ms=round(standard_ms, 1),
                        efficiency=round(min(efficiency, 1.0), 3),
                        mod_total=round(mod_total, 1),
                        shift=shift_name,
                    )
                    session.add(wr)
                    worktime_records.append((wr, station, shift_name, cycle_actions, total_cycle_ms))

                    total += len(cycle_actions)

    session.commit()
    logger.info("Seeded %d process segments", total)
    return total


def seed_worktime_and_therblig(session) -> int:
    """Link segments to worktime records and create therblig details."""
    segments = session.query(ProcessSegment).all()
    if not segments:
        logger.info("No segments to link")
        return 0

    worktime_records = session.query(WorktimeRecord).all()
    if not worktime_records:
        logger.info("No worktime records to populate")
        return 0

    # Assign segments to the nearest worktime record by station and shift
    from collections import defaultdict

    wr_by_station_shift = defaultdict(list)
    for wr in worktime_records:
        wr_by_station_shift[(wr.station_id, wr.shift)].append(wr)

    linked = 0
    for seg in segments:
        key = (seg.station_id, seg.shift)
        records = wr_by_station_shift.get(key, [])
        if records:
            # Find the record whose created_at is closest to segment start
            best = min(records, key=lambda r: abs((r.created_at - seg.start_time).total_seconds()))
            seg.worktime_record_id = best.id
            linked += 1

    session.commit()

    # Create therblig details for each worktime record
    total_details = 0
    for wr in worktime_records:
        wr_segments = session.query(ProcessSegment).filter(
            ProcessSegment.worktime_record_id == wr.id
        ).all()

        # Group segments by therblig symbol
        symbol_groups = defaultdict(list)
        for seg in wr_segments:
            sym = seg.therblig_symbol or "UD"
            symbol_groups[sym].append(seg)

        for symbol, segs in symbol_groups.items():
            total_ms = sum(s.duration_ms for s in segs)
            mod_val = total_ms / 129.0
            pct = (total_ms / wr.actual_ms * 100) if wr.actual_ms > 0 else 0

            # Determine if waste
            is_waste = symbol in ("AD", "UD", "I")

            td = TherbligDetail(
                worktime_record_id=wr.id,
                symbol=symbol,
                name=_therblig_name(symbol),
                mod=round(mod_val, 1),
                actual_ms=round(total_ms, 1),
                pct=round(pct, 1),
                is_waste=is_waste,
            )
            session.add(td)
            total_details += 1

    session.commit()
    logger.info("Linked %d segments, created %d therblig details", linked, total_details)
    return total_details


def _therblig_name(symbol: str) -> str:
    """Map therblig symbol to Chinese name."""
    names = {
        "RE": "Reach", "G": "Grasp", "TL": "Transport Load",
        "P": "Position", "A": "Assemble", "U": "Use",
        "DA": "Disassemble", "I": "Inspect", "AD": "Avoidable Delay",
        "UD": "Unavoidable Delay", "RL": "Release", "TE": "Transport Empty",
        "H": "Hold", "R": "Rest", "PL": "Pre-Position", "PP": "Plan",
        "F": "Search", "ST": "Select", "EF": "Find",
    }
    return names.get(symbol, symbol)


def main():
    """Main entry point for demo data seeding."""
    logger.info("=" * 60)
    logger.info("MES Demo Data Seeding Script (T5-10)")
    logger.info("=" * 60)

    selected = args.tables  # None = seed all
    if selected:
        logger.info("Selected tables: %s", ", ".join(selected))
    else:
        logger.info("Seeding ALL tables")

    # Use test database for seeding
    db_url = os.environ.get("MES_DB_URL", "sqlite:///data/mes.db")
    logger.info("Database: %s", db_url)

    init_db(db_url)
    session = get_session(db_url)

    try:
        if not selected or "customers" in selected:
            c_customers = seed_customers(session)
        if not selected or "orders" in selected:
            c_orders = seed_orders(session)
        if not selected or "equipment" in selected:
            c_equipment = seed_equipment(session)
        if not selected or "inventory" in selected:
            c_inventory = seed_inventory(session)
        if not selected or "segments" in selected:
            c_segments = seed_process_segments(session)
        if not selected or "worktime_therblig" in selected:
            c_therblig = seed_worktime_and_therblig(session)

        logger.info("=" * 60)
        logger.info("Seeding complete")
        if not selected or "customers" in selected:
            logger.info("  Customers:  %d", _count(session, Customer))
        if not selected or "orders" in selected:
            logger.info("  Orders:     %d", _count(session, Order))
        if not selected or "equipment" in selected:
            logger.info("  Equipment:  %d", _count(session, Equipment))
        if not selected or "inventory" in selected:
            logger.info("  Inventory:  %d items, %d logs", _count(session, InventoryItem), _count(session, InventoryLog))
        if not selected or "segments" in selected:
            logger.info("  Segments:   %d", _count(session, ProcessSegment))
        if not selected or "worktime_therblig" in selected:
            logger.info("  Worktime:   %d", _count(session, WorktimeRecord))
            logger.info("  Therblig:   %d", _count(session, TherbligDetail))
        logger.info("=" * 60)

    finally:
        session.close()


if __name__ == "__main__":
    main()
