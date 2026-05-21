"""
Production order CRUD API routes.

Endpoints:
  GET    /api/orders        - list orders with filters and pagination
  GET    /api/orders/{id}   - get single order detail
  POST   /api/orders        - create new order
  PUT    /api/orders/{id}   - update existing order
  DELETE /api/orders/{id}   - delete an order
"""

from __future__ import annotations

import logging
import re
import time
from datetime import date, datetime
from enum import Enum
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session, joinedload

from app.models.database import get_session, Order, Customer
from app.models.schemas import ApiResponse, OrderCreate, OrderUpdate
from app.api.deps import get_db_session, require_auth, require_admin
from app.core.enums import OrderStatus, OrderPriority

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/orders", tags=["orders"])

_DATE_PATTERN = re.compile(r"^\d{4}-\d{2}-\d{2}$")

# FK mapping: string code → integer ID for enum lookup tables
# Uses IntEnum values from app.core.enums (must match _seed_enums() in database.py)
_ORDER_STATUS_MAP = {s.name: s.value for s in OrderStatus}
_ORDER_PRIORITY_MAP = {p.name: p.value for p in OrderPriority}

# Reverse map: integer ID → string code
_ORDER_STATUS_ID_TO_CODE = {v: k for k, v in _ORDER_STATUS_MAP.items()}
_ORDER_PRIORITY_ID_TO_CODE = {v: k for k, v in _ORDER_PRIORITY_MAP.items()}




def _order_to_dict(order: Order) -> dict:
    """Convert ORM Order to API response dict."""
    customer_name = ""
    if order.customer_id and order.customer:
        customer_name = order.customer.name
    # P0-4: resolve FK IDs to readable codes via relationship or reverse map
    status_code = (
        order.status_rel.code
        if order.status_rel
        else _ORDER_STATUS_ID_TO_CODE.get(order.status, str(order.status))
    )
    priority_code = (
        order.priority_rel.code
        if order.priority_rel
        else _ORDER_PRIORITY_ID_TO_CODE.get(order.priority, str(order.priority))
    )
    return {
        "id": order.id,
        "code": order.code,
        "product": order.product,
        "spec": order.spec,
        "customer": customer_name,
        "customer_id": order.customer_id,
        "qty": order.quantity,
        "completedQty": order.completed_qty,
        "dueDate": order.due_date,
        "priority": priority_code,
        "status": status_code,
        "remark": order.remark,
        "createdAt": order.created_at.isoformat() if order.created_at else "",
        "updatedAt": order.updated_at.isoformat() if order.updated_at else "",
    }


@router.get("")
def list_orders(
    status: Optional[str] = Query(None),
    priority: Optional[str] = Query(None),
    keyword: Optional[str] = Query(None, max_length=64),
    dateFrom: Optional[str] = Query(None),
    dateTo: Optional[str] = Query(None),
    page: int = Query(1, ge=1),
    pageSize: int = Query(20, ge=1, le=100),
    session: Session = Depends(get_db_session),
    _user: dict = Depends(require_auth),
):
    """List orders with optional filters and pagination."""
    query = session.query(Order)

    # P0-3: convert string filter params to integer FK IDs
    if status:
        status_id = _ORDER_STATUS_MAP.get(status)
        if status_id is not None:
            query = query.filter(Order.status == status_id)
    if priority:
        priority_id = _ORDER_PRIORITY_MAP.get(priority)
        if priority_id is not None:
            query = query.filter(Order.priority == priority_id)
    if keyword:
        query = query.filter(
            Order.code.contains(keyword) | Order.product.contains(keyword)
        )
    if dateFrom:
        if not _DATE_PATTERN.match(dateFrom):
            raise HTTPException(status_code=400, detail="dateFrom must be YYYY-MM-DD format")
        try:
            date.fromisoformat(dateFrom)
        except ValueError:
            raise HTTPException(status_code=400, detail="dateFrom is not a valid date")
        query = query.filter(Order.due_date >= dateFrom)
    if dateTo:
        if not _DATE_PATTERN.match(dateTo):
            raise HTTPException(status_code=400, detail="dateTo must be YYYY-MM-DD format")
        try:
            date.fromisoformat(dateTo)
        except ValueError:
            raise HTTPException(status_code=400, detail="dateTo is not a valid date")
        query = query.filter(Order.due_date <= dateTo)

    total = query.count()
    # P1 #23: Use joinedload to prevent N+1 query on customer
    # P1-8: Also eager-load status_rel and priority_rel to prevent N+1 in _order_to_dict
    items = (
        query.options(
            joinedload(Order.customer),
            joinedload(Order.status_rel),
            joinedload(Order.priority_rel),
        )
        .order_by(Order.id.desc())
        .offset((page - 1) * pageSize)
        .limit(pageSize)
        .all()
    )

    return ApiResponse(
        data={
            "items": [_order_to_dict(o) for o in items],
            "total": total,
            "page": page,
            "pageSize": pageSize,
        },
        timestamp=time.time(),
    )


@router.get("/{order_id}")
def get_order(
    order_id: int,
    session: Session = Depends(get_db_session),
    _user: dict = Depends(require_auth),
):
    """Get a single order by ID."""
    order = session.query(Order).options(
        joinedload(Order.customer),
        joinedload(Order.status_rel),
        joinedload(Order.priority_rel),
    ).where(Order.id == order_id).first()
    if not order:
        raise HTTPException(status_code=404, detail="Order not found")
    return ApiResponse(data=_order_to_dict(order), timestamp=time.time())


@router.post("")
def create_order(
    req: OrderCreate,
    session: Session = Depends(get_db_session),
    _user: dict = Depends(require_admin),
):
    """Create a new production order."""
    # Resolve customer name to customer_id
    customer_id = None
    if req.customer:
        cust = session.query(Customer).filter(Customer.name == req.customer).first()
        if cust:
            customer_id = cust.id
        else:
            logger.warning("Order creation: customer '%s' not found", req.customer)

    # P0-2: map string status/priority codes to Integer FK IDs
    status_value = req.status.value if isinstance(req.status, Enum) else req.status
    priority_value = req.priority.value if isinstance(req.priority, Enum) else req.priority
    status_id = _ORDER_STATUS_MAP.get(status_value, 1)
    priority_id = _ORDER_PRIORITY_MAP.get(priority_value, 1)

    order = Order(
        code=req.code,
        product=req.product,
        spec=req.spec,
        customer_id=customer_id,
        quantity=req.qty,
        due_date=req.due_date,
        priority=priority_id,
        status=status_id,
        remark=req.remark,
    )
    session.add(order)
    session.commit()
    session.refresh(order)

    logger.info("Order created: %s (%s)", order.code, order.product)
    return ApiResponse(data=_order_to_dict(order), timestamp=time.time())


@router.put("/{order_id}")
def update_order(
    order_id: int,
    req: OrderUpdate,
    session: Session = Depends(get_db_session),
    _user: dict = Depends(require_admin),
):
    """Update an existing order."""
    order = session.get(Order, order_id)
    if not order:
        raise HTTPException(status_code=404, detail="Order not found")

    update_data = req.model_dump(exclude_none=True)

    # Map frontend field names to ORM field names
    field_map = {
        "dueDate": "due_date",
    }
    # P0-2: map string status/priority codes to Integer FK IDs
    if "status" in update_data:
        update_data["status"] = _ORDER_STATUS_MAP.get(update_data["status"], 1)
    if "priority" in update_data:
        update_data["priority"] = _ORDER_PRIORITY_MAP.get(update_data["priority"], 1)

    for key, value in update_data.items():
        orm_key = field_map.get(key, key)
        if hasattr(order, orm_key):
            setattr(order, orm_key, value)

    # Resolve customer name to customer_id
    if "customer" in update_data and update_data["customer"]:
        cust = session.query(Customer).filter(
            Customer.name == update_data["customer"]
        ).first()
        if cust:
            order.customer_id = cust.id

    session.commit()
    session.refresh(order)

    logger.info("Order updated: %s", order.code)
    return ApiResponse(data=_order_to_dict(order), timestamp=time.time())


@router.delete("/{order_id}")
def delete_order(
    order_id: int,
    session: Session = Depends(get_db_session),
    _user: dict = Depends(require_admin),
):
    """Delete an order.

    Note: No child tables currently FK-reference orders, so deletion
    is allowed without additional protection. If future tables (e.g.
    order_items, production_records) add FK references, add a check
    similar to customers.py delete protection.
    """
    order = session.get(Order, order_id)
    if not order:
        raise HTTPException(status_code=404, detail="Order not found")

    session.delete(order)
    session.commit()

    logger.info("Order deleted: id=%d", order_id)
    return ApiResponse(data=None, message="Order deleted", timestamp=time.time())
