"""Shared line balance computation service.

Extracted from dashboard.py and line_balance.py to eliminate duplicate
balance calculation logic (S05).

Conforms to spec_metrics_formulas.md sections 5.1-5.3.
"""

from __future__ import annotations

import math
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models.database import ProcessSegment, WorktimeRecord


def get_station_metrics(
    session: Session,
    range_hours: float = 8.0,
    range_start: Optional[datetime] = None,
    line: Optional[str] = None,
    shift: Optional[str] = None,
) -> List[Dict[str, Any]]:
    """Get per-station average operation time from recent segments.

    Args:
        session: Database session.
        range_hours: Hours to look back (used when range_start is None).
        range_start: Explicit start datetime override. When provided, used instead
                     of computing from range_hours.
        line: Optional line filter. When provided, only segments matching
              this line are included.
        shift: Optional shift filter. When provided, only records matching
               this shift are included (e.g. "morning", "afternoon").

    Returns:
        List of dicts with keys: name, time (ms), count, shift.
    """
    range_hours = range_hours or 168.0  # default 7 days
    if range_start is None:
        now = datetime.now(timezone.utc)
        range_start = now - timedelta(hours=range_hours)

    query = session.query(
        WorktimeRecord.station_id,
        WorktimeRecord.shift,
        func.avg(WorktimeRecord.actual_ms).label("avg_duration"),
        func.count(WorktimeRecord.id).label("seg_count"),
    ).filter(
        WorktimeRecord.created_at >= range_start,
    )
    if line:
        # WorktimeRecord has no line column; use subquery via ProcessSegment
        subq = select(ProcessSegment.station_id).filter(
            ProcessSegment.line == line,
            ProcessSegment.start_time >= range_start,
        ).distinct()
        query = query.filter(WorktimeRecord.station_id.in_(subq))

    if shift:
        query = query.filter(WorktimeRecord.shift == shift)

    results = query.group_by(WorktimeRecord.station_id, WorktimeRecord.shift).all()

    station_data = []
    for r in results:
        if r.seg_count > 0:
            # Clamp negative durations to 0; negative work time is physically
            # impossible and violates schema constraints (StationInfo.time >= 0).
            avg_ms = max(float(r.avg_duration), 0.0)
            station_data.append({
                "name": r.station_id,
                "time": round(avg_ms / 1000.0, 3),
                "count": r.seg_count,
                "shift": r.shift,
            })
    return station_data


def compute_balance_metrics(
    station_data: List[Dict[str, Any]],
) -> Dict[str, Any]:
    """Compute LBR, SI, bottleneck from station data.

    Per spec_metrics_formulas.md:
      LBR = sum(D_i) / (max(D_i) * N)
      SI  = sqrt(sum((D_i - D_avg)^2))

    Returns dict with keys:
        balanceRate, smoothIndex, bottleneckStation, stations
    """
    if not station_data:
        return {
            "balanceRate": None,
            "smoothIndex": None,
            "bottleneckStation": None,
            "stations": [],
        }

    n = len(station_data)
    durations = [s["time"] for s in station_data]
    total = sum(durations)
    max_d = max(durations)
    avg_d = total / n

    if max_d == 0:
        return {
            "balanceRate": 1.0,
            "smoothIndex": 0.0,
            "bottleneckStation": "",
            "stations": station_data,
        }

    lbr = total / (max_d * n)

    # Smoothness Index (spec section 5.2)
    variance = sum((d - avg_d) ** 2 for d in durations)
    si = math.sqrt(variance)

    bottleneck_name = max(station_data, key=lambda s: s["time"])["name"]

    # Mark bottleneck stations (BI >= 1.20)
    for s in station_data:
        bi = s["time"] / avg_d if avg_d > 0 else 0
        s["isBottleneck"] = bi >= 1.20

    return {
        "balanceRate": round(lbr, 4),
        "smoothIndex": round(si, 1),
        "bottleneckStation": bottleneck_name,
        "stations": station_data,
    }


def compute_line_balance_rate(
    session: Session,
    range_hours: float = 8.0,
    range_start: Optional[datetime] = None,
    line: Optional[str] = None,
) -> tuple[float, str, list]:
    """Compute line balance rate (backward-compatible with dashboard).

    LBR = sum(D_i) / (max(D_i) * N_stations)

    Args:
        session: Database session.
        range_hours: Hours to look back (used when range_start is None).
        range_start: Explicit start datetime override. When provided,
                     the query uses this time window instead of range_hours.
        line: Optional line filter. When provided, only segments matching
              this line are included.

    Returns (balance_rate, bottleneck_station, station_list).
    """
    station_data = get_station_metrics(session, range_hours, range_start=range_start, line=line)
    metrics = compute_balance_metrics(station_data)
    return (
        metrics["balanceRate"],
        metrics["bottleneckStation"],
        metrics["stations"],
    )


def generate_ecrs_suggestions(
    station_data: List[Dict[str, Any]],
    avg_d: float,
) -> List[Dict[str, str]]:
    """Generate ECRS improvement suggestions based on station data.

    ECRS: Eliminate, Combine, Rearrange, Simplify.
    """
    suggestions: List[Dict[str, str]] = []

    if not station_data:
        return suggestions

    bottleneck = max(station_data, key=lambda s: s["time"])
    lightest = min(station_data, key=lambda s: s["time"])

    if bottleneck["time"] / avg_d >= 1.30:
        suggestions.append({
            "method": "Eliminate",
            "target": bottleneck["name"],
            "description": (
                f"Station {bottleneck['name']} is severely overloaded (BI>1.30). "
                f"Eliminate non-value-added steps to reduce cycle time."
            ),
        })

    for s in station_data:
        bi = s["time"] / avg_d if avg_d > 0 else 0
        if bi < 0.80:
            suggestions.append({
                "method": "Combine",
                "target": f"{lightest['name']} + {bottleneck['name']}",
                "description": (
                    f"Station {s['name']} is underloaded (BI={bi:.2f}). "
                    f"Consider combining part of {bottleneck['name']}'s workload here."
                ),
            })

    suggestions.append({
        "method": "Rearrange",
        "target": "All stations",
        "description": (
            "Review operation sequence across all stations to minimize "
            "unnecessary material handling and waiting between steps."
        ),
    })

    suggestions.append({
        "method": "Simplify",
        "target": bottleneck["name"],
        "description": (
            f"Simplify tool changes and fixture setup at station {bottleneck['name']} "
            f"to reduce its current {bottleneck['time']:.1f}s cycle time."
        ),
    })

    return suggestions
