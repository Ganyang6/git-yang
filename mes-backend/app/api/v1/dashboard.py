"""
Dashboard API routes.

Endpoints:
  GET /api/dashboard/kpi                   - core KPI metrics
  GET /api/dashboard/ai-context            - AI context snapshot
  GET /api/stations/timeline              - station timeline for chart
  GET /api/worktime/therblig-distribution - therblig time distribution
  GET /api/line-balance/bottleneck-diagnosis - bottleneck diagnosis

Note: Some endpoints match frontend paths that differ from the existing
v1 worktime routes. These routes serve the dashboard's specialized views.
All metric calculations conform to spec_metrics_formulas.md.
"""

from __future__ import annotations

import logging
import threading
import time
from collections import defaultdict
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo
from typing import Optional

from fastapi import APIRouter, Depends, Query
from sqlalchemy import func, case
from sqlalchemy.orm import Session

from app.models.database import (
    ProcessSegment, Equipment, Order, WorktimeRecord,
)
from app.models.schemas import ApiResponse
from app.services.line_balance_service import compute_line_balance_rate
from app.api.deps import get_db_session, require_read_all

# Asia/Shanghai timezone constant for shift/day calculations
SHANGHAI_TZ = ZoneInfo("Asia/Shanghai")

# Maximum number of segments to load per query to prevent unbounded memory usage.
# 50000 segments at ~200 bytes each = ~10MB, which is reasonable for KPI calculations.
_MAX_SEGMENT_QUERY_LIMIT = 50000

# In-memory cache: dict by key -> (timestamp, data, ttl_seconds)
_ctx_cache: dict = {}
_ctx_cache_lock = threading.Lock()

logger = logging.getLogger(__name__)


def _get_cached(key: str, ttl: float = 30.0) -> object | None:
    """Get value from in-memory cache if not expired."""
    with _ctx_cache_lock:
        entry = _ctx_cache.get(key)
    if entry is not None and time.time() - entry[0] < ttl:
        return entry[1]
    return None


def _set_cache(key: str, data: object) -> None:
    """Set value in in-memory cache."""
    with _ctx_cache_lock:
        _ctx_cache[key] = (time.time(), data)


def _clear_cache() -> None:
    """Clear the in-memory cache (for testing)."""
    with _ctx_cache_lock:
        _ctx_cache.clear()

router = APIRouter(tags=["dashboard"])


def _compute_hur_and_wait(segments):
    """Compute HUR (Human Utilization Rate) and wait times from segments.

    Shared by dashboard_kpi and ai_context to avoid duplicated logic.

    Returns:
        (total_ms, wait_ms, idle_ms, effective_ms, hur)
    """
    total_ms = sum(s.duration_ms for s in segments)
    wait_ms = sum(s.duration_ms for s in segments if s.action == "wait")
    idle_ms = sum(s.duration_ms for s in segments if s.action == "idle")
    effective_ms = total_ms - wait_ms - idle_ms
    t_total = max(total_ms, 1)
    hur = effective_ms / t_total
    return total_ms, wait_ms, idle_ms, effective_ms, hur




def _get_shift_seconds() -> tuple[float, float]:
    """Get current shift's total and elapsed seconds.

    Shift schedule (spec_metrics_formulas.md section 7.2):
      morning:   06:00-14:00 (28800s)
      afternoon: 14:00-22:00 (28800s)
      night:     22:00-06:00 (28800s)
    """
    now = datetime.now(SHANGHAI_TZ)
    hour = now.hour
    if 6 <= hour < 14:
        shift_start = now.replace(hour=6, minute=0, second=0, microsecond=0)
        shift_total = 28800.0
    elif 14 <= hour < 22:
        shift_start = now.replace(hour=14, minute=0, second=0, microsecond=0)
        shift_total = 28800.0
    else:
        if hour >= 22:
            shift_start = now.replace(hour=22, minute=0, second=0, microsecond=0)
        else:
            shift_start = (now - timedelta(days=1)).replace(
                hour=22, minute=0, second=0, microsecond=0
            )
        shift_total = 28800.0

    elapsed = (now - shift_start).total_seconds()
    return shift_total, max(elapsed, 0.0)


@router.get("/api/dashboard/kpi")
def dashboard_kpi(
    range_param: str = Query("today", alias="range"),
    line: str = Query(""),
    session: Session = Depends(get_db_session),
    _user: dict = Depends(require_read_all),
):
    """Get core KPI metrics for the dashboard.

    Metrics computed per spec_metrics_formulas.md:
    - utilization: HUR = T_effective / T_total
    - stdtimeAchievement: min(t_mod / t_actual, 1.0)
    - balanceRate: LBR from line balance calculation
    - waitLossMinutes: T_wait converted to minutes

    Performance: uses SQL aggregation and in-memory cache (15s TTL).
    """
    now_sh = datetime.now(SHANGHAI_TZ)

    # Determine time range (based on Asia/Shanghai calendar day)
    if range_param == "week":
        range_start = now_sh - timedelta(days=7)
        cache_key = "kpi_week"
    elif range_param == "month":
        range_start = now_sh - timedelta(days=30)
        cache_key = "kpi_month"
    else:
        # Start of today in Shanghai timezone
        range_start = now_sh.replace(hour=0, minute=0, second=0, microsecond=0)
        cache_key = "kpi_today"

    # Convert Shanghai timezone range_start to UTC for DB query (timestamps stored in UTC)
    range_start = range_start.astimezone(timezone.utc)

    # Check cache (15s TTL for KPI)
    cached = _get_cached(cache_key, ttl=15.0)
    if cached is not None:
        return ApiResponse(data=cached, timestamp=time.time())

    shift_total, _ = _get_shift_seconds()
    shift_total_ms = shift_total * 1000

    # Aggregated segment stats (single SQL query, no object loading)
    segment_stats_query = session.query(
        func.sum(ProcessSegment.duration_ms).label("total_ms"),
        func.sum(case((ProcessSegment.action == "wait", ProcessSegment.duration_ms), else_=0)).label("wait_ms"),
        func.sum(case((ProcessSegment.action == "idle", ProcessSegment.duration_ms), else_=0)).label("idle_ms"),
        func.count(ProcessSegment.id).label("seg_count"),
    ).filter(
        ProcessSegment.start_time >= range_start,
    )
    if line:
        segment_stats_query = segment_stats_query.filter(ProcessSegment.line == line)
    segment_stats = segment_stats_query.first()

    total_ms = float(segment_stats.total_ms or 0)
    wait_ms = float(segment_stats.wait_ms or 0)
    idle_ms = float(segment_stats.idle_ms or 0)
    effective_ms = total_ms - wait_ms - idle_ms
    t_total = max(total_ms, 1)
    hur = effective_ms / t_total if total_ms > 0 else 0.0

    if total_ms == 0:
        data = {
            "utilization": 0.0,
            "stdtimeAchievement": 0.0,
            "balanceRate": 0.0,
            "waitLossMinutes": 0.0,
            "trends": [],
        }
        _set_cache(cache_key, data)
        return ApiResponse(data=data, timestamp=time.time())

    # Standard time achievement (spec section 2.2)
    # MOD values per action (spec table)
    mod_map = {
        "reach": 3.0, "grasp": 1.0, "move": 4.0, "assemble": 5.0,
        "release": 1.0, "inspect": 3.0, "wait": 0.0, "idle": 0.0,
    }
    mod_unit = 0.129  # seconds per MOD

    # Get total duration per action via SQL GROUP BY (much faster than loading 50K rows)
    action_durations_query = session.query(
        ProcessSegment.action,
        func.sum(ProcessSegment.duration_ms).label("dur"),
    ).filter(
        ProcessSegment.start_time >= range_start,
    )
    if line:
        action_durations_query = action_durations_query.filter(ProcessSegment.line == line)
    action_durations = action_durations_query.group_by(ProcessSegment.action).all()

    total_mod_ms = 0.0
    for action, dur in action_durations:
        mod_val = mod_map.get(action, 0.0)
        total_mod_ms += float(dur) * mod_val * mod_unit * 1000

    std_achievement = min(total_mod_ms / t_total, 1.0) if t_total > 0 else 0.0

    # Line balance rate
    lbr, bottleneck, _ = compute_line_balance_rate(session)

    # Wait loss in minutes
    wait_loss_min = wait_ms / 60000.0

    data = {
        "utilization": round(hur, 4),
        "stdtimeAchievement": round(std_achievement, 4),
        "balanceRate": round(lbr, 4),
        "waitLossMinutes": round(wait_loss_min, 1),
        "trends": [],
    }

    _set_cache(cache_key, data)

    return ApiResponse(data=data, timestamp=time.time())


@router.get("/api/dashboard/ai-context")
def ai_context(
    line: str = Query(""),
    session: Session = Depends(get_db_session),
    _user: dict = Depends(require_read_all),
):
    """Get structured AI context snapshot for injection into prompts.

    Provides real-time production line metrics that the AI agent
    needs to give informed analysis.

    Performance: uses SQL aggregation instead of loading all segments into
    Python memory. Results are cached in-memory for 30s to prevent
    repeated expensive queries on rapid frontend polling.
    """
    # Check cache first (30s TTL to balance freshness vs query load)
    cached = _get_cached("ai_context", ttl=30.0)
    if cached is not None:
        return ApiResponse(data=cached, timestamp=time.time())

    now_sh = datetime.now(SHANGHAI_TZ)
    # Start of today in Shanghai, then convert to UTC for DB query
    range_start = now_sh.replace(hour=0, minute=0, second=0, microsecond=0).astimezone(timezone.utc)

    # ── Aggregated segment stats (single query, no object loading) ──
    segment_stats_query = session.query(
        # Total duration_ms sum
        func.sum(ProcessSegment.duration_ms).label("total_ms"),
        # Wait duration_ms sum
        func.sum(case((ProcessSegment.action == "wait", ProcessSegment.duration_ms), else_=0)).label("wait_ms"),
        # Idle duration_ms sum
        func.sum(case((ProcessSegment.action == "idle", ProcessSegment.duration_ms), else_=0)).label("idle_ms"),
        # Total segment count
        func.count(ProcessSegment.id).label("seg_count"),
    ).filter(
        ProcessSegment.start_time >= range_start,
    )
    if line:
        segment_stats_query = segment_stats_query.filter(ProcessSegment.line == line)
    segment_stats = segment_stats_query.first()

    total_ms = float(segment_stats.total_ms or 0)
    wait_ms = float(segment_stats.wait_ms or 0)
    idle_ms = float(segment_stats.idle_ms or 0)
    effective_ms = total_ms - wait_ms - idle_ms

    hur = effective_ms / total_ms if total_ms > 0 else 0.0
    waste_ratio = (wait_ms + idle_ms) / total_ms if total_ms > 0 else 0.0

    # ── Line balance rate (single aggregated query inside compute) ──
    lbr, bottleneck, station_data = compute_line_balance_rate(session)

    # Takt time = available time / demand
    # Use shift hours (8h) and completed orders in the current shift
    completed_qty = session.query(
        func.sum(Order.completed_qty)
    ).filter(
        Order.updated_at >= range_start if hasattr(Order, "updated_at") else True
    ).scalar() or 0
    shift_seconds = 28800.0
    takt_time = shift_seconds / completed_qty if completed_qty > 0 else 0.0

    max_d = max((s["time"] for s in station_data), default=0)
    n = len(station_data) if station_data else 1
    avg_d = sum(s["time"] for s in station_data) / n if station_data else 0
    lost_capacity = (max_d - avg_d) * n if station_data else 0.0

    data = {
        "balanceRate": round(lbr, 4),
        "bottleneckStation": bottleneck,
        "taktTime": round(takt_time, 1),
        "lostCapacity": round(lost_capacity / 1000, 1),
        "utilization": round(hur, 4),
        "stdtimeAchievement": round(
            min(1.0, hur) if total_ms > 0 else 0.0, 4
        ),
        "wasteRatio": round(waste_ratio, 4),
    }

    _set_cache("ai_context", data)

    return ApiResponse(data=data, timestamp=time.time())


@router.get("/api/stations/timeline")
def station_timeline(
    session: Session = Depends(get_db_session),
    _user: dict = Depends(require_read_all),
):
    """Get station timeline data for current shift.

    Returns per-station time breakdown by action category.
    """
    now_sh = datetime.now(SHANGHAI_TZ)
    shift_start = now_sh.replace(hour=0, minute=0, second=0, microsecond=0).astimezone(timezone.utc)

    # Get equipment list as stations
    stations = session.query(Equipment).order_by(Equipment.id).all()
    if not stations:
        return ApiResponse(data=[], timestamp=time.time())

    # Aggregate segment stats per station via SQL GROUP BY (avoids loading 50K objects)
    station_action_stats = session.query(
        ProcessSegment.station_id,
        ProcessSegment.action,
        func.sum(ProcessSegment.duration_ms).label("dur"),
    ).filter(
        ProcessSegment.start_time >= shift_start,
    ).group_by(
        ProcessSegment.station_id, ProcessSegment.action
    ).all()

    # Build a lookup: station_id -> {action: duration_ms}
    station_action_map: dict[str, dict[str, float]] = defaultdict(lambda: defaultdict(float))
    for row in station_action_stats:
        action = row.action
        if action in ("wait", "idle"):
            station_action_map[row.station_id][action] += float(row.dur)
        else:
            station_action_map[row.station_id]["work"] += float(row.dur)

    labels = {"work": "Effective", "wait": "Wait", "idle": "Idle"}
    types = {"work": "effective", "wait": "wait", "idle": "idle"}

    timeline = []
    for eq in stations:
        action_groups = station_action_map.get(eq.name, {})
        total_ms = sum(action_groups.values())

        segments_list = []
        for action, ms in sorted(action_groups.items(), key=lambda x: -x[1]):
            pct = (ms / total_ms * 100) if total_ms > 0 else 0
            segments_list.append({
                "type": types.get(action, action),
                "label": labels.get(action, action),
                "time": round(ms / 1000, 1),
                "pct": round(pct, 1),
            })

        timeline.append({
            "id": eq.id,
            "name": eq.name,
            "oee": round(eq.oee, 4),
            "segments": segments_list,
        })

    return ApiResponse(data=timeline, timestamp=time.time())


@router.get("/api/worktime/therblig-distribution")
def therblig_distribution(
    station: str = Query("all"),
    shift: str = Query("morning"),
    session: Session = Depends(get_db_session),
    _user: dict = Depends(require_read_all),
):
    """Get Therblig time distribution for pie chart.

    Maps action labels to therblig symbols and calculates percentage.
    """
    now_sh = datetime.now(SHANGHAI_TZ)
    range_start = now_sh.replace(hour=0, minute=0, second=0, microsecond=0).astimezone(timezone.utc)

    query = session.query(ProcessSegment).filter(
        ProcessSegment.start_time >= range_start,
    )
    if station != "all":
        query = query.filter(ProcessSegment.station_id == station)

    segments = query.order_by(ProcessSegment.start_time.desc()).limit(_MAX_SEGMENT_QUERY_LIMIT).all()

    # Map actions to therblig
    action_therblig = {
        "reach": ("R", "Reach", "#5470c6"),
        "grasp": ("G", "Grasp", "#91cc75"),
        "move": ("M", "Move", "#fac858"),
        "assemble": ("A", "Assemble", "#ee6666"),
        "release": ("RL", "Release", "#73c0de"),
        "inspect": ("I", "Inspect", "#3ba272"),
        "wait": ("UD", "Wait", "#fc8452"),
        "idle": ("AD", "Idle", "#9a60b4"),
    }

    action_ms = defaultdict(float)
    for s in segments:
        action_ms[s.action] += s.duration_ms

    total_ms = sum(action_ms.values()) if action_ms else 1

    items = []
    for action, ms in sorted(action_ms.items(), key=lambda x: -x[1]):
        symbol, name, color = action_therblig.get(action, (action, action, "#999"))
        pct = ms / total_ms * 100
        items.append({
            "label": f"{symbol} {name}",
            "pct": round(pct, 1),
            "color": color,
        })

    return ApiResponse(data=items, timestamp=time.time())


@router.get("/api/line-balance/bottleneck-diagnosis")
def bottleneck_diagnosis(
    line: str = Query(""),
    session: Session = Depends(get_db_session),
    _user: dict = Depends(require_read_all),
):
    """Diagnose bottleneck stations using BI (Bottleneck Index).

    Per spec_metrics_formulas.md section 5.3:
      BI_i = D_i / D_avg

    Judgment:
      BI >= 1.30: Severe bottleneck, trigger ECRS
      1.20 <= BI < 1.30: Bottleneck, monitor
      0.80 <= BI < 1.20: Normal
      BI < 0.80: Light load
    """
    now_sh = datetime.now(SHANGHAI_TZ)
    range_start = now_sh.replace(hour=0, minute=0, second=0, microsecond=0).astimezone(timezone.utc)

    results_query = session.query(
        ProcessSegment.station_id,
        func.avg(ProcessSegment.duration_ms).label("avg_duration"),
        func.count(ProcessSegment.id).label("seg_count"),
    ).filter(
        ProcessSegment.start_time >= range_start,
        ProcessSegment.action != "idle",
    )
    if line:
        results_query = results_query.filter(ProcessSegment.line == line)
    results = results_query.group_by(ProcessSegment.station_id).all()

    if not results:
        return ApiResponse(data=[], timestamp=time.time())

    station_data = []
    for r in results:
        if r.seg_count > 0:
            station_data.append({
                "name": r.station_id,
                "time": float(r.avg_duration),
                "count": r.seg_count,
            })

    n = len(station_data)
    avg_time = sum(s["time"] for s in station_data) / n if n > 0 else 1

    diagnosis = []
    ecrs_suggestions = {
        "severe": "Recommend immediate ECRS analysis: consider splitting tasks, adding parallel stations, or improving tooling.",
        "bottleneck": "Monitor closely. Consider minor process improvements or workload redistribution.",
        "normal": "Within acceptable range. Continue standard operations.",
        "light": "Underutilized. Consider merging operations or redistributing workload.",
    }

    for s in station_data:
        bi = s["time"] / avg_time if avg_time > 0 else 0

        if bi >= 1.30:
            level = "severe"
            level_label = "Severe"
            reason = f"BI={bi:.2f}, average time {s['time']/1000:.1f}s vs line average {avg_time/1000:.1f}s (exceeds 130% threshold)"
            suggest = ecrs_suggestions["severe"]
        elif bi >= 1.20:
            level = "bottleneck"
            level_label = "Warning"
            reason = f"BI={bi:.2f}, approaching bottleneck threshold (120-130%)"
            suggest = ecrs_suggestions["bottleneck"]
        elif bi >= 0.80:
            level = "normal"
            level_label = "Normal"
            reason = f"BI={bi:.2f}, within normal range"
            suggest = ecrs_suggestions["normal"]
        else:
            level = "light"
            level_label = "Light"
            reason = f"BI={bi:.2f}, station is underloaded (below 80%)"
            suggest = ecrs_suggestions["light"]

        diagnosis.append({
            "station": s["name"],
            "level": level,
            "levelLabel": level_label,
            "reason": reason,
            "suggest": suggest,
        })

    # Sort by severity
    severity_order = {"severe": 0, "bottleneck": 1, "normal": 2, "light": 3}
    diagnosis.sort(key=lambda d: severity_order.get(d["level"], 99))

    return ApiResponse(data=diagnosis, timestamp=time.time())
