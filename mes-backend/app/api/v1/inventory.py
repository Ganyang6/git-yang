"""
Inventory management API routes.

Endpoints:
  GET  /api/inventory           - list inventory items with filters
  GET  /api/inventory/stats     - inventory statistics
  POST /api/inventory           - create new inventory item
  POST /api/inventory/inbound   - inbound (stock in) operation
  POST /api/inventory/outbound  - outbound (stock out) operation
"""

from __future__ import annotations

import logging
import time
from datetime import datetime, timezone
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import case, func, update
from sqlalchemy.orm import Session

from app.models.database import (
    get_session, InventoryItem, InventoryLog,
)
from app.models.schemas import ApiResponse, InventoryCreate, InventoryTransaction
from app.api.deps import get_db_session, require_auth, require_admin

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/inventory", tags=["inventory"])




def _item_to_dict(item: InventoryItem) -> dict:
    """Convert ORM InventoryItem to API response dict."""
    return {
        "code": item.code,
        "name": item.name,
        "spec": item.spec,
        "category": item.category,
        "unit": item.unit,
        "stock": float(item.stock),
        "safeStock": float(item.safe_stock),
        "location": item.location,
        "warehouse": item.warehouse,
        "price": float(item.price) if item.price else 0.0,
        "lastIn": item.last_inbound.isoformat() if item.last_inbound else "",
    }


@router.get("")
def list_inventory(
    category: Optional[str] = Query(None),
    warehouse: Optional[str] = Query(None),
    keyword: Optional[str] = Query(None, max_length=64),
    lowStockOnly: bool = Query(False),
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    session: Session = Depends(get_db_session),
    _user: dict = Depends(require_auth),
):
    """List inventory items with optional filters and pagination."""
    query = session.query(InventoryItem)

    if category:
        query = query.filter(InventoryItem.category == category)
    if warehouse:
        query = query.filter(InventoryItem.warehouse == warehouse)
    if keyword:
        query = query.filter(
            InventoryItem.code.contains(keyword)
            | InventoryItem.name.contains(keyword)
        )
    if lowStockOnly:
        query = query.filter(InventoryItem.stock <= InventoryItem.safe_stock)

    total = query.count()
    offset = (page - 1) * page_size
    items = [_item_to_dict(i) for i in query.order_by(InventoryItem.code).offset(offset).limit(page_size).all()]
    return ApiResponse(data={"items": items, "total": total, "page": page, "pageSize": page_size}, timestamp=time.time())


@router.get("/stats")
def inventory_stats(
    session: Session = Depends(get_db_session),
    _user: dict = Depends(require_auth),
):
    """Get inventory summary statistics."""
    # N-P1-11: Merge independent COUNT queries into single conditional aggregation
    stats = session.query(
        func.count(InventoryItem.id).label("total_items"),
        func.sum(case((InventoryItem.stock <= InventoryItem.safe_stock, 1), else_=0)).label("low_stock"),
        func.sum(InventoryItem.stock * InventoryItem.price).label("total_value"),
        func.count(func.distinct(InventoryItem.warehouse)).label("warehouse_count"),
    ).first()

    return ApiResponse(
        data={
            "totalItems": stats.total_items or 0,
            "lowStockCount": int(stats.low_stock or 0),
            "totalValue": float(stats.total_value or 0),
            "warehouseCount": stats.warehouse_count or 0,
        },
        timestamp=time.time(),
    )


@router.post("")
def create_inventory_item(
    req: InventoryCreate,
    session: Session = Depends(get_db_session),
    _user: dict = Depends(require_admin),
):
    """Create a new inventory item."""
    existing = session.query(InventoryItem).filter(InventoryItem.code == req.code).first()
    if existing:
        raise HTTPException(status_code=409, detail="Inventory code already exists")

    item = InventoryItem(
        code=req.code,
        name=req.name,
        spec=req.spec,
        category=req.category,
        unit=req.unit,
        safe_stock=req.safe_stock,
        location=req.location,
        warehouse=req.warehouse,
        price=req.price,
    )
    session.add(item)
    session.commit()
    session.refresh(item)

    logger.info("Inventory item created: %s", item.code)
    return ApiResponse(data=_item_to_dict(item), timestamp=time.time())


@router.post("/inbound")
def inbound_stock(
    req: InventoryTransaction,
    session: Session = Depends(get_db_session),
    _user: dict = Depends(require_admin),
):
    """Process inbound (stock in) operation."""
    item = session.query(InventoryItem).filter(
        InventoryItem.code == req.code
    ).first()
    if not item:
        raise HTTPException(status_code=404, detail="Inventory item not found")

    # Atomic SQL update to prevent race condition (P0 #14)
    result = session.execute(
        update(InventoryItem)
        .where(InventoryItem.code == req.code)
        .values(stock=InventoryItem.stock + req.qty, last_inbound=datetime.now(timezone.utc))
    )
    if result.rowcount == 0:
        raise HTTPException(status_code=404, detail="Inventory item not found")

    log = InventoryLog(
        inventory_item_id=item.id,
        transaction_type="inbound",
        quantity=req.qty,
        remark=req.remark,
    )
    session.add(log)
    session.commit()
    session.refresh(item)

    logger.info("Inbound: %s +%g", req.code, req.qty)
    return ApiResponse(data=_item_to_dict(item), timestamp=time.time())


@router.post("/outbound")
def outbound_stock(
    req: InventoryTransaction,
    session: Session = Depends(get_db_session),
    _user: dict = Depends(require_admin),
):
    """Process outbound (stock out) operation."""
    # Fetch item first (needed for error response and refresh)
    item = session.query(InventoryItem).filter(
        InventoryItem.code == req.code
    ).first()
    if not item:
        raise HTTPException(status_code=404, detail="Inventory item not found")

    # Check stock before atomic update
    if item.stock < req.qty:
        raise HTTPException(
            status_code=400,
            detail=f"Insufficient stock. Current: {item.stock}, Requested: {req.qty}",
        )

    # Atomic SQL update with stock check to prevent race condition (P0 #14)
    result = session.execute(
        update(InventoryItem)
        .where(
            InventoryItem.code == req.code,
            InventoryItem.stock >= req.qty,
        )
        .values(stock=InventoryItem.stock - req.qty)
    )
    if result.rowcount == 0:
        # Race condition: stock changed between check and update
        raise HTTPException(
            status_code=409,
            detail=f"Stock changed concurrently for {req.code}. Please retry.",
        )

    # Refresh from DB instead of re-querying (P2-10)
    session.refresh(item)

    log = InventoryLog(
        inventory_item_id=item.id,
        transaction_type="outbound",
        quantity=req.qty,
        remark=req.remark,
    )
    session.add(log)
    session.commit()
    session.refresh(item)

    logger.info("Outbound: %s -%g", req.code, req.qty)
    return ApiResponse(data=_item_to_dict(item), timestamp=time.time())


@router.delete("/{code}")
def delete_inventory_item(
    code: str,
    session: Session = Depends(get_db_session),
    _user: dict = Depends(require_admin),
):
    """Delete an inventory item by code and its associated logs."""
    item = session.query(InventoryItem).filter(InventoryItem.code == code).first()
    if not item:
        raise HTTPException(status_code=404, detail="Inventory item not found")

    # Delete associated inventory log records first
    session.query(InventoryLog).filter(
        InventoryLog.inventory_item_id == item.id
    ).delete(synchronize_session='fetch')

    session.delete(item)
    session.commit()

    logger.info("Inventory item deleted: code=%s, name=%s", code, item.name)
    return ApiResponse(data={"code": code, "deleted": True}, timestamp=time.time())
