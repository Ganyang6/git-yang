"""Quality check / defect tracking model."""
from datetime import datetime, timezone
from sqlalchemy import Column, Integer, String, DateTime, ForeignKey, Text
from app.models.database import Base


class QualityCheck(Base):
    __tablename__ = "quality_checks"

    id = Column(Integer, primary_key=True, index=True)
    order_id = Column(Integer, ForeignKey("orders.id"), nullable=False, index=True)
    checked_qty = Column(Integer, default=0, comment="检验数量")
    ok_qty = Column(Integer, default=0, comment="良品数量")
    defect_qty = Column(Integer, default=0, comment="不良数量")
    defect_type = Column(String(64), nullable=True, comment="不良类型")
    inspector = Column(String(64), nullable=True, comment="检验人")
    station_id = Column(String(32), nullable=True, comment="工站编号")
    notes = Column(Text, nullable=True, comment="备注")
    checked_at = Column(DateTime, default=lambda: datetime.now(timezone.utc), comment="检验时间")
    created_at = Column(DateTime, default=lambda: datetime.now(timezone.utc))
    updated_at = Column(DateTime, default=lambda: datetime.now(timezone.utc), onupdate=lambda: datetime.now(timezone.utc))
