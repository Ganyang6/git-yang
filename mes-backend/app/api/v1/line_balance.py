"""
Line balance API routes.

Endpoints:
  GET /api/line-balance/summary - line balance overview
  GET /api/line-balance/full    - complete line balance data with ECRS

Conforms to spec_metrics_formulas.md sections 5.1-5.3.
"""

from __future__ import annotations

import logging
import time
from typing import Optional

from fastapi import APIRouter, Depends, Query
from sqlalchemy import func
from sqlalchemy.orm import Session

from app.models.database import get_session, Order
from app.models.schemas import ApiResponse
from app.services.line_balance_service import (
    compute_balance_metrics,
    generate_ecrs_suggestions,
    get_station_metrics,
)
from app.api.deps import get_db_session, require_read_all

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/line-balance", tags=["line-balance"])




@router.get("/summary")
def line_balance_summary(
    session: Session = Depends(get_db_session),
    _user: dict = Depends(require_read_all),
):
    """Get line balance summary for the dashboard."""
    station_data = get_station_metrics(session)
    n = len(station_data) if station_data else 1
    avg_d = sum(s["time"] for s in station_data) / n if station_data else 0

    metrics = compute_balance_metrics(station_data)
    lbr = metrics["balanceRate"]
    si = metrics["smoothIndex"]
    bottleneck = metrics["bottleneckStation"]
    stations = metrics["stations"]

    # Takt time = available time / demand
    completed_qty = session.query(func.sum(Order.completed_qty)).scalar() or 0
    shift_seconds = 28800.0
    # N-P1-14: consistent with /full endpoint -- return 0 when no demand
    takt_time = shift_seconds / completed_qty if completed_qty > 0 else 0.0

    return ApiResponse(
        data={
            "balanceRate": lbr,
            "smoothIndex": si,
            "bottleneckStation": bottleneck,
            "stations": stations,
            "taktTime": round(takt_time, 1),
        },
        timestamp=time.time(),
    )


@router.get("/full")
def line_balance_full(
    line: str = Query("line1"),
    session: Session = Depends(get_db_session),
    _user: dict = Depends(require_read_all),
):
    """Get complete line balance data with ECRS suggestions."""
    station_data = get_station_metrics(session)
    n = len(station_data) if station_data else 1
    avg_d = sum(s["time"] for s in station_data) / n if station_data else 0

    metrics = compute_balance_metrics(station_data)
    lbr = metrics["balanceRate"]
    si = metrics["smoothIndex"]
    bottleneck = metrics["bottleneckStation"]
    stations = metrics["stations"]

    # Takt time (N-P1-14: consistent zero-division strategy with /summary)
    completed_qty = session.query(func.sum(Order.completed_qty)).scalar() or 0
    shift_seconds = 28800.0
    takt_time = shift_seconds / completed_qty if completed_qty > 0 else 0.0

    # Lost capacity = (max - avg) * N stations
    max_d = max((s["time"] for s in stations), default=0)
    lost_capacity = (max_d - avg_d) * n if stations else 0.0

    # Lost value estimation (using average MOD rate)
    mod_rate = 0.129  # seconds per MOD
    lost_value = lost_capacity / 1000 * mod_rate * 60  # rough CNY estimate per minute

    # ECRS suggestions
    ecrs_items = generate_ecrs_suggestions(stations, avg_d)

    # Causal rules for bottleneck
    causal_rules = []
    if max_d > 0 and avg_d > 0:
        bi = max_d / avg_d
        if bi >= 1.30:
            causal_rules.append({
                "condition": f"BI >= 1.30 (actual: {bi:.2f})",
                "conclusion": "Severe bottleneck detected",
                "level": "critical",
            })
        elif bi >= 1.20:
            causal_rules.append({
                "condition": f"BI >= 1.20 (actual: {bi:.2f})",
                "conclusion": "Moderate bottleneck detected",
                "level": "warning",
            })

    if si >= 10000:
        causal_rules.append({
            "condition": f"SI >= 10000ms (actual: {si:.0f}ms)",
            "conclusion": "High workload variance across stations",
            "level": "warning",
        })

    return ApiResponse(
        data={
            "balanceRate": lbr,
            "smoothIndex": si,
            "taktTime": round(takt_time, 1),
            "dailyDemand": completed_qty if completed_qty > 0 else 0,
            "bottleneck": bottleneck,
            "lostCapacity": round(lost_capacity / 1000, 1),
            "lostValue": round(lost_value, 1),
            "stations": stations,
            "causalRules": causal_rules,
            "ecrsItems": ecrs_items,
        },
        timestamp=time.time(),
    )
