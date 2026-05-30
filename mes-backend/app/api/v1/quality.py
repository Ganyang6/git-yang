"""
Quality check CRUD API routes.

Endpoints:
  GET    /api/quality/checks          - list quality checks with filters
  GET    /api/quality/checks/{id}     - get single check detail
  POST   /api/quality/checks          - create new quality check
  PUT    /api/quality/checks/{id}     - update existing check
  DELETE /api/quality/checks/{id}     - delete a quality check
"""

from __future__ import annotations

import logging
import time
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from app.models.database import Order
from app.models.quality_check import QualityCheck
from app.models.schemas import ApiResponse, QualityCheckCreate, QualityCheckUpdate
from app.api.deps import get_db_session, require_auth, require_admin

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/quality", tags=["quality"])


def _check_to_dict(check: QualityCheck) -> dict:
    """Convert ORM QualityCheck to API response dict."""
    return {
        "id": check.id,
        "orderId": check.order_id,
        "checkedQty": check.checked_qty,
        "okQty": check.ok_qty,
        "defectQty": check.defect_qty,
        "defectType": check.defect_type or "",
        "inspector": check.inspector or "",
        "stationId": check.station_id or "",
        "notes": check.notes or "",
        "checkedAt": check.checked_at.isoformat() if check.checked_at else "",
        "createdAt": check.created_at.isoformat() if check.created_at else "",
        "updatedAt": check.updated_at.isoformat() if check.updated_at else "",
    }


@router.get("/checks")
def list_checks(
    order_id: Optional[int] = Query(None, gt=0),
    page: int = Query(1, ge=1),
    pageSize: int = Query(20, ge=1, le=100),
    session: Session = Depends(get_db_session),
    _user: dict = Depends(require_auth),
):
    """List quality checks with optional order_id filter and pagination."""
    query = session.query(QualityCheck)

    if order_id is not None:
        query = query.filter(QualityCheck.order_id == order_id)

    total = query.count()
    items = (
        query.order_by(QualityCheck.id.desc())
        .offset((page - 1) * pageSize)
        .limit(pageSize)
        .all()
    )

    return ApiResponse(
        data={
            "items": [_check_to_dict(c) for c in items],
            "total": total,
            "page": page,
            "pageSize": pageSize,
        },
        timestamp=time.time(),
    )


@router.get("/checks/{check_id}")
def get_check(
    check_id: int,
    session: Session = Depends(get_db_session),
    _user: dict = Depends(require_auth),
):
    """Get a single quality check by ID."""
    check = session.get(QualityCheck, check_id)
    if not check:
        raise HTTPException(status_code=404, detail="Quality check not found")
    return ApiResponse(data=_check_to_dict(check), timestamp=time.time())


@router.post("/checks")
def create_check(
    req: QualityCheckCreate,
    session: Session = Depends(get_db_session),
    _user: dict = Depends(require_admin),
):
    """Create a new quality check record.

    Validates that the referenced order exists before creating.
    """
    order = session.get(Order, req.order_id)
    if not order:
        raise HTTPException(
            status_code=404,
            detail=f"Order with id {req.order_id} not found",
        )

    # Defensive: double-check qty consistency (pydantic validator already catches this)
    if req.ok_qty + req.defect_qty > req.checked_qty:
        raise HTTPException(
            status_code=400,
            detail="ok_qty + defect_qty must not exceed checked_qty",
        )

    from datetime import datetime

    checked_at = None
    if req.checked_at:
        try:
            checked_at = datetime.fromisoformat(req.checked_at)
        except ValueError:
            raise HTTPException(
                status_code=400,
                detail="checked_at must be a valid ISO datetime string",
            )

    check = QualityCheck(
        order_id=req.order_id,
        checked_qty=req.checked_qty,
        ok_qty=req.ok_qty,
        defect_qty=req.defect_qty,
        defect_type=req.defect_type,
        inspector=req.inspector,
        station_id=req.station_id,
        notes=req.notes,
        checked_at=checked_at,
    )
    session.add(check)
    session.commit()
    session.refresh(check)

    logger.info(
        "Quality check created: order=%d, ok=%d, defect=%d",
        check.order_id, check.ok_qty, check.defect_qty,
    )
    return ApiResponse(data=_check_to_dict(check), timestamp=time.time())


@router.put("/checks/{check_id}")
def update_check(
    check_id: int,
    req: QualityCheckUpdate,
    session: Session = Depends(get_db_session),
    _user: dict = Depends(require_admin),
):
    """Update an existing quality check."""
    check = session.get(QualityCheck, check_id)
    if not check:
        raise HTTPException(status_code=404, detail="Quality check not found")

    update_data = req.model_dump(exclude_none=True)

    # Defensive: validate qty consistency (pydantic validator already catches when all 3 fields present)
    final_checked = update_data.get("checked_qty", check.checked_qty)
    final_ok = update_data.get("ok_qty", check.ok_qty)
    final_defect = update_data.get("defect_qty", check.defect_qty)
    if final_ok + final_defect > final_checked:
        raise HTTPException(
            status_code=400,
            detail="ok_qty + defect_qty must not exceed checked_qty",
        )

    if "checked_at" in update_data and update_data["checked_at"]:
        from datetime import datetime
        try:
            update_data["checked_at"] = datetime.fromisoformat(update_data["checked_at"])
        except ValueError:
            raise HTTPException(
                status_code=400,
                detail="checked_at must be a valid ISO datetime string",
            )

    from datetime import datetime, timezone
    update_data["updated_at"] = datetime.now(timezone.utc)

    for key, value in update_data.items():
        if hasattr(check, key):
            setattr(check, key, value)

    session.commit()
    session.refresh(check)

    logger.info("Quality check updated: id=%d", check_id)
    return ApiResponse(data=_check_to_dict(check), timestamp=time.time())


@router.delete("/checks/{check_id}")
def delete_check(
    check_id: int,
    session: Session = Depends(get_db_session),
    _user: dict = Depends(require_admin),
):
    """Delete a quality check."""
    check = session.get(QualityCheck, check_id)
    if not check:
        raise HTTPException(status_code=404, detail="Quality check not found")

    session.delete(check)
    session.commit()

    logger.info("Quality check deleted: id=%d", check_id)
    return ApiResponse(data=None, message="Quality check deleted", timestamp=time.time())
