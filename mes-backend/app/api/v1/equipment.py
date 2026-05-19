"""
Equipment management API routes.

Endpoints:
  GET    /api/equipment       - list all equipment
  GET    /api/equipment/stats - equipment status overview
  POST   /api/equipment       - create new equipment
  DELETE /api/equipment/{id}  - delete equipment
"""

from __future__ import annotations

import logging
import time
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import case, func
from sqlalchemy.orm import Session

from app.models.database import get_session, Equipment
from app.models.schemas import ApiResponse, EquipmentCreate, EquipmentUpdate
from app.api.deps import get_db_session, require_auth, require_admin, require_read_all

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/equipment", tags=["equipment"])




def _eq_to_dict(eq: Equipment) -> dict:
    """Convert ORM Equipment to API response dict."""
    return {
        "id": eq.id,
        "name": eq.name,
        "model": eq.model,
        "workshop": eq.workshop,
        "status": eq.status,
        "oee": round(eq.oee, 4),
        "utilization": round(eq.utilization, 4),
        "faultCount": eq.fault_count,
        "mtbf": round(eq.mtbf_hours, 1),
        "todayUtil": round(eq.today_util_pct, 4),
        "nextMaint": eq.next_maintenance,
    }


@router.get("")
def list_equipment(
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    session: Session = Depends(get_db_session),
    _user: dict = Depends(require_read_all),
):
    """List all equipment/workstations with pagination."""
    query = session.query(Equipment)
    total = query.count()
    offset = (page - 1) * page_size
    items = [_eq_to_dict(e) for e in query.order_by(Equipment.id).offset(offset).limit(page_size).all()]
    return ApiResponse(data={"items": items, "total": total, "page": page, "pageSize": page_size}, timestamp=time.time())


@router.get("/stats")
def equipment_stats(
    session: Session = Depends(get_db_session),
    _user: dict = Depends(require_read_all),
):
    """Get equipment status overview."""
    # N-P1-10: Merge 4 independent COUNT queries into a single CASE WHEN
    stats = session.query(
        func.count(Equipment.id).label("total"),
        func.sum(case((Equipment.status == "running", 1), else_=0)).label("running"),
        func.sum(case((Equipment.status == "idle", 1), else_=0)).label("idle"),
        func.sum(case((Equipment.status == "maintenance", 1), else_=0)).label("maintenance"),
        func.avg(Equipment.oee).label("avg_oee"),
    ).first()

    return ApiResponse(
        data={
            "running": int(stats.running or 0),
            "idle": int(stats.idle or 0),
            "maintenance": int(stats.maintenance or 0),
            "avgOee": round(float(stats.avg_oee or 0), 4),
        },
        timestamp=time.time(),
    )


@router.post("")
def create_equipment(
    req: EquipmentCreate,
    session: Session = Depends(get_db_session),
    _user: dict = Depends(require_admin),
):
    """Create a new equipment entry."""
    existing = session.query(Equipment).filter(Equipment.name == req.name).first()
    if existing:
        raise HTTPException(status_code=409, detail="Equipment name already exists")

    eq = Equipment(
        name=req.name,
        model=req.model,
        workshop=req.workshop,
    )
    session.add(eq)
    session.commit()
    session.refresh(eq)

    logger.info("Equipment created: %s", eq.name)
    return ApiResponse(data=_eq_to_dict(eq), timestamp=time.time())


@router.put("/{equipment_id}")
def update_equipment(
    equipment_id: int,
    req: EquipmentUpdate,
    session: Session = Depends(get_db_session),
    _user: dict = Depends(require_admin),
):
    """Update an existing equipment entry. Only provided fields are changed."""
    eq = session.get(Equipment, equipment_id)
    if not eq:
        raise HTTPException(status_code=404, detail="Equipment not found")

    update_data = req.model_dump(exclude_none=True)
    if not update_data:
        raise HTTPException(status_code=400, detail="No fields to update")

    for field, value in update_data.items():
        setattr(eq, field, value)
    session.commit()
    session.refresh(eq)

    logger.info("Equipment updated: id=%d name=%s fields=%s", equipment_id, eq.name, list(update_data.keys()))
    return ApiResponse(data=_eq_to_dict(eq), timestamp=time.time())


@router.delete("/{equipment_id}")
def delete_equipment(
    equipment_id: int,
    session: Session = Depends(get_db_session),
    _user: dict = Depends(require_admin),
):
    """Delete an equipment entry."""
    eq = session.get(Equipment, equipment_id)
    if not eq:
        raise HTTPException(status_code=404, detail="Equipment not found")

    session.delete(eq)
    session.commit()

    logger.info("Equipment deleted: id=%d name=%s", equipment_id, eq.name)
    return ApiResponse(data=None, message="Equipment deleted", timestamp=time.time())
