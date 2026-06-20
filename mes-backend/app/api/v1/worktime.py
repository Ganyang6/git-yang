"""
Worktime analysis API routes.

Endpoints:
  GET  /api/v1/worktime/summary        - worktime summary stats
  GET  /api/v1/worktime/operations     - per-operation worktime list
  GET  /api/v1/worktime/therblig/{id}  - therblig detail for one operation
  GET  /api/v1/worktime/recent         - latest process segments
  GET  /api/v1/worktime/trend          - worktime trend (days)
  GET  /api/v1/worktime/therblig-distribution - therblig time distribution
  PUT  /api/v1/worktime/operations/{id} - manually calibrate standard_ms (admin)
"""

from __future__ import annotations

import logging
import time
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.models.database import get_session, init_db
from app.models.schemas import (
    ApiResponse, PaginatedResponse, WorktimeSummary,
    WorktimeOperation, validate_response_data,
)
from app.services import worktime_aggregator
from app.api.deps import get_db_session, require_read_all, require_admin

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/v1/worktime", tags=["worktime"])


class CalibrateRequest(BaseModel):
    """Request model for calibrating a worktime record."""
    standard_ms: float = Field(..., ge=0, description="New standard time in milliseconds")


@router.put("/operations/{operation_id}")
def calibrate_worktime(
    operation_id: int,
    body: CalibrateRequest,
    session: Session = Depends(get_db_session),
    _user: dict = Depends(require_admin),
):
    """Manually calibrate standard_ms for a worktime record.

    Accepts ``{"standard_ms": <float>}``, updates the record, and
    automatically recalculates ``efficiency = standard_ms / actual_ms``.

    Requires admin role.
    """
    from app.models.database import WorktimeRecord

    standard_ms = body.standard_ms
    record = session.get(WorktimeRecord, operation_id)
    if not record:
        raise HTTPException(status_code=404, detail="Worktime record not found")

    record.standard_ms = float(standard_ms)
    # Recalculate efficiency: efficiency = standard_ms / actual_ms
    # If actual_ms is 0, efficiency = 0 to avoid division by zero
    record.efficiency = round(float(standard_ms) / record.actual_ms, 4) if record.actual_ms > 0 else 0.0

    session.commit()
    session.refresh(record)

    logger.info(
        "校准工时: operation_id=%s standard_ms=%.1f actual_ms=%.1f efficiency=%.4f",
        operation_id, record.standard_ms, record.actual_ms, record.efficiency,
    )

    return ApiResponse(
        data={
            "id": record.id,
            "operation": record.operation,
            "station": record.station_id,
            "actual": round(max(record.actual_ms, 0.0) / 1000.0, 2),
            "standard": round(record.standard_ms / 1000.0, 2),
            "efficiency": round(record.efficiency * 100, 2),
        },
        timestamp=time.time(),
    )


@router.delete("/cleanup")
def cleanup_worktime(
    session: Session = Depends(get_db_session),
    _user: dict = Depends(require_admin),
):
    """Delete all worktime records, therblig details, and reset process segment references.

    Requires admin role. Does NOT delete raw process segments.
    """
    from app.models.database import TherbligDetail, WorktimeRecord, ProcessSegment

    # Temporarily disassociate process_segments from worktime_records
    (
        session.query(ProcessSegment)
        .filter(ProcessSegment.worktime_record_id.isnot(None))
        .update({"worktime_record_id": None}, synchronize_session=False)
    )

    # Delete TherbligDetail (cascade handles via relationship, but explicit is safer)
    deleted_therblig = session.query(TherbligDetail).delete(synchronize_session=False)

    # Delete WorktimeRecord (order matters: delete therblig first, then worktime_records)
    deleted_records = session.query(WorktimeRecord).delete(synchronize_session=False)

    session.commit()

    logger.info(
        "清理工时数据: 删除了 %d 条动素明细, %d 条工时记录",
        deleted_therblig,
        deleted_records,
    )
    return ApiResponse(
        data={
            "deletedTherbligDetails": deleted_therblig,
            "deletedWorktimeRecords": deleted_records,
        },
        timestamp=time.time(),
    )


@router.get("/summary")
def get_worktime_summary(
    station: str = Query("all"),
    shift: str = Query("morning"),
    session: Session = Depends(get_db_session),
    _user: dict = Depends(require_read_all),
):
    """Get worktime summary statistics for a station and shift."""
    raw = worktime_aggregator.get_worktime_summary(session, station, shift)
    data = validate_response_data(WorktimeSummary, {
        "totalOps": raw.get("total_ops", 0),
        "avgEfficiency": round(raw.get("avg_efficiency", 0.0) * 100, 2),
        "wasteRatio": round(raw.get("waste_ratio", 0.0) * 100, 2),
        "totalStdTimeHours": raw.get("total_std_time_hours", 0.0),
    })
    return ApiResponse(data=data, timestamp=time.time())


@router.get("/operations")
def get_operations(
    station: str = Query("all"),
    shift: str = Query("morning"),
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    session: Session = Depends(get_db_session),
    _user: dict = Depends(require_read_all),
):
    """Get per-operation worktime records with pagination.

    Each record includes a ``wastePct`` field representing the percentage
    of time spent on non-value-added therblig elements
    (``TherbligDetail.is_waste == True``).
    """
    from sqlalchemy import case as sa_case, func as sa_func

    from app.models.database import TherbligDetail

    records, total = worktime_aggregator.get_operations(
        session, station, shift, page=page, page_size=page_size,
    )

    # ── Bulk wastePct calculation ────────────────────────────────────
    # Compute waste ratio for all returned records in a single query.
    record_ids = [r.id for r in records]
    if record_ids:
        waste_rows = (
            session.query(
                TherbligDetail.worktime_record_id,
                sa_func.sum(TherbligDetail.actual_ms).label("total_ms"),
                sa_func.sum(
                    sa_case(
                        (TherbligDetail.is_waste == True, TherbligDetail.actual_ms),
                        else_=0,
                    )
                ).label("waste_ms"),
            )
            .filter(TherbligDetail.worktime_record_id.in_(record_ids))
            .group_by(TherbligDetail.worktime_record_id)
            .all()
        )
        waste_map: dict = {
            row.worktime_record_id: {
                "waste_ms": float(row.waste_ms or 0),
                "total_ms": float(row.total_ms or 0),
            }
            for row in waste_rows
        }
    else:
        waste_map = {}

    items = []
    for r in records:
        w = waste_map.get(r.id, {"waste_ms": 0.0, "total_ms": 0.0})
        waste_pct = round(w["waste_ms"] / w["total_ms"] * 100, 2) if w["total_ms"] > 0 else 0.0
        items.append(validate_response_data(WorktimeOperation, {
            "id": r.id,
            "operation": r.operation,
            "station": r.station_id,
            "actual": round(max(r.actual_ms, 0.0) / 1000.0, 2),
            "standard": round(r.standard_ms / 1000.0, 2),
            "efficiency": round(r.efficiency * 100, 2),
            "modTotal": round(r.mod_total, 2),
            "wastePct": waste_pct,
        }))

    return ApiResponse(
        data=items,
        timestamp=time.time(),
    )


@router.get("/therblig/{operation_id}")
def get_therblig_detail(
    operation_id: int,
    session: Session = Depends(get_db_session),
    _user: dict = Depends(require_read_all),
):
    """Get Therblig breakdown for a specific worktime record."""
    from app.models.database import TherbligDetail

    details = (
        session.query(TherbligDetail)
        .filter_by(worktime_record_id=operation_id)
        .order_by(TherbligDetail.id)
        .all()
    )
    if not details:
        raise HTTPException(status_code=404, detail="Operation not found")

    rows = [
        {
            "id": d.id,
            "symbol": d.symbol,
            "name": d.name,
            "mod": round(d.mod, 2),
            "actual": round(d.actual_ms / 1000.0, 3),
            "pct": round(d.pct, 1),
            "isWaste": d.is_waste,
            "standardSeconds": round(d.mod * 0.129, 2),
        }
        for d in details
    ]

    from app.models.database import WorktimeRecord
    record = session.get(WorktimeRecord, operation_id)

    # MOD法 standard time & efficiency (计算下沉 — 前端不应复算)
    total_actual_s = sum(d.actual_ms for d in details) / 1000.0
    total_mod = sum(d.mod for d in details)
    standard_time = round(total_mod * 0.129, 2)  # MOD法秒
    efficiency = round(standard_time / total_actual_s * 100, 2) if total_actual_s > 0 else 0.0

    return ApiResponse(
        data={
            "allowanceRate": 0.15,
            "rows": rows,
            "operationId": operation_id,
            "operationName": record.operation if record else "",
            "standardTime": standard_time,
            "efficiency": efficiency,
        },
        timestamp=time.time(),
    )


@router.get("/recent")
def get_recent_worktime(
    limit: int = Query(10, ge=1, le=100),
    session: Session = Depends(get_db_session),
    _user: dict = Depends(require_read_all),
):
    """Get latest process segments with standard/efficiency from associated WorktimeRecord."""
    from app.models.database import ProcessSegment, WorktimeRecord

    rows = (
        session.query(
            ProcessSegment.id,
            ProcessSegment.action,
            ProcessSegment.station_id,
            ProcessSegment.duration_ms,
            WorktimeRecord.standard_ms,
            WorktimeRecord.efficiency,
        )
        .outerjoin(
            WorktimeRecord,
            ProcessSegment.worktime_record_id == WorktimeRecord.id,
        )
        .order_by(ProcessSegment.start_time.desc())
        .limit(limit)
        .all()
    )
    items = [
        {
            "id": row.id,
            "operation": row.action,
            "station": row.station_id,
            "actual": round(row.duration_ms / 1000.0, 1),  # ms → s
            "standard": round((row.standard_ms or 0.0) / 1000.0, 1),  # ms → s
            "efficiency": row.efficiency or 0.0,
        }
        for row in rows
    ]
    return ApiResponse(
        data=items,
        timestamp=time.time(),
    )


@router.get("/trend")
def get_worktime_trend(
    days: int = Query(7, ge=1, le=30),
    session: Session = Depends(get_db_session),
    _user: dict = Depends(require_read_all),
):
    """Get worktime trend over the past N days.

    Returns actual vs standard time per day for chart display.
    Uses a single GROUP BY (day, action) query to compute both
    total duration and per-action distribution in one pass.
    """
    from datetime import datetime, timedelta, timezone

    from app.models.database import ProcessSegment
    from sqlalchemy import func as sa_func
    from app.models.schemas import ActionLabel
    from app.services.therblig_mapper import map_action_to_therblig

    now = datetime.now(timezone.utc)
    day_start = now - timedelta(days=days - 1)
    start_ts = day_start.replace(hour=0, minute=0, second=0, microsecond=0)

    # Use DB-agnostic date function instead of SQLite-specific strftime
    date_col = _date_format_func(session, ProcessSegment.start_time)

    # Single query: GROUP BY (date, action) — replaces two separate GROUP BY queries
    rows = session.query(
        date_col.label("day"),
        ProcessSegment.action,
        sa_func.sum(ProcessSegment.duration_ms).label("duration_ms"),
        sa_func.count(ProcessSegment.id).label("cnt"),
    ).filter(
        ProcessSegment.start_time >= start_ts,
    ).group_by(
        date_col,
        ProcessSegment.action,
    ).all()

    # Aggregate in Python: per-day total duration + per-day action counts
    daily_map: dict = {}
    day_action_map: dict = {}
    for r in rows:
        if r.day not in daily_map:
            daily_map[r.day] = {"total_ms": 0, "count": 0}
        daily_map[r.day]["total_ms"] += float(r.duration_ms or 0)
        daily_map[r.day]["count"] += r.cnt or 0

        day_action_map.setdefault(r.day, {})[r.action] = r.cnt or 0

    # Generate labels in chronological order
    labels = []
    actual = []
    standard = []
    mod_unit = 0.129

    for i in range(days):
        day = day_start + timedelta(days=i)
        key = day.strftime("%Y-%m-%d")
        labels.append(day.strftime("%m-%d"))
        info = daily_map.get(key, {"total_ms": 0, "count": 0})
        actual.append(round(info["total_ms"] / 1000.0, 1))

        # Standard time estimate from action distribution
        total_std = 0.0
        actions = day_action_map.get(key, {})
        for action_name, count in actions.items():
            try:
                th = map_action_to_therblig(ActionLabel(action_name))
                total_std += th.mod_value * mod_unit * count
            except ValueError:
                pass
        standard.append(round(total_std, 1))

    return ApiResponse(
        data={"labels": labels, "actual": actual, "standard": standard},
        timestamp=time.time(),
    )


@router.get("/therblig-distribution")
def get_therblig_distribution(
    station: str = Query("all"),
    shift: str = Query("morning"),
    session: Session = Depends(get_db_session),
    _user: dict = Depends(require_read_all),
):
    """Get Therblig time distribution for pie chart."""
    data = worktime_aggregator.get_therblig_distribution(session, station, shift)
    return ApiResponse(data={"items": data}, timestamp=time.time())


from sqlalchemy import String as _String

def _date_format_func(session: Session, column, fmt: str = "%Y-%m-%d"):
    """Return a DB-agnostic date truncation expression for grouping.

    Uses ``func.date()`` / ``func.substr()`` which work across SQLite,
    PostgreSQL, and MySQL.

    Args:
        session: SQLAlchemy session (unused, kept for backwards compat).
        column:  Datetime column to truncate.
        fmt:     Desired format.
                 - "%%Y-%%m-%%d" (default) → YYYY-MM-DD via ``func.date()``
                 - "%%Y-%%m"              → YYYY-MM via ``func.substr(func.date(...), 1, 7)``
    """
    from sqlalchemy import func as sa_func
    if fmt == "%Y-%m":
        return sa_func.substr(sa_func.date(column), 1, 7)
    # Cast to string for cross-DB compatibility (SQLite→str, PG→str)
    return sa_func.cast(sa_func.date(column), _String)


@router.get("/boxplot")
def get_boxplot_stats(
    station: str = Query("all"),
    session: Session = Depends(get_db_session),
    _user: dict = Depends(require_read_all),
):
    """Get per-station boxplot statistics (five-number summary) grouped by shift."""
    data = worktime_aggregator.get_boxplot_stats(session, station)
    return ApiResponse(data=data, timestamp=time.time())


@router.get("/heatmap")
def get_heatmap_stats(
    station: str = Query("all"),
    session: Session = Depends(get_db_session),
    _user: dict = Depends(require_read_all),
):
    """Get per-station, per-hour waste ratio heatmap data."""
    data = worktime_aggregator.get_heatmap_stats(session, station)
    return ApiResponse(data=data, timestamp=time.time())
