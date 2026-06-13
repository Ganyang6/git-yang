"""
Station management API routes.

Endpoints:
  GET    /api/stations         - list all stations
  POST   /api/stations         - create new station
  PUT    /api/stations/{id}    - update station (name unchanged)
  DELETE /api/stations/{id}    - delete station
"""

from __future__ import annotations

import logging
import time
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from app.models.database import get_session, Station, ProcessSegment
from app.models.schemas import ApiResponse, StationCreate, StationUpdate, StationResponse
from app.api.deps import get_db_session, require_read_all

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/stations", tags=["stations"])


@router.get("")
def list_stations(
    session: Session = Depends(get_db_session),
    _user: dict = Depends(require_read_all),
):
    """List all stations."""
    stations = session.query(Station).order_by(Station.name, Station.line, Station.shift).all()
    data = [
        StationResponse(
            id=s.id,
            name=s.name,
            worker=s.worker,
            line=s.line,
            shift=s.shift,
        ).model_dump()
        for s in stations
    ]
    return ApiResponse(data=data, timestamp=time.time())


@router.post("")
def create_station(
    body: StationCreate,
    session: Session = Depends(get_db_session),
    _user: dict = Depends(require_read_all),
):
    """Create a new station."""
    # Check uniqueness
    existing = session.query(Station).filter(
        Station.name == body.name,
        Station.line == body.line,
        Station.shift == body.shift,
    ).first()
    if existing:
        raise HTTPException(
            status_code=409,
            detail=f"Station with name='{body.name}', line='{body.line}', shift='{body.shift}' already exists",
        )
    station = Station(
        name=body.name,
        worker=body.worker,
        line=body.line,
        shift=body.shift,
    )
    session.add(station)
    session.commit()
    session.refresh(station)
    return ApiResponse(
        data=StationResponse(
            id=station.id,
            name=station.name,
            worker=station.worker,
            line=station.line,
            shift=station.shift,
        ).model_dump(),
        timestamp=time.time(),
    )


@router.put("/{station_id}")
def update_station(
    station_id: int,
    body: StationUpdate,
    session: Session = Depends(get_db_session),
    _user: dict = Depends(require_read_all),
):
    """Update a station (cannot change name)."""
    station = session.query(Station).filter(Station.id == station_id).first()
    if not station:
        raise HTTPException(status_code=404, detail="Station not found")

    if body.worker is not None:
        station.worker = body.worker
    if body.line is not None:
        station.line = body.line
    if body.shift is not None:
        station.shift = body.shift

    session.commit()
    session.refresh(station)
    return ApiResponse(
        data=StationResponse(
            id=station.id,
            name=station.name,
            worker=station.worker,
            line=station.line,
            shift=station.shift,
        ).model_dump(),
        timestamp=time.time(),
    )


@router.delete("/{station_id}")
def delete_station(
    station_id: int,
    session: Session = Depends(get_db_session),
    _user: dict = Depends(require_read_all),
):
    """Delete a station.

    If ProcessSegment records reference this station's name, the response
    includes a warning so the frontend can alert the user.
    """
    station = session.query(Station).filter(Station.id == station_id).first()
    if not station:
        raise HTTPException(status_code=404, detail="Station not found")

    # Check for related ProcessSegment data
    seg_count = session.query(ProcessSegment).filter(
        ProcessSegment.station_id == station.name
    ).count()

    result = {"deleted": True}
    if seg_count > 0:
        result["warning"] = f"有 {seg_count} 条历史记录将失去工位关联"

    session.delete(station)
    session.commit()
    return ApiResponse(data=result, timestamp=time.time())
