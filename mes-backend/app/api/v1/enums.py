"""
Enumeration lookup API endpoints.

Provides read-only access to enum/meta data used by customers and orders.
All endpoints return is_active=True records with id, code, name fields.

Endpoints:
  GET /api/enums/customers/types     - list active customer types
  GET /api/enums/customers/levels    - list active customer levels
  GET /api/enums/orders/statuses     - list active order statuses
  GET /api/enums/orders/priorities   - list active order priorities
"""

from __future__ import annotations

import time

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.models.database import CustomerType, CustomerLevel, OrderStatus, OrderPriority
from app.models.schemas import ApiResponse
from app.api.deps import get_db_session, require_auth

router = APIRouter(prefix="/api/enums", tags=["enums"])


def _enum_to_dict(record) -> dict:
    """Convert an enum ORM record to a standard {id, code, name} dict."""
    return {
        "id": record.id,
        "code": record.code,
        "name": record.name,
    }


@router.get("/customers/types")
def list_customer_types(
    session: Session = Depends(get_db_session),
    _user: dict = Depends(require_auth),
):
    """Get all active customer types."""
    records = (
        session.query(CustomerType)
        .filter(CustomerType.is_active.is_(True))
        .order_by(CustomerType.sort_order)
        .all()
    )
    return ApiResponse(
        data=[_enum_to_dict(r) for r in records],
        timestamp=time.time(),
    )


@router.get("/customers/levels")
def list_customer_levels(
    session: Session = Depends(get_db_session),
    _user: dict = Depends(require_auth),
):
    """Get all active customer levels."""
    records = (
        session.query(CustomerLevel)
        .filter(CustomerLevel.is_active.is_(True))
        .order_by(CustomerLevel.sort_order)
        .all()
    )
    return ApiResponse(
        data=[_enum_to_dict(r) for r in records],
        timestamp=time.time(),
    )


@router.get("/orders/statuses")
def list_order_statuses(
    session: Session = Depends(get_db_session),
    _user: dict = Depends(require_auth),
):
    """Get all active order statuses."""
    records = (
        session.query(OrderStatus)
        .filter(OrderStatus.is_active.is_(True))
        .order_by(OrderStatus.sort_order)
        .all()
    )
    return ApiResponse(
        data=[_enum_to_dict(r) for r in records],
        timestamp=time.time(),
    )


@router.get("/orders/priorities")
def list_order_priorities(
    session: Session = Depends(get_db_session),
    _user: dict = Depends(require_auth),
):
    """Get all active order priorities."""
    records = (
        session.query(OrderPriority)
        .filter(OrderPriority.is_active.is_(True))
        .order_by(OrderPriority.sort_order)
        .all()
    )
    return ApiResponse(
        data=[_enum_to_dict(r) for r in records],
        timestamp=time.time(),
    )
