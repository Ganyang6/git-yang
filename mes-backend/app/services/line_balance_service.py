"""Shared line balance computation service.

Extracted from dashboard.py and line_balance.py to eliminate duplicate
balance calculation logic (S05).

Conforms to spec_metrics_formulas.md sections 5.1-5.3.
"""

from __future__ import annotations

import math
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional

from sqlalchemy import func
from sqlalchemy.orm import Session

from app.models.database import ProcessSegment


def get_station_metrics(
    session: Session,
    range_hours: float = 8.0,
) -> List[Dict[str, Any]]:
    """Get per-station average operation time from recent segments.

    Args:
        session: Database session.
        range_hours: Hours to look back for segment data.

    Returns:
        List of dicts with keys: name, time (ms), count.
    """
    now = datetime.now(timezone.utc)
    range_start = now - timedelta(hours=range_hours)

    results = session.query(
        ProcessSegment.station_id,
        func.avg(ProcessSegment.duration_ms).label("avg_duration"),
        func.count(ProcessSegment.id).label("seg_count"),
    ).filter(
        ProcessSegment.start_time >= range_start,
        ProcessSegment.action != "idle",
    ).group_by(ProcessSegment.station_id).all()

    station_data = []
    for r in results:
        if r.seg_count > 0:
            station_data.append({
                "name": r.station_id,
                "time": round(float(r.avg_duration) / 1000.0, 3),
                "count": r.seg_count,
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
            "balanceRate": 1.0,
            "smoothIndex": 0.0,
            "bottleneckStation": "",
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
) -> tuple[float, str, list]:
    """Compute line balance rate (backward-compatible with dashboard).

    LBR = sum(D_i) / (max(D_i) * N_stations)

    Returns (balance_rate, bottleneck_station, station_list).
    """
    station_data = get_station_metrics(session, range_hours)
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
