"""Anomaly detection API routes.

Endpoints:
  GET /api/anomaly/events  - query historical anomaly events
  GET /api/anomaly/stats   - anomaly detection statistics
"""

from __future__ import annotations

import logging
import time
import threading
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel
from sqlalchemy import func
from sqlalchemy.orm import Session

from app.api.deps import get_db_session, require_read_all
from app.models.database import AnomalyEvent
from app.models.schemas import ApiResponse

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/anomaly", tags=["anomaly"])

# Backward-compatible in-memory fallback for callers that don't have a session.
# Stream consumers should prefer add_anomaly_event_db().
_anomaly_store: List[Dict[str, Any]] = []
_anomaly_store_lock = threading.Lock()  # N-P1-13: thread safety for concurrent access
_MAX_STORE_SIZE = 1000


def add_anomaly_event(event_dict: Dict[str, Any]) -> None:
    """Add an anomaly event from Stream consumer (in-memory fallback).

    Called by ActionEventConsumer when AnomalyDetector flags an anomaly.
    For persistence across restarts, use add_anomaly_event_db() instead.
    """
    with _anomaly_store_lock:
        _anomaly_store.append(event_dict)
        if len(_anomaly_store) > _MAX_STORE_SIZE:
            del _anomaly_store[: len(_anomaly_store) - _MAX_STORE_SIZE]


def add_anomaly_event_db(session: Session, event_dict: Dict[str, Any]) -> None:
    """Persist an anomaly event to SQLite (P1 #40).

    Called by ActionEventConsumer with a DB session for durability.
    """
    try:
        evt = AnomalyEvent(
            station_id=event_dict.get("station_id", ""),
            action=event_dict.get("action", ""),
            anomaly_type=event_dict.get("anomaly_type", "duration_outlier"),
            duration_ms=event_dict.get("duration_ms", 0.0),
            mean_duration=event_dict.get("mean_duration", 0.0),
            std_duration=event_dict.get("std_duration", 0.0),
            deviation_sigma=event_dict.get("deviation_sigma", 0.0),
            event_ts=event_dict.get("timestamp", 0.0),
        )
        session.add(evt)
        session.commit()
    except Exception as exc:
        session.rollback()
        logger.error("Failed to persist anomaly event to DB: %s", exc)
        add_anomaly_event(event_dict)


class AnomalyEventResponse(BaseModel):
    """Response model for a single anomaly event."""
    id: str
    station_id: str
    action: str
    anomaly_type: str
    duration_ms: float
    mean_duration: float
    std_duration: float
    deviation_sigma: float
    timestamp: float


@router.get("/events")
def get_anomaly_events(
    station_id: Optional[str] = Query(None, description="Filter by station"),
    limit: int = Query(20, ge=1, le=100, description="Max events to return"),
    _user: dict = Depends(require_read_all),
    session: Session = Depends(get_db_session),
):
    """Query historical anomaly events.

    Returns the most recent anomaly events, optionally filtered by station.
    Reads from the persisted AnomalyEvent table (P1 #40).
    """
    query = session.query(AnomalyEvent)

    if station_id:
        query = query.filter(AnomalyEvent.station_id == station_id)

    total = query.count()

    events = (
        query.order_by(AnomalyEvent.event_ts.desc())
        .limit(limit)
        .all()
    )

    event_list = []
    for e in events:
        event_list.append({
            "id": str(e.id),
            "station_id": e.station_id,
            "action": e.action,
            "anomaly_type": e.anomaly_type,
            "duration_ms": e.duration_ms,
            "mean_duration": e.mean_duration,
            "std_duration": e.std_duration,
            "deviation_sigma": e.deviation_sigma,
            "timestamp": e.event_ts,
        })

    # Also include any in-memory events not yet persisted
    with _anomaly_store_lock:
        memory_snapshot = list(_anomaly_store)
    if memory_snapshot:
        for e in memory_snapshot:
            if station_id and e.get("station_id") != station_id:
                continue
            event_list.append(e)

    # Sort by timestamp descending and limit
    event_list.sort(key=lambda e: e.get("timestamp", 0), reverse=True)
    event_list = event_list[:limit]

    return ApiResponse(
        data={
            "events": event_list,
            "total": total + len(memory_snapshot),
            "returned": len(event_list),
        },
        timestamp=time.time(),
    )


@router.get("/stats")
def get_anomaly_stats(
    _user: dict = Depends(require_read_all),
    session: Session = Depends(get_db_session),
):
    """Get anomaly detection statistics.

    Returns counts by station and action from persisted data.
    """
    # Query from database
    station_rows = (
        session.query(
            AnomalyEvent.station_id,
            func.count(AnomalyEvent.id),
        )
        .group_by(AnomalyEvent.station_id)
        .all()
    )
    action_rows = (
        session.query(
            AnomalyEvent.action,
            func.count(AnomalyEvent.id),
        )
        .group_by(AnomalyEvent.action)
        .all()
    )

    station_counts: Dict[str, int] = {r[0]: r[1] for r in station_rows}
    action_counts: Dict[str, int] = {r[0]: r[1] for r in action_rows}
    total_db = sum(r[1] for r in station_rows)

    # Merge in-memory counts
    with _anomaly_store_lock:
        memory_events = list(_anomaly_store)
    for e in memory_events:
        sid = e.get("station_id", "unknown")
        action = e.get("action", "unknown")
        station_counts[sid] = station_counts.get(sid, 0) + 1
        action_counts[action] = action_counts.get(action, 0) + 1

    total = total_db + len(memory_events)

    return ApiResponse(
        data={
            "total_anomalies": total,
            "by_station": station_counts,
            "by_action": action_counts,
        },
        timestamp=time.time(),
    )
