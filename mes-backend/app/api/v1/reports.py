"""
Report analysis API routes.

Endpoints:
  GET /api/reports/kpi           - report KPI metrics
  GET /api/reports/monthly-output - monthly output trend
  GET /api/reports/product-mix    - product category distribution
  GET /api/reports/top-customers  - top customer ranking
  GET /api/reports/worktime/pdf   - worktime analysis PDF export
  GET /api/reports/line-balance/pdf - line balance PDF export
"""

from __future__ import annotations

import logging
import re
import time
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import Response
from sqlalchemy import func
from sqlalchemy.orm import Session

from app.core.enums import OrderStatus
from app.models.database import get_session, Order, Customer
from app.models.schemas import ApiResponse
from app.api.deps import get_db_session, require_read_all

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/reports", tags=["reports"])




@router.get("/kpi")
def report_kpi(
    period: str = Query("month"),
    session: Session = Depends(get_db_session),
    _user: dict = Depends(require_read_all),
):
    """Get report KPI metrics.

    Computes from actual order data:
    - totalOutput: total completed quantity across orders
    - completionRate: ratio of completed orders to total orders
    - yieldRate: simulated (no defect data yet)
    - onTimeRate: ratio of orders completed before due date
    - oee: simulated (requires PLC data)
    - changes: simulated period-over-period change percentages
    """
    from datetime import datetime, timezone
    from sqlalchemy import case

    now = datetime.now(timezone.utc)
    now_str = now.strftime("%Y-%m-%d")

    # Aggregate all KPI metrics in 2 queries instead of 5.
    # Query 1: base counts and sums
    row = session.query(
        func.count(Order.id).label("total_orders"),
        func.sum(case((Order.status == OrderStatus.completed.value, 1), else_=0)).label("completed_orders"),
        func.sum(Order.completed_qty).label("total_output"),
        func.sum(Order.quantity).label("total_qty"),
    ).first()

    total_orders = int(row.total_orders or 0)
    completed_orders = int(row.completed_orders or 0)
    total_output = int(row.total_output or 0)
    total_qty = int(row.total_qty or 0)

    # Query 2: on-time count (completed with future due_date)
    on_time = session.query(func.count(Order.id)).filter(
        Order.status == OrderStatus.completed.value,
        Order.due_date != "",
        Order.due_date >= now_str,
    ).scalar() or 0

    completion_rate = (completed_orders / total_orders) if total_orders > 0 else 0.0
    on_time_rate = (on_time / completed_orders) if completed_orders > 0 else 0.0

    return ApiResponse(
        data={
            "totalOutput": int(total_output),
            "completionRate": round(completion_rate, 4),
            "yieldRate": None,  # TODO: requires defect tracking module
            "onTimeRate": round(on_time_rate, 4),
            "oee": None,  # TODO: requires PLC integration (availability * performance * quality)
            "changes": None,  # TODO: requires historical period comparison
        },
        timestamp=time.time(),
    )


@router.get("/monthly-output")
def monthly_output(
    months: int = Query(6, ge=1, le=12),
    session: Session = Depends(get_db_session),
    _user: dict = Depends(require_read_all),
):
    """Get monthly output trend for chart.

    Returns labels (month names) and values (output quantities).
    Uses a single GROUP BY query instead of N separate queries.
    """
    from datetime import datetime, timedelta, timezone

    now = datetime.now(timezone.utc)

    # Compute the earliest month start we need
    earliest = now - timedelta(days=(months - 1) * 30 + 30)
    month_start = earliest.replace(day=1, hour=0, minute=0, second=0, microsecond=0)

    # Single query: GROUP BY year-month
    rows = session.query(
        func.strftime("%Y-%m", Order.created_at).label("month"),
        func.sum(Order.completed_qty).label("total"),
    ).filter(
        Order.created_at >= month_start,
    ).group_by(
        func.strftime("%Y-%m", Order.created_at)
    ).all()

    # Build lookup dict
    monthly_map = {r.month: int(r.total or 0) for r in rows}

    # Generate labels and values in chronological order
    labels = []
    values = []
    for i in range(months):
        month_date = now - timedelta(days=(months - 1 - i) * 30)
        key = month_date.strftime("%Y-%m")
        labels.append(key)
        values.append(monthly_map.get(key, 0))

    return ApiResponse(
        data={"labels": labels, "values": values},
        timestamp=time.time(),
    )


@router.get("/product-mix")
def product_mix(
    session: Session = Depends(get_db_session),
    _user: dict = Depends(require_read_all),
):
    """Get product category distribution for pie chart.

    Groups orders by product name and returns quantity shares.
    """
    results = session.query(
        Order.product, func.sum(Order.quantity).label("total_qty")
    ).group_by(Order.product).order_by(func.sum(Order.quantity).desc()).limit(8).all()

    colors = [
        "#5470c6", "#91cc75", "#fac858", "#ee6666",
        "#73c0de", "#3ba272", "#fc8452", "#9a60b4",
    ]

    total = sum(r.total_qty for r in results) if results else 1
    items = [
        {
            "label": r.product,
            "value": round(float(r.total_qty), 1),
            "color": colors[i % len(colors)],
        }
        for i, r in enumerate(results)
    ]

    return ApiResponse(data=items, timestamp=time.time())


# ---------------------------------------------------------------------------
# PDF Export Endpoints (T5-03)
# ---------------------------------------------------------------------------


@router.get("/worktime/pdf")
def export_worktime_pdf(
    station_id: str = Query("all", description="Station ID"),
    period: str = Query("today", description="Analysis period"),
    _user: dict = Depends(require_read_all),
    session: Session = Depends(get_db_session),
):
    """Export worktime analysis as PDF.

    Generates a PDF report containing:
    - KPI summary (utilization, efficiency, balance rate)
    - Therblig distribution table
    - Operations summary
    - Station efficiency ranking
    """
    from app.models.database import ProcessSegment
    from app.services.pdf_generator import generate_worktime_pdf

    # Gather worktime data from database
    query = session.query(ProcessSegment)

    # Filter by station
    if station_id != "all":
        query = query.filter(ProcessSegment.station_id == station_id)

    segments = query.order_by(ProcessSegment.start_time.desc()).limit(500).all()

    # Compute therblig stats from segments
    therblig_stats_map: dict = {}
    operations_map: dict = {}
    for seg in segments:
        action = seg.action or "unknown"
        therblig_symbol = seg.therblig_symbol or ""

        # Operations count
        if action not in operations_map:
            operations_map[action] = {"count": 0, "total_duration_ms": 0}
        operations_map[action]["count"] += 1
        operations_map[action]["total_duration_ms"] += seg.duration_ms or 0

        # Therblig stats
        if therblig_symbol and therblig_symbol not in therblig_stats_map:
            therblig_stats_map[therblig_symbol] = {
                "symbol": therblig_symbol,
                "name": therblig_symbol,
                "count": 0,
                "total_mod": 0.0,
                "total_seconds": 0.0,
                "is_waste": False,
            }
        if therblig_symbol in therblig_stats_map:
            therblig_stats_map[therblig_symbol]["count"] += 1
            therblig_stats_map[therblig_symbol]["total_seconds"] += (seg.duration_ms or 0) / 1000.0
            mod_val = (seg.duration_ms or 0) / 1000.0 / 0.129  # 1 MOD = 0.129s
            therblig_stats_map[therblig_symbol]["total_mod"] += mod_val

    # Build operations list
    operations = []
    for action, info in operations_map.items():
        count = info["count"]
        operations.append({
            "action": action,
            "count": count,
            "avg_duration_ms": info["total_duration_ms"] / count if count > 0 else 0,
            "total_duration_ms": info["total_duration_ms"],
        })

    # Compute KPI
    total_duration_ms = sum(
        seg.duration_ms or 0 for seg in segments
    )
    wait_ms = sum(
        seg.duration_ms or 0 for seg in segments if seg.action in ("wait", "idle")
    )
    utilization = (
        (total_duration_ms - wait_ms) / total_duration_ms
        if total_duration_ms > 0 else 0
    )

    kpi = {
        "Utilization": f"{utilization:.1%}",
        "Segments": str(len(segments)),
        "Total Time (s)": f"{total_duration_ms / 1000:.1f}",
        "Waste Time (s)": f"{wait_ms / 1000:.1f}",
    }

    pdf_data = {
        "station_id": station_id,
        "period": period,
        "kpi": kpi,
        "therblig_stats": list(therblig_stats_map.values()),
        "operations": operations,
        "efficiency_ranking": [],
    }

    try:
        pdf_bytes = generate_worktime_pdf(pdf_data)
    except RuntimeError as e:
        logger.error("Worktime PDF generation failed: %s", e)
        raise HTTPException(status_code=503, detail="PDF generation failed")

    # N-P1-18: sanitize station_id for safe filename in Content-Disposition header
    safe_station_id = re.sub(r'[^\w\-.]', '_', station_id) if station_id else 'all'
    safe_period = re.sub(r'[^\w\-.]', '_', period) if period else 'today'
    filename = f"worktime_{safe_station_id}_{safe_period}.pdf"
    return Response(
        content=pdf_bytes,
        media_type="application/pdf",
        headers={
            "Content-Disposition": f'attachment; filename="{filename}"',
        },
    )


@router.get("/line-balance/pdf")
def export_line_balance_pdf(
    line_id: str = Query("line1", description="Production line ID"),
    _user: dict = Depends(require_read_all),
    session: Session = Depends(get_db_session),
):
    """Export line balance analysis as PDF.

    Generates a PDF report containing:
    - Balance rate and smoothness index
    - Station workload distribution table
    - Bottleneck identification
    - ECRS improvement suggestions
    """
    from app.services.pdf_generator import generate_line_balance_pdf

    from app.models.database import ProcessSegment
    from sqlalchemy import func as sa_func

    # Get per-station avg cycle time
    station_stats = (
        session.query(
            ProcessSegment.station_id,
            sa_func.count(ProcessSegment.id).label("segment_count"),
            sa_func.avg(ProcessSegment.duration_ms).label("avg_duration_ms"),
            sa_func.sum(ProcessSegment.duration_ms).label("total_duration_ms"),
        )
        .group_by(ProcessSegment.station_id)
        .all()
    )

    if not station_stats:
        raise HTTPException(status_code=404, detail="No line balance data available")

    # Build stations list
    avg_times = [s.avg_duration_ms for s in station_stats if s.avg_duration_ms]
    max_time = max(avg_times) if avg_times else 1
    avg_time = sum(avg_times) / len(avg_times) if avg_times else 1
    min_time = min(avg_times) if avg_times else 0

    stations = []
    bottleneck_station = None
    bottleneck_time = 0

    for stat in station_stats:
        cycle_time = (stat.avg_duration_ms or 0) / 1000.0
        load = cycle_time / max_time if max_time > 0 else 0
        status = "normal"
        if cycle_time == max_time and len(station_stats) > 1:
            status = "bottleneck"
            bottleneck_station = stat.station_id
            bottleneck_time = cycle_time

        stations.append({
            "name": stat.station_id,
            "cycle_time": cycle_time,
            "load": load,
            "status": status,
        })

    # Balance rate = min / avg
    balance_rate = min_time / avg_time if avg_time > 0 else 0

    # Smoothness index
    if avg_time > 0:
        variance = sum((s.avg_duration_ms - avg_time) ** 2 for s in station_stats) / len(station_stats)
        std_dev = variance ** 0.5
        smoothness = 1 - (std_dev / avg_time)
    else:
        smoothness = 0

    # ECRS suggestions based on data
    ecrs = []
    if bottleneck_station and balance_rate < 0.85:
        ecrs.append({
            "priority": "1",
            "type": "Redistribute",
            "description": f"Redistribute workload from bottleneck station {bottleneck_station} to underutilized stations",
        })
    if balance_rate < 0.9:
        ecrs.append({
            "priority": "2",
            "type": "Simplify",
            "description": "Simplify operations at stations with above-average cycle time to reduce variation",
        })
    if balance_rate >= 0.75:
        ecrs.append({
            "priority": "3",
            "type": "Combine",
            "description": "Consider combining short-duration stations to reduce handoff waste",
        })

    pdf_data = {
        "line_id": line_id,
        "balance_rate": balance_rate,
        "smoothness_index": smoothness,
        "stations": stations,
        "bottleneck": {
            "station": bottleneck_station or "N/A",
            "cycle_time": bottleneck_time,
            "deviation": (bottleneck_time - avg_time) / avg_time if avg_time > 0 else 0,
        },
        "ecrs_suggestions": ecrs,
    }

    try:
        pdf_bytes = generate_line_balance_pdf(pdf_data)
    except RuntimeError as e:
        logger.error("Line balance PDF generation failed: %s", e)
        raise HTTPException(status_code=503, detail="PDF generation failed")

    safe_line_id = re.sub(r'[^\w\-.]', '_', line_id) if line_id else 'line1'
    filename = f"line_balance_{safe_line_id}.pdf"
    return Response(
        content=pdf_bytes,
        media_type="application/pdf",
        headers={
            "Content-Disposition": f'attachment; filename="{filename}"',
        },
    )
@router.get("/top-customers")
def top_customers(
    period: str = Query("month"),
    session: Session = Depends(get_db_session),
    _user: dict = Depends(require_read_all),
):
    """Get top customer ranking by order contribution.

    Returns customer name, order count, quantity, amount share.
    """
    results = session.query(
        Customer.name,
        func.count(Order.id).label("order_count"),
        func.sum(Order.quantity).label("total_qty"),
    ).join(Order, Order.customer_id == Customer.id).group_by(
        Customer.id
    ).order_by(func.sum(Order.quantity).desc()).limit(10).all()

    total_qty = sum(r.total_qty or 0 for r in results) if results else 1
    items = [
        {
            "name": r.name,
            "orders": r.order_count or 0,
            "qty": int(r.total_qty or 0),
            "amount": float(r.total_qty or 0),
            "share": round(float(r.total_qty or 0) / total_qty, 4) if total_qty > 0 else 0,
            "trend": 0.0,  # requires historical comparison for period-over-period trend
        }
        for i, r in enumerate(results)
    ]

    return ApiResponse(data=items, timestamp=time.time())
