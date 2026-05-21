"""
Customer CRUD API routes.

Endpoints:
  GET    /api/customers       - list customers with filters
  GET    /api/customers/stats - customer statistics
  POST   /api/customers       - create new customer
  PUT    /api/customers/{id}  - update customer
  DELETE /api/customers/{id}  - delete customer
"""

from __future__ import annotations

import logging
import time
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import case, func
from sqlalchemy.orm import Session, joinedload

from app.models.database import get_session, Customer, Order
from app.models.schemas import ApiResponse, CustomerCreate, CustomerUpdate
from app.api.deps import get_db_session, require_auth, require_admin

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/customers", tags=["customers"])

# FK mapping: string code → integer ID for enum lookup tables
# Must match data in _seed_enums() in app/models/database.py
_CUSTOMER_TYPE_MAP = {"normal": 1, "vip": 2}
_CUSTOMER_LEVEL_MAP = {"A": 1, "B": 2, "C": 3, "S": 4}

# Reverse map: integer ID → string code
_CUSTOMER_TYPE_ID_TO_CODE = {v: k for k, v in _CUSTOMER_TYPE_MAP.items()}
_CUSTOMER_LEVEL_ID_TO_CODE = {v: k for k, v in _CUSTOMER_LEVEL_MAP.items()}


def _customer_to_dict(cust: Customer, extra: dict | None = None) -> dict:
    """Convert ORM Customer to API response dict.

    Matches frontend Customer fields: id, name, contact, phone, city,
    type, level, orders, amount, lastOrder, status.
    """
    # P0-4: resolve FK IDs to readable codes via relationship or reverse map
    type_code = (
        cust.customer_type_rel.code
        if cust.customer_type_rel
        else _CUSTOMER_TYPE_ID_TO_CODE.get(cust.customer_type, str(cust.customer_type))
    )
    level_code = (
        cust.level_rel.code
        if cust.level_rel
        else _CUSTOMER_LEVEL_ID_TO_CODE.get(cust.level, str(cust.level))
    )
    result = {
        "id": cust.id,
        "name": cust.name,
        "contact": cust.contact,
        "phone": cust.phone,
        "city": cust.city,
        "type": type_code,
        "level": level_code,
        "remark": cust.remark,
        "status": cust.status,
    }
    if extra:
        result.update(extra)
    return result


@router.get("")
def list_customers(
    type: Optional[str] = Query(None),
    level: Optional[str] = Query(None),
    keyword: Optional[str] = Query(None, max_length=64),
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    session: Session = Depends(get_db_session),
    _user: dict = Depends(require_auth),
):
    """List customers with optional filters and pagination."""
    query = session.query(Customer)

    # P0-3: convert string filter params to integer FK IDs
    if type:
        type_id = _CUSTOMER_TYPE_MAP.get(type)
        if type_id is not None:
            query = query.filter(Customer.customer_type == type_id)
    if level:
        level_id = _CUSTOMER_LEVEL_MAP.get(level)
        if level_id is not None:
            query = query.filter(Customer.level == level_id)
    if keyword:
        query = query.filter(
            Customer.name.contains(keyword) | Customer.phone.contains(keyword)
        )

    total = query.count()
    offset = (page - 1) * page_size
    # P1-9: Use joinedload to prevent N+1 query on customer_type_rel and level_rel
    customers = (
        query.options(
            joinedload(Customer.customer_type_rel),
            joinedload(Customer.level_rel),
        )
        .order_by(Customer.id.desc())
        .offset(offset)
        .limit(page_size)
        .all()
    )

    # Batch aggregate order stats in a single GROUP BY query (avoids N+1)
    customer_ids = [c.id for c in customers]
    stats_map: dict = {}
    if customer_ids:
        stats_rows = session.query(
            Order.customer_id,
            func.count(Order.id).label("order_count"),
            func.sum(Order.quantity).label("total_amount"),
            func.max(Order.created_at).label("last_order"),
        ).filter(
            Order.customer_id.in_(customer_ids)
        ).group_by(Order.customer_id).all()

        stats_map = {
            r.customer_id: {
                "orders": r.order_count or 0,
                "amount": float(r.total_amount or 0),
                "lastOrder": r.last_order.isoformat() if r.last_order else "",
            }
            for r in stats_rows
        }

    items = []
    for c in customers:
        extra = stats_map.get(c.id, {"orders": 0, "amount": 0.0, "lastOrder": ""})
        items.append(_customer_to_dict(c, extra))

    return ApiResponse(
        data={"items": items, "total": total, "page": page, "pageSize": page_size},
        timestamp=time.time(),
    )


@router.get("/stats")
def customer_stats(
    session: Session = Depends(get_db_session),
    _user: dict = Depends(require_auth),
):
    """Get customer summary statistics."""
    # N-P1-16: Fix JOIN膨胀 - use subquery for order aggregation instead of outerjoin
    order_agg = session.query(
        Order.customer_id,
        func.count(Order.id).label("order_count"),
        func.sum(Order.quantity).label("total_amount"),
    ).group_by(Order.customer_id).subquery()

    stats = session.query(
        func.count(Customer.id).label("total"),
        func.sum(case((Customer.status == "active", 1), else_=0)).label("active"),
        # P0-5: compare Integer FK with the correct int ID (S-level = 4)
        func.sum(case((Customer.level == 4, 1), else_=0)).label("sa_count"),
        func.coalesce(func.sum(order_agg.c.total_amount), 0).label("total_amount"),
    ).outerjoin(order_agg, order_agg.c.customer_id == Customer.id).first()

    total = stats.total or 0
    active = int(stats.active or 0)
    sa_count = int(stats.sa_count or 0)
    total_amount = stats.total_amount or 0

    return ApiResponse(
        data={
            "total": total,
            "active": active,
            "saCount": sa_count,
            "totalAmount": float(total_amount),
        },
        timestamp=time.time(),
    )


@router.post("")
def create_customer(
    req: CustomerCreate,
    session: Session = Depends(get_db_session),
    _user: dict = Depends(require_admin),
):
    """Create a new customer."""
    existing = session.query(Customer).filter(Customer.name == req.name).first()
    if existing:
        raise HTTPException(status_code=409, detail="Customer name already exists")

    # P0-1: map string type/level codes to Integer FK IDs
    type_id = _CUSTOMER_TYPE_MAP.get(req.type, 1)
    level_id = _CUSTOMER_LEVEL_MAP.get(req.level, 1)

    customer = Customer(
        name=req.name,
        contact=req.contact,
        phone=req.phone,
        city=req.city,
        customer_type=type_id,
        level=level_id,
        remark=req.remark,
    )
    session.add(customer)
    session.commit()
    session.refresh(customer)

    logger.info("Customer created: %s", customer.name)
    return ApiResponse(data=_customer_to_dict(customer), timestamp=time.time())


@router.put("/{customer_id}")
def update_customer(
    customer_id: int,
    req: CustomerUpdate,
    session: Session = Depends(get_db_session),
    _user: dict = Depends(require_admin),
):
    """Update an existing customer."""
    customer = session.get(Customer, customer_id)
    if not customer:
        raise HTTPException(status_code=404, detail="Customer not found")

    update_data = req.model_dump(exclude_none=True)
    field_map = {
        "type": "customer_type",
    }
    # P0-1/P0-6: map string type/level codes to Integer FK IDs
    if "type" in update_data:
        update_data["type"] = _CUSTOMER_TYPE_MAP.get(update_data["type"], 1)
    if "level" in update_data:
        update_data["level"] = _CUSTOMER_LEVEL_MAP.get(update_data["level"], 1)

    for key, value in update_data.items():
        orm_key = field_map.get(key, key)
        if hasattr(customer, orm_key):
            setattr(customer, orm_key, value)

    session.commit()
    session.refresh(customer)

    logger.info("Customer updated: %s", customer.name)
    return ApiResponse(data=_customer_to_dict(customer), timestamp=time.time())


@router.delete("/{customer_id}")
def delete_customer(
    customer_id: int,
    session: Session = Depends(get_db_session),
    _user: dict = Depends(require_admin),
):
    """Delete a customer.

    Protected: refuses deletion if the customer has any associated orders.
    """
    customer = session.get(Customer, customer_id)
    if not customer:
        raise HTTPException(status_code=404, detail="Customer not found")

    # 删除保护：检查是否有关联订单
    order_count = session.query(Order).filter(Order.customer_id == customer_id).count()
    if order_count > 0:
        raise HTTPException(
            status_code=400,
            detail=f"该客户有 {order_count} 条关联订单，无法删除",
        )

    session.delete(customer)
    session.commit()

    logger.info("Customer deleted: id=%d", customer_id)
    return ApiResponse(data=None, message="Customer deleted", timestamp=time.time())
