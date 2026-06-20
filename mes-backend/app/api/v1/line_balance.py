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
from app.models.schemas import (
    ApiResponse, LineBalanceSummary, LineBalanceFull,
    validate_response_data,
)
from app.services.line_balance_service import (
    compute_balance_metrics,
    generate_ecrs_suggestions,
    get_station_metrics,
)
from app.api.deps import get_db_session, require_read_all

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/line-balance", tags=["line-balance"])


def _compute_line_balance_context(
    session: Session,
    line: Optional[str] = None,
    shift: Optional[str] = None,
    range_hours: float = 8.0,
) -> dict:
    """Compute shared line balance context used by both /summary and /full.

    Args:
        session: Database session.
        line: Optional line filter to scope station metrics.
        shift: Optional shift filter (e.g. "morning", "afternoon").
        range_hours: Look-back window in hours (passed to get_station_metrics).

    Returns a dict with keys: station_data, stations, lbr, si, bottleneck,
    takt_time, avg_d.
    """
    station_data = get_station_metrics(session, range_hours=168.0, line=line, shift=shift)
    n = len(station_data) if station_data else 1
    avg_d = sum(s["time"] for s in station_data) / n if station_data else 0

    metrics = compute_balance_metrics(station_data)
    stations = metrics["stations"]

    # Takt time = available time / demand (using total order quantity, not completed)
    total_demand = session.query(func.sum(Order.quantity)).scalar() or 0
    completed_qty = session.query(func.sum(Order.completed_qty)).scalar() or 0
    shift_seconds = 28800.0
    takt_time = shift_seconds / total_demand if total_demand > 0 else 0.0

    return {
        "station_data": station_data,
        "stations": stations,
        "lbr": metrics["balanceRate"],
        "si": metrics["smoothIndex"],
        "bottleneck": metrics["bottleneckStation"],
        "takt_time": takt_time,
        "total_demand": total_demand,
        "completed_qty": completed_qty,
        "avg_d": avg_d,
        "n": n,
    }


@router.get("/summary")
def line_balance_summary(
    session: Session = Depends(get_db_session),
    _user: dict = Depends(require_read_all),
):
    """Get line balance summary for the dashboard."""
    ctx = _compute_line_balance_context(session)

    return ApiResponse(
        data=validate_response_data(LineBalanceSummary, {
            "balanceRate": ctx["lbr"],
            "smoothIndex": ctx["si"],
            "bottleneckStation": ctx["bottleneck"],
            "stations": ctx["stations"],
            "taktTime": round(ctx["takt_time"], 1),
            "dailyDemand": ctx["total_demand"],
            "dailyCompleted": ctx["completed_qty"],
        }),
        timestamp=time.time(),
    )


@router.get("/full")
def line_balance_full(
    line: str = Query(""),
    shift: str = Query(""),
    session: Session = Depends(get_db_session),
    _user: dict = Depends(require_read_all),
):
    """Get complete line balance data with ECRS suggestions.

    Args:
        line: Optional line name filter.
        shift: Optional shift filter (e.g. "morning", "afternoon").
    """
    shift_val = shift or None
    ctx = _compute_line_balance_context(session, line=line, shift=shift_val)
    stations = ctx["stations"]

    # Compute per-station efficiency (effective work ratio)
    from datetime import datetime, timedelta, timezone
    from sqlalchemy import case as sa_case
    from app.models.database import ProcessSegment

    range_start = ctx.get("_range_start") or (datetime.now(timezone.utc) - timedelta(hours=8))
    eff_rows = session.query(
        ProcessSegment.station_id,
        func.sum(ProcessSegment.duration_ms).label("total_ms"),
        func.sum(sa_case((ProcessSegment.action.in_(["wait", "idle"]), ProcessSegment.duration_ms), else_=0)).label("waste_ms"),
    ).filter(
        ProcessSegment.start_time >= range_start,
    ).group_by(ProcessSegment.station_id).all()

    eff_map = {}
    for row in eff_rows:
        total = float(row.total_ms or 0)
        waste = float(row.waste_ms or 0)
        if total > 0:
            eff_map[row.station_id] = round((total - waste) / total, 4)
    for s in stations:
        s["efficiency"] = eff_map.get(s["name"], 0.0)

    n = ctx["n"]
    avg_d = ctx["avg_d"]
    si = ctx["si"]
    lbr = ctx["lbr"]
    takt_time = ctx["takt_time"]
    bottleneck = ctx["bottleneck"]
    completed_qty = ctx["completed_qty"]

    # Lost capacity = (max - avg) * N stations
    max_d = max((s["time"] for s in stations), default=0)
    lost_capacity = (max_d - avg_d) * n if stations else 0.0

    # 每日产量（基于瓶颈节拍）
    shift_seconds = 28800.0
    daily_output = int(shift_seconds / (max_d if max_d > 0 else 1)) if max_d > 0 else 0
    # 每日损失时间（秒）
    daily_lost_time = round((max_d - avg_d) * daily_output, 1) if max_d > 0 else 0.0

    # Lost value estimation (using average MOD rate)
    mod_rate = 0.129  # seconds per MOD
    lost_value = lost_capacity * mod_rate * 60  # rough CNY estimate per minute

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

    if si is not None and si >= 10:
        causal_rules.append({
            "condition": f"SI >= 10s (actual: {si:.0f}s)",
            "conclusion": "High workload variance across stations",
            "level": "warning",
        })

    # --- Compute baseline metrics for saving/improvement formulas ---
    station_times = [s["time"] for s in stations]
    sorted_times = sorted(station_times, reverse=True)
    max_time = sorted_times[0] if sorted_times else 0
    second_max_time = sorted_times[1] if len(sorted_times) > 1 else max_time
    total_time = sum(station_times)
    n_stations = len(station_times)

    # 当前平衡率
    br_old = total_time / (max_time * n_stations) if max_time > 0 and n_stations > 0 else 0

    # 保守改善：瓶颈降到次高水平
    new_times = list(station_times)
    for i, s in enumerate(stations):
        if s.get("isBottleneck"):
            new_times[i] = second_max_time
            break
    new_max = max(new_times, default=0)
    br_new = sum(new_times) / (new_max * n_stations) if new_max > 0 and n_stations > 0 else 0

    saving_seconds = round(max_time - second_max_time, 1)
    improvement_pct = round((br_new - br_old) * 100, 1)

    # --- Map causal_rules to frontend-expected format ---
    mapped_causal = []
    for i, r in enumerate(causal_rules):
        mapped_causal.append({
            "station": bottleneck,
            "condition": r["condition"],
            "cause": r["conclusion"],
            "action": "优化瓶颈工位操作流程，减少非增值动作",
            "saving": f"{saving_seconds}s/件",
            "improvement": f"{improvement_pct}%",
        })

    # --- Map ecrs_items to frontend-expected format ---
    ecrs_type_map = {
        "Eliminate": ("eliminate", "消除"),
        "Combine": ("combine", "合并"),
        "Rearrange": ("rearrange", "重排"),
        "Simplify": ("simplify", "简化"),
    }
    mapped_ecrs = []
    for i, item in enumerate(ecrs_items):
        etype, etype_label = ecrs_type_map.get(item["method"], ("", item["method"]))
        # 根据 ECRS 类型赋予不同的 saving 值
        if etype in ("eliminate", "simplify"):
            ecrs_saving = f"{saving_seconds}s/件"
        elif etype == "combine":
            ecrs_saving = f"{round(max_time * 0.3, 1)}s/件"
        else:  # rearrange
            ecrs_saving = "待分析"
        mapped_ecrs.append({
            "type": etype,
            "typeLabel": etype_label,
            "station": item["target"],
            "content": item["description"],
            "saving": ecrs_saving,
            "difficulty": 2,
            "priority": "P2",
            "status": "pending",
        })

    return ApiResponse(
        data=validate_response_data(LineBalanceFull, {
            "balanceRate": lbr,
            "smoothIndex": si,
            "taktTime": round(takt_time, 1),
            "dailyDemand": ctx["total_demand"],
            "dailyCompleted": ctx["completed_qty"],
            "bottleneck": bottleneck,
            "lostCapacity": round(lost_capacity, 1),
            "dailyLostCapacity": daily_lost_time,
            "lostValue": round(lost_value, 1),
            "stations": stations,
            "causalRules": mapped_causal,
            "ecrsItems": mapped_ecrs,
        }),
        timestamp=time.time(),
    )
