"""
Worktime aggregation service.

Aggregates process segments into worktime records and generates Therblig
breakdowns.  This service is called after each segment event is emitted
by the process segmenter.
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Dict, List, Optional, Tuple

from sqlalchemy.orm import Session, joinedload

from app.models.database import (
    ProcessSegment,
    TherbligDetail,
    WorktimeRecord,
)
from app.models.schemas import (
    ActionLabel,
    ProcessSegmentSchema,
    ShiftName,
    TherbligRowSchema,
    WorktimeRecordSchema,
)
from app.services.therblig_mapper import map_action_to_therblig

logger = logging.getLogger(__name__)


def _determine_shift(dt: datetime) -> ShiftName:
    """Determine shift name from datetime (factory standard hours).

    Converts UTC to local time (UTC+8) before checking hour ranges.
    Factory shift schedule (local time):
      morning:   06:00-14:00
      afternoon: 14:00-22:00
      night:     22:00-06:00
    """
    from datetime import timedelta

    # Convert to UTC+8 (factory local time)
    dt_local = dt + timedelta(hours=8)
    hour = dt_local.hour
    if 6 <= hour < 14:
        return ShiftName.MORNING
    elif 14 <= hour < 22:
        return ShiftName.AFTERNOON
    else:
        return ShiftName.NIGHT


def _action_to_operation_name(action: ActionLabel) -> str:
    """Map action label to a human-readable operation name."""
    mapping = {
        ActionLabel.REACH: "reach",
        ActionLabel.GRASP: "grasp",
        ActionLabel.MOVE: "transport",
        ActionLabel.ASSEMBLE: "assembly",
        ActionLabel.RELEASE: "release",
        ActionLabel.INSPECT: "inspection",
        ActionLabel.WAIT: "waiting",
        ActionLabel.IDLE: "idle",
    }
    return mapping.get(action, "other")


def save_segment(
    session: Session,
    event: "SegmentEvent",
) -> ProcessSegment:
    """
    Persist a segment event to the database.

    Args:
        session: SQLAlchemy session.
        event:   SegmentEvent from the process segmenter.

    Returns:
        The created ProcessSegment ORM object.
    """
    start_dt = datetime.fromtimestamp(event.start_time, tz=timezone.utc)
    end_dt = datetime.fromtimestamp(event.end_time, tz=timezone.utc)
    shift = _determine_shift(start_dt)

    therblig = map_action_to_therblig(event.action)

    segment = ProcessSegment(
        camera_id=event.camera_id,
        station_id=event.station_id,
        action=event.action.value,
        therblig_symbol=therblig.symbol.value,
        start_time=start_dt,
        end_time=end_dt,
        duration_ms=event.duration_ms,
        confidence=event.confidence,
        shift=shift.value,
    )
    session.add(segment)
    session.commit()
    session.refresh(segment)
    return segment


def get_recent_segments(
    session: Session,
    station_id: Optional[str] = None,
    limit: int = 50,
) -> List[ProcessSegment]:
    """Query recent process segments from the database."""
    query = session.query(ProcessSegment).order_by(
        ProcessSegment.start_time.desc()
    )
    if station_id and station_id != "all":
        query = query.filter(ProcessSegment.station_id == station_id)
    return query.limit(limit).all()


def get_operations(
    session: Session,
    station_id: Optional[str] = None,
    shift: str = "morning",
    page: int = 1,
    page_size: int = 20,
) -> tuple[List[WorktimeRecord], int]:
    """
    Get aggregated worktime records grouped by operation with SQL pagination.

    This queries the worktime_records table.  Records are created by
    the `aggregate_segments` function.

    Returns:
        (records, total_count) tuple for paginated response.
    """
    base_query = session.query(WorktimeRecord).filter(
        WorktimeRecord.shift == shift
    )
    if station_id and station_id != "all":
        base_query = base_query.filter(WorktimeRecord.station_id == station_id)

    total = base_query.count()
    offset = (page - 1) * page_size
    records = base_query.order_by(
        WorktimeRecord.created_at.desc()
    ).offset(offset).limit(page_size).all()

    return records, total


def aggregate_segments(
    session: Session,
    station_id: Optional[str] = None,
    shift: str = "morning",
) -> List[WorktimeRecord]:
    """
    Aggregate raw process segments into per-operation worktime records.

    Groups segments by (action, station_id, shift) and computes:
      - total actual time (sum of segment durations)
      - standard time (from Therblig MOD values)
      - efficiency (standard / actual)
      - MOD total
    """
    query = session.query(ProcessSegment).filter(
        ProcessSegment.shift == shift
    )
    if station_id and station_id != "all":
        query = query.filter(ProcessSegment.station_id == station_id)

    segments = query.order_by(ProcessSegment.start_time).all()

    # Group by action
    groups: Dict[str, List[ProcessSegment]] = {}
    for seg in segments:
        key = seg.action
        if key not in groups:
            groups[key] = []
        groups[key].append(seg)

    mod_unit = 0.129  # 1 MOD = 0.129 seconds

    # P1 #48: Batch-load existing worktime records to avoid N+1 queries
    existing_records = (
        session.query(WorktimeRecord)
        .filter(WorktimeRecord.shift == shift)
        .all()
    )
    existing_map: Dict[str, WorktimeRecord] = {}
    for rec in existing_records:
        key = (rec.operation, rec.station_id or "default")
        existing_map[key] = rec

    records = []

    for action, segs in groups.items():
        total_actual_ms = sum(s.duration_ms for s in segs)
        total_actual_s = total_actual_ms / 1000.0

        # Compute standard time from Therblig MOD
        action_enum = ActionLabel(action)
        therblig = map_action_to_therblig(action_enum)
        standard_ms = therblig.mod_value * mod_unit * 1000 * len(segs)
        mod_total = therblig.mod_value * len(segs)

        efficiency = 0.0
        if total_actual_ms > 0:
            efficiency = standard_ms / total_actual_ms

        operation_name = _action_to_operation_name(action_enum)

        # Find or create worktime record (P1 #48: use preloaded map)
        lookup_key = (operation_name, station_id or "default")
        existing = existing_map.get(lookup_key)

        if existing:
            existing.actual_ms = total_actual_ms
            existing.standard_ms = standard_ms
            existing.efficiency = min(efficiency, 1.0) if efficiency > 1.0 else efficiency
            existing.mod_total = mod_total
            session.add(existing)
            record = existing
        else:
            record = WorktimeRecord(
                operation=operation_name,
                station_id=station_id or "default",
                actual_ms=total_actual_ms,
                standard_ms=standard_ms,
                efficiency=efficiency,
                mod_total=mod_total,
                shift=shift,
            )
            session.add(record)

        records.append(record)

    # Generate Therblig detail rows for all records (both new and updated)
    session.flush()  # ensure all record IDs are populated
    for record in records:
        # Determine what to create BEFORE deleting (P1: avoid data loss on failure)
        action_value = None
        for av, op_name in {
            ActionLabel.REACH.value: "reach",
            ActionLabel.GRASP.value: "grasp",
            ActionLabel.MOVE.value: "transport",
            ActionLabel.ASSEMBLE.value: "assembly",
            ActionLabel.RELEASE.value: "release",
            ActionLabel.INSPECT.value: "inspection",
            ActionLabel.WAIT.value: "waiting",
            ActionLabel.IDLE.value: "idle",
        }.items():
            if op_name == record.operation:
                action_value = av
                break
        if action_value is None:
            continue
        try:
            therblig = map_action_to_therblig(ActionLabel(action_value))
        except ValueError:
            continue
        segs_for_action = groups.get(action_value, [])
        if not segs_for_action:
            continue
        # Wrap delete+rebuild in savepoint so partial failures don't lose data
        total_actual_ms = sum(s.duration_ms for s in segs_for_action)
        try:
            with session.begin_nested():
                session.query(TherbligDetail).filter_by(
                    worktime_record_id=record.id
                ).delete()
                for seg in segs_for_action:
                    detail = TherbligDetail(
                        worktime_record_id=record.id,
                        symbol=therblig.symbol.value,
                        name=therblig.name,
                        mod=therblig.mod_value,
                        actual_ms=seg.duration_ms,
                        pct=(seg.duration_ms / total_actual_ms * 100) if total_actual_ms > 0 else 0.0,
                        is_waste=therblig.is_waste,
                    )
                    session.add(detail)
        except Exception as exc:
            logger.warning(
                "Failed to rebuild therblig details for record %s: %s",
                record.id, exc,
            )
            # Savepoint automatically rolls back: old TherbligDetails survive

    session.commit()
    return records


def get_worktime_summary(
    session: Session,
    station_id: Optional[str] = None,
    shift: str = "morning",
) -> Dict:
    """
    Get worktime summary statistics.

    Returns dict with:
      - total_ops: total number of operations
      - avg_efficiency: average efficiency across operations
      - waste_ratio: fraction of time classified as waste
      - total_std_time_hours: total standard time in hours
    """
    records, _ = get_operations(session, station_id, shift)

    if not records:
        return {
            "total_ops": 0,
            "avg_efficiency": 0.0,
            "waste_ratio": 0.0,
            "total_std_time_hours": 0.0,
        }

    total_ops = len(records)
    avg_efficiency = sum(r.efficiency for r in records) / total_ops

    # Waste = wait + idle (operation field stores mapped names)
    waste_operations = {"waiting", "idle"}
    waste_records = [r for r in records if r.operation in waste_operations]
    total_actual = sum(r.actual_ms for r in records)
    waste_actual = sum(r.actual_ms for r in waste_records)
    waste_ratio = waste_actual / total_actual if total_actual > 0 else 0.0

    total_std_ms = sum(r.standard_ms for r in records)
    total_std_hours = total_std_ms / 1000 / 3600

    return {
        "total_ops": total_ops,
        "avg_efficiency": round(avg_efficiency, 4),
        "waste_ratio": round(waste_ratio, 4),
        "total_std_time_hours": round(total_std_hours, 4),
    }


def get_therblig_distribution(
    session: Session,
    station_id: Optional[str] = None,
    shift: str = "morning",
) -> List[Dict]:
    """
    Get Therblig distribution across all operations.

    Returns list of dicts: { symbol, name, pct, color, is_waste }
    """
    records, _ = get_operations(session, station_id, shift)

    # P1 #48: Eagerly load therblig_details to avoid N+1 queries
    if records:
        record_ids = [r.id for r in records]
        all_details = (
            session.query(TherbligDetail)
            .filter(TherbligDetail.worktime_record_id.in_(record_ids))
            .all()
        )
        # Build a lookup: record_id -> list of details
        details_map: Dict[int, List[TherbligDetail]] = {}
        for d in all_details:
            details_map.setdefault(d.worktime_record_id, []).append(d)
    else:
        details_map = {}

    # Collect all therblig details
    symbol_totals: Dict[str, Dict] = {}
    for record in records:
        details = details_map.get(record.id, [])
        for d in details:
            if d.symbol not in symbol_totals:
                symbol_totals[d.symbol] = {
                    "symbol": d.symbol,
                    "name": d.name,
                    "total_ms": 0.0,
                    "is_waste": d.is_waste,
                }
            symbol_totals[d.symbol]["total_ms"] += d.actual_ms

    total_ms = sum(v["total_ms"] for v in symbol_totals.values())
    if total_ms == 0:
        return []

    # Color palette for chart display
    colors = {
        "R": "#4CAF50",
        "M": "#2196F3",
        "G": "#FF9800",
        "RL": "#9C27B0",
        "A": "#F44336",
        "I": "#00BCD4",
        "UD": "#FFC107",
        "AD": "#F44336",
        "Pn": "#607D8B",
        "Sh": "#795548",
        "St": "#795548",
        "P": "#3F51B5",
        "PP": "#3F51B5",
        "U": "#009688",
        "DA": "#FF5722",
        "H": "#9E9E9E",
        "Rst": "#9E9E9E",
        "F": "#795548",
    }

    result = []
    for sym, data in sorted(symbol_totals.items(), key=lambda x: -x[1]["total_ms"]):
        pct = round(data["total_ms"] / total_ms * 100, 1)
        result.append({
            "symbol": sym,
            "name": data["name"],
            "pct": pct,
            "color": colors.get(sym, "#999999"),
            "is_waste": data["is_waste"],
        })

    return result


def get_boxplot_stats(
    session: Session,
    station_id: Optional[str] = None,
) -> Dict:
    """
    Compute per-station boxplot statistics (five-number summary) grouped by shift.

    Returns dict:
      {
        "stations": ["WS-01", "WS-02", ...],
        "shifts": ["morning", "afternoon", "night"],
        "morning": [[min, Q1, median, Q3, max], ...],  # one per station
        "afternoon": [...],
        "night": [...]
      }

    The boxplot values are computed from the actual duration_ms of all
    process segments for each (station, shift) combination.  When a
    (station, shift) group has fewer than 5 data points the function
    still returns the five-number summary (it just may be less useful
    for spotting outliers).
    """
    query = session.query(ProcessSegment)
    if station_id and station_id != "all":
        query = query.filter(ProcessSegment.station_id == station_id)

    segments = query.all()

    # Group durations by (station_id, shift)
    groups: Dict[Tuple[str, str], List[float]] = {}
    for seg in segments:
        key = (seg.station_id, seg.shift)
        groups.setdefault(key, []).append(seg.duration_ms)

    # Collect unique stations and shifts in deterministic order
    all_stations = sorted({k[0] for k in groups})
    all_shifts = sorted({k[1] for k in groups})

    def _five_number(values: List[float]):
        """Compute [min, Q1, median, Q3, max] from a list of floats."""
        if not values:
            return None
        s = sorted(values)
        n = len(s)
        minimum = s[0]
        maximum = s[-1]
        if n == 1:
            med = s[0]
            return [minimum, med, med, med, maximum]
        # Median
        mid = n // 2
        if n % 2 == 0:
            median = (s[mid - 1] + s[mid]) / 2.0
        else:
            median = s[mid]
        # Q1 / Q3 -- use the "inclusive" method (numpy default)
        def _percentile(sorted_vals, pct):
            """Linear interpolation percentile on pre-sorted list."""
            idx = (len(sorted_vals) - 1) * pct
            lo = int(idx)
            hi = min(lo + 1, len(sorted_vals) - 1)
            frac = idx - lo
            return sorted_vals[lo] + frac * (sorted_vals[hi] - sorted_vals[lo])

        q1 = _percentile(s, 0.25)
        q3 = _percentile(s, 0.75)
        return [round(minimum, 2), round(q1, 2), round(median, 2), round(q3, 2), round(maximum, 2)]

    result: Dict = {"stations": all_stations, "shifts": all_shifts}
    for shift_name in all_shifts:
        shift_data = []
        for st in all_stations:
            vals = groups.get((st, shift_name), [])
            box = _five_number(vals)
            shift_data.append(box)
        result[shift_name] = shift_data

    return result


def get_heatmap_stats(
    session: Session,
    station_id: Optional[str] = None,
) -> Dict:
    """
    Compute per-station, per-hour waste (wait+idle) ratio as a heatmap.

    Returns dict:
      {
        "stations": ["WS-01", ...],
        "hours": ["1h", "2h", ...],      # relative hour within shift
        "data": [[hour_idx, station_idx, waste_pct], ...]
      }

    Waste ratio = total duration of wait+idle segments / total duration of
    all segments for that (station, hour) bucket.  Hour is derived from
    ``start_time`` and mapped to the shift-relative hour index (0-7 for a
    typical 8-hour shift window).

    If there are no segments for a (station, hour) cell the cell is omitted
    from the data array, so the frontend can show it as "no data" instead
    of zero.
    """
    query = session.query(ProcessSegment)
    if station_id and station_id != "all":
        query = query.filter(ProcessSegment.station_id == station_id)

    segments = query.all()

    if not segments:
        return {"stations": [], "hours": [], "data": []}

    waste_actions = {"wait", "idle"}

    # Group by (station, shift_relative_hour)
    # shift_relative_hour: 0-7 mapping based on shift
    buckets: Dict[Tuple[str, int], Dict[str, float]] = {}  # (station, hour) -> {total, waste}

    for seg in segments:
        st = seg.station_id
        # Convert UTC to local time (UTC+8) for shift-relative hour
        from datetime import timedelta as _td
        local_dt = seg.start_time + _td(hours=8)
        hour = local_dt.hour
        if 6 <= hour < 14:
            shift_offset = hour - 6
        elif 14 <= hour < 22:
            shift_offset = hour - 14
        else:
            # Night shift: 22-6 wraps; map 22-23 -> 0-1, 0-5 -> 2-7
            shift_offset = (hour - 22) % 8

        h_idx = min(shift_offset, 7)  # clamp to 0-7
        key = (st, h_idx)
        bucket = buckets.setdefault(key, {"total": 0.0, "waste": 0.0})
        bucket["total"] += seg.duration_ms
        if seg.action in waste_actions:
            bucket["waste"] += seg.duration_ms

    all_stations = sorted({k[0] for k in buckets})
    max_hour = max(k[1] for k in buckets) if buckets else 7
    hours = [f"{i + 1}h" for i in range(max_hour + 1)]

    data = []
    for (st, h_idx), bucket in sorted(buckets.items()):
        if bucket["total"] > 0:
            pct = round(bucket["waste"] / bucket["total"] * 100, 1)
        else:
            pct = 0.0
        st_idx = all_stations.index(st)
        data.append([h_idx, st_idx, pct])

    return {"stations": all_stations, "hours": hours, "data": data}
