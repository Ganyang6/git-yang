"""Meta data API — 提供前端所需的动态配置和选项列表。

解决前端硬编码问题：工位、班次、产线、阈值等。
"""
from __future__ import annotations
import logging
import time
from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.core.config import load_app_config
from app.models.database import ProcessSegment, Equipment
from app.models.schemas import ApiResponse
from app.api.deps import get_db_session, require_auth

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/meta", tags=["meta"])


@router.get("")
def get_meta(
    session: Session = Depends(get_db_session),
    _user: dict = Depends(require_auth),
):
    """返回前端启动所需的元数据。"""
    # 工位
    stations = session.query(Equipment).order_by(Equipment.id).all()
    stations_data = [
        {"id": s.name, "name": s.name, "workshop": s.workshop}
        for s in stations
    ]

    # 班次（从 config.yaml 读取）
    cfg = load_app_config().meta
    shifts = cfg.shifts

    # 产线（从 process_segments 推断）
    lines = [
        {"id": r[0], "name": r[0]}
        for r in session.query(ProcessSegment.line).distinct().filter(
            ProcessSegment.line.isnot(None), ProcessSegment.line != ""
        ).all()
    ]
    if not lines:
        lines = [{"id": "line1", "name": "产线 A"}]

    return ApiResponse(data={
        "stations": stations_data,
        "shifts": shifts,
        "lines": lines,
        "mod_unit": cfg.mod_unit,
        "default_allowance_rate": cfg.default_allowance_rate,
        "thresholds": cfg.thresholds,
    }, timestamp=time.time())
