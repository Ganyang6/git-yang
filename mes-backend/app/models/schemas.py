"""
Pydantic schemas for request/response validation.

All API input/output passes through these schemas to guarantee type safety.
"""

from __future__ import annotations

from datetime import datetime
from enum import Enum
from typing import Dict, List, Optional

import time as _time

from pydantic import BaseModel, ConfigDict, Field, model_validator, ValidationError


# -- Enums -------------------------------------------------------------------

class ActionLabel(str, Enum):
    """Classified action categories recognized by the rule engine."""
    REACH = "reach"              #伸手
    GRASP = "grasp"              #抓取
    MOVE = "move"                #搬运
    ASSEMBLE = "assemble"        #装配
    RELEASE = "release"          #释放
    INSPECT = "inspect"          #检验
    WAIT = "wait"                #等待
    HOLD = "hold"                #持住(Phase I, currently mapped to WAIT)
    IDLE = "idle"                #空闲(未检测到人)


class TherbligSymbol(str, Enum):
    """18 standard Therblig symbols for motion analysis."""
    REACH = "R"          # 伸手
    MOVE = "M"           # 搬运
    GRASP = "G"          # 抓取
    RELEASE = "RL"       # 释放
    POSITION = "P"       # 定位
    PREPOSITION = "PP"   # 预定位
    USE = "U"            # 使用
    ASSEMBLE = "A"       # 组合
    DISASSEMBLE = "DA"   # 拆卸
    SEARCH = "Sh"        # 寻找
    SELECT = "St"        # 选择
    PLAN = "Pn"          # 计划
    INSPECT = "I"        # 检验
    HOLD = "H"           # 持住
    UNAVOIDABLE_DELAY = "UD"     # 不可避免的延迟
    AVOIDABLE_DELAY = "AD"       # 可避免的延迟
    REST = "Rst"                  # 休息
    FIND = "F"           # 发现


class ShiftName(str, Enum):
    MORNING = "morning"
    AFTERNOON = "afternoon"
    NIGHT = "night"


# -- Pose frame input (from perception layer) ---------------------------------

class LandmarkSchema(BaseModel):
    """A single pose landmark point."""
    name: str = ""
    x: float
    y: float
    z: float = 0.0
    visibility: float = 0.0


class PoseFrameSchema(BaseModel):
    """A single frame of pose landmarks from the perception layer."""
    camera_id: str
    timestamp: float
    frame_id: str = ""
    landmarks: List[LandmarkSchema] = Field(default_factory=list, max_length=75)
    pose_score: float = 0.0
    hand_landmarks: Optional[List[LandmarkSchema]] = Field(default=None, max_length=42)
    hand_features: Optional[Dict[str, float]] = None


class ClassificationResultSchema(BaseModel):
    """Output of the action classifier for one window."""
    action: ActionLabel
    confidence: float
    dominant_region: str = ""  # upper_body / lower_body / full_body


# -- Process segment (database entity) ----------------------------------------

class ProcessSegmentSchema(BaseModel):
    """A completed process segment written to the database."""
    id: Optional[int] = None
    camera_id: str
    station_id: str
    action: ActionLabel
    therblig_symbol: Optional[str] = None
    start_time: datetime
    end_time: datetime
    duration_ms: float
    confidence: float
    shift: ShiftName = ShiftName.MORNING


# -- Worktime record (aggregated from segments) -------------------------------

class WorktimeRecordSchema(BaseModel):
    """An aggregated worktime record for one operation."""
    id: Optional[int] = None
    operation: str
    station_id: str
    actual_ms: float
    standard_ms: float = 0.0
    efficiency: float = 0.0  # standard / actual
    mod_total: float = 0.0
    shift: ShiftName = ShiftName.MORNING
    created_at: Optional[datetime] = None


# -- Therblig detail row ------------------------------------------------------

class TherbligRowSchema(BaseModel):
    """A single therblig motion element within an operation."""
    id: Optional[int] = None
    operation_id: Optional[int] = None
    symbol: TherbligSymbol
    name: str = ""
    mod: float = 0.0
    actual_ms: float = 0.0
    pct: float = 0.0  # percentage of total operation time
    is_waste: bool = False


# -- API response wrappers ----------------------------------------------------

class ApiResponse(BaseModel):
    """Standard API response envelope."""
    code: int = 0
    message: str = "success"
    data: Optional[dict | list] = None
    timestamp: float = Field(default_factory=lambda: _time.time())


class PaginatedResponse(ApiResponse):
    """Paginated list response."""
    data: Optional[dict] = None  # { items: [...], total: int, page: int }


# -- Auth schemas (Phase 3) ---------------------------------------------------

class LoginRequest(BaseModel):
    username: str = Field(..., min_length=1, max_length=32)
    password: str = Field(..., min_length=1, max_length=128)
    remember: bool = False


class UserInfo(BaseModel):
    username: str
    role: str = "operator"
    display_name: str = ""


class LoginResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    expires_in: int = 28800
    user: UserInfo


# -- Business CRUD schemas (Phase 3) ------------------------------------------

# -- Orders --

class OrderStatus(str, Enum):
    """Order status values."""
    PENDING = "pending"
    IN_PROGRESS = "in_progress"
    PROCESSING = "processing"
    COMPLETED = "completed"
    CANCELLED = "cancelled"


class OrderPriority(str, Enum):
    """Order priority levels."""
    LOW = "low"
    NORMAL = "normal"
    HIGH = "high"
    URGENT = "urgent"


# -- Orders --

class OrderCreate(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    product: str = Field(..., min_length=1, max_length=128)
    code: str = Field(..., min_length=1, max_length=64)
    spec: str = ""
    customer: str = ""
    qty: int = Field(default=1, ge=0)
    due_date: str = Field(default="", alias="dueDate")
    priority: OrderPriority = OrderPriority.NORMAL
    status: OrderStatus = OrderStatus.PENDING
    remark: str = ""


class OrderUpdate(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    product: Optional[str] = None
    code: Optional[str] = None
    spec: Optional[str] = None
    customer: Optional[str] = None
    qty: Optional[int] = Field(default=None, ge=0)
    due_date: Optional[str] = Field(default=None, alias="dueDate")
    priority: Optional[OrderPriority] = None
    status: Optional[OrderStatus] = None
    remark: Optional[str] = None


# -- Customers --

class CustomerCreate(BaseModel):
    name: str = Field(..., min_length=1, max_length=128)
    contact: str = ""
    phone: str = ""
    city: str = ""
    type: str = "normal"
    level: str = "B"
    remark: str = ""


class CustomerUpdate(BaseModel):
    name: Optional[str] = None
    contact: Optional[str] = None
    phone: Optional[str] = None
    city: Optional[str] = None
    type: Optional[str] = None
    level: Optional[str] = None
    remark: Optional[str] = None


# -- Inventory --

class InventoryCreate(BaseModel):
    model_config = ConfigDict(populate_by_name=True)
    code: str = Field(..., min_length=1, max_length=64)
    name: str = Field(..., min_length=1, max_length=128)
    spec: str = ""
    category: str = "material"
    unit: str = ""
    safe_stock: float = Field(default=0.0, ge=0.0, alias="safeStock")
    location: str = ""
    warehouse: str = ""
    price: float = Field(default=0.0, ge=0.0)


class InventoryTransaction(BaseModel):
    code: str = Field(..., min_length=1, max_length=64)
    qty: float = Field(..., gt=0)
    remark: str = ""


# -- Equipment --

class EquipmentCreate(BaseModel):
    name: str = Field(..., min_length=1, max_length=128)
    model: str = ""
    workshop: str = ""


class EquipmentUpdate(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    name: Optional[str] = Field(default=None, min_length=1, max_length=128)
    model: Optional[str] = None
    workshop: Optional[str] = None
    status: Optional[str] = Field(default=None, pattern="^(running|idle|maintenance|offline)$")
    oee: Optional[float] = Field(default=None, ge=0.0, le=100.0)
    utilization: Optional[float] = Field(default=None, ge=0.0, le=100.0)
    fault_count: Optional[int] = Field(default=None, ge=0, alias="faultCount")
    mtbf_hours: Optional[float] = Field(default=None, ge=0.0, alias="mtbf")
    today_util_pct: Optional[float] = Field(default=None, ge=0.0, le=100.0, alias="todayUtil")
    next_maintenance: Optional[str] = Field(default=None, alias="nextMaint")


# -- Stations --

class StationCreate(BaseModel):
    name: str = Field(..., min_length=1, max_length=50)
    worker: str = Field(..., min_length=1, max_length=64)
    line: str = Field(..., min_length=1, max_length=50)
    shift: str = Field(..., min_length=1, max_length=16)


class StationUpdate(BaseModel):
    worker: Optional[str] = Field(None, min_length=1, max_length=64)
    line: Optional[str] = Field(None, min_length=1, max_length=50)
    shift: Optional[str] = Field(None, min_length=1, max_length=16)
    # 注意：没有 name 字段，编辑不允许改编号


class StationResponse(BaseModel):
    id: int
    name: str
    worker: str
    line: str
    shift: str


# -- Dashboard schemas (Phase 3) -----------------------------------------------

class DashboardKpi(BaseModel):
    """Dashboard KPI response data with range constraints."""
    utilization: float = Field(default=0.0, ge=0.0, le=1.0)
    utilization_hasData: bool = Field(default=False)
    stdtimeAchievement: float = Field(default=0.0, ge=0.0, le=1.0)
    stdtimeAchievement_hasData: bool = Field(default=False)
    balanceRate: float = Field(default=0.0, ge=0.0, le=1.0)
    balanceRate_hasData: bool = Field(default=False)
    waitLossMinutes: float = Field(default=0.0, ge=0.0)
    waitLossMinutes_hasData: bool = Field(default=False)
    trends: dict = Field(default_factory=dict)


class AiContext(BaseModel):
    """AI context response data with range constraints."""
    balanceRate: float | None = Field(default=None, ge=0.0, le=1.0)
    bottleneckStation: str = ""
    taktTime: float = Field(default=0.0, ge=0.0)
    lostCapacity: float = Field(default=0.0, ge=0.0)
    utilization: float = Field(default=0.0, ge=0.0, le=1.0)
    stdtimeAchievement: float = Field(default=0.0, ge=0.0, le=1.0)
    wasteRatio: float = Field(default=0.0, ge=0.0, le=1.0)

    @model_validator(mode="before")
    @classmethod
    def coerce_none_strings(cls, data):
        """Coerce None values to empty string for str fields."""
        if isinstance(data, dict):
            if data.get("bottleneckStation") is None:
                data["bottleneckStation"] = ""
        return data


class TimelineSegment(BaseModel):
    """Station timeline segment with range constraints."""
    type: str
    label: str
    time: float = Field(ge=0.0)
    pct: float = Field(ge=0.0, le=100.0)


class StationTimeline(BaseModel):
    """Station timeline entry with range constraints."""
    id: int
    name: str
    oee: float = Field(default=0.0, ge=0.0, le=1.0)
    segments: List[TimelineSegment] = Field(default_factory=list)


# -- Line balance schemas (Phase 3) --------------------------------------------

class StationInfo(BaseModel):
    """Station info with range constraints."""
    name: str
    time: float = Field(ge=0.0)
    isBottleneck: bool = False


class LineBalanceSummary(BaseModel):
    """Line balance summary with range constraints."""
    balanceRate: float = Field(default=0.0, ge=0.0, le=1.0)
    smoothIndex: float = Field(default=0.0, ge=0.0)
    bottleneckStation: str = ""
    stations: List[StationInfo] = Field(default_factory=list)
    taktTime: float = Field(default=0.0, ge=0.0)

    @model_validator(mode="before")
    @classmethod
    def coerce_none_values(cls, data):
        """Coerce None numeric values to 0.0 and None strings to empty."""
        if isinstance(data, dict):
            for key in ("balanceRate", "smoothIndex", "taktTime"):
                if data.get(key) is None:
                    data[key] = 0.0
            for key in ("bottleneckStation",):
                if data.get(key) is None:
                    data[key] = ""
        return data


class EcrsItem(BaseModel):
    """ECRS suggestion item (frontend-facing format)."""
    type: str = ""
    typeLabel: str = ""
    station: str = ""
    content: str = ""
    saving: str = ""
    difficulty: int = 2
    priority: str = "P2"
    status: str = "pending"


class CausalRule(BaseModel):
    """Causal rule for bottleneck diagnosis (frontend-facing format)."""
    station: str = ""
    condition: str = ""
    cause: str = ""
    action: str = ""
    saving: str = ""
    improvement: str = ""


class LineBalanceFull(BaseModel):
    """Complete line balance data with range constraints."""
    balanceRate: float = Field(default=0.0, ge=0.0, le=1.0)
    smoothIndex: float = Field(default=0.0, ge=0.0)
    taktTime: float = Field(default=0.0, ge=0.0)
    dailyDemand: int = Field(default=0, ge=0)
    bottleneck: str = ""
    lostCapacity: float = Field(default=0.0, ge=0.0)
    lostValue: float = Field(default=0.0, ge=0.0)
    stations: List[StationInfo] = Field(default_factory=list)
    causalRules: List[CausalRule] = Field(default_factory=list)
    ecrsItems: List[EcrsItem] = Field(default_factory=list)

    @model_validator(mode="before")
    @classmethod
    def coerce_none_values(cls, data):
        """Coerce None values to defaults."""
        if isinstance(data, dict):
            for key in ("balanceRate", "smoothIndex", "taktTime", "lostCapacity", "lostValue"):
                if data.get(key) is None:
                    data[key] = 0.0
            for key in ("bottleneck",):
                if data.get(key) is None:
                    data[key] = ""
            if data.get("dailyDemand") is None:
                data["dailyDemand"] = 0
        return data


class BottleneckDiagnosis(BaseModel):
    """Bottleneck diagnosis result."""
    station: str
    level: str
    levelLabel: str
    reason: str
    suggest: str


# -- Report schemas (Phase 3) --------------------------------------------------

class ReportKpi(BaseModel):
    """Report KPI response data with range constraints."""
    totalOutput: int = Field(default=0, ge=0)
    totalOutput_hasData: bool = Field(default=False)
    completionRate: float = Field(default=0.0, ge=0.0, le=200.0)
    completionRate_hasData: bool = Field(default=False)
    yieldRate: float | None = Field(default=None, ge=0.0, le=100.0)
    yieldRate_hasData: bool = Field(default=False)
    onTimeRate: float = Field(default=0.0, ge=0.0, le=100.0)
    onTimeRate_hasData: bool = Field(default=False)
    oee: float | None = Field(default=None, ge=0.0, le=100.0)
    oee_hasData: bool = Field(default=False)
    utilization: float = Field(default=0.0, ge=0.0, le=100.0)
    utilization_hasData: bool = Field(default=False)
    changes: Optional[dict] = None


class TopCustomer(BaseModel):
    """Top customer ranking item with range constraints."""
    name: str
    orders: int = Field(default=0, ge=0)
    qty: int = Field(default=0, ge=0)
    amount: float = Field(default=0.0, ge=0.0)
    share: float = Field(default=0.0, ge=0.0, le=100.0)
    trend: str = ""


# -- Quality Check --

class QualityCheckCreate(BaseModel):
    order_id: int = Field(..., gt=0)
    checked_qty: int = Field(default=0, ge=0)
    ok_qty: int = Field(default=0, ge=0)
    defect_qty: int = Field(default=0, ge=0)
    defect_type: Optional[str] = Field(default=None, max_length=64)
    inspector: Optional[str] = Field(default=None, max_length=64)
    station_id: Optional[str] = Field(default=None, max_length=32)
    notes: Optional[str] = None
    checked_at: Optional[str] = None

    @model_validator(mode="after")
    def check_qty_consistency(self):
        if self.ok_qty + self.defect_qty > self.checked_qty:
            raise ValueError("ok_qty + defect_qty must not exceed checked_qty")
        return self


class QualityCheckUpdate(BaseModel):
    checked_qty: Optional[int] = Field(default=None, ge=0)
    ok_qty: Optional[int] = Field(default=None, ge=0)
    defect_qty: Optional[int] = Field(default=None, ge=0)
    defect_type: Optional[str] = Field(default=None, max_length=64)
    inspector: Optional[str] = Field(default=None, max_length=64)
    station_id: Optional[str] = Field(default=None, max_length=32)
    notes: Optional[str] = None
    checked_at: Optional[str] = None

    @model_validator(mode="after")
    def check_qty_consistency(self):
        # Only validate when all three relevant fields are present
        if self.checked_qty is not None and self.ok_qty is not None and self.defect_qty is not None:
            if self.ok_qty + self.defect_qty > self.checked_qty:
                raise ValueError("ok_qty + defect_qty must not exceed checked_qty")
        return self


class ProductMixItem(BaseModel):
    """Product mix pie chart item."""
    label: str
    value: float = Field(ge=0.0)
    color: str = ""


# -- Worktime response schemas ------------------------------------------------

class WorktimeSummary(BaseModel):
    """Worktime summary response with range constraints."""
    totalOps: int = Field(default=0, ge=0)
    avgEfficiency: float = Field(default=0.0, ge=0.0, le=500.0)
    wasteRatio: float = Field(default=0.0, ge=0.0, le=100.0)
    totalStdTimeHours: float = Field(default=0.0, ge=0.0)


class WorktimeOperation(BaseModel):
    """Worktime operation record with range constraints."""
    id: int = Field(ge=0)
    operation: str
    station: str
    actual: float = Field(ge=0.0)
    standard: float = Field(ge=0.0)
    efficiency: float = Field(ge=0.0, le=500.0)
    modTotal: float = Field(default=0.0, ge=0.0)
    wastePct: float = Field(default=0.0, ge=0.0, le=100.0)


class MonthlyOutput(BaseModel):
    """Monthly output trend data with range constraints."""
    labels: list = Field(default_factory=list)
    values: list = Field(default_factory=list)


# -- Validation helper --------------------------------------------------------

import logging as _logging

_logger = _logging.getLogger(__name__)


def validate_response_data(model_class, data: dict) -> dict:
    """Validate response data dict against a Pydantic model with Field constraints.

    Raises ValueError with a descriptive message if any field is out of range,
    which FastAPI will convert to a 400 response. Otherwise returns the
    validated (and default-populated) dict.

    Args:
        model_class: A Pydantic BaseModel subclass with Field(ge=/le=) constraints.
        data: Raw data dict to validate.

    Returns:
        Dict with validated values (missing fields filled with defaults).

    Raises:
        ValueError: If validation fails (caught by FastAPI as 400).
    """
    try:
        return model_class.model_validate(data).model_dump()
    except ValidationError as e:
        errors = [
            f"{err['loc'][0]}: {err['msg']}" for err in e.errors()
        ]
        msg = f"response validation failed: {'; '.join(errors)}"
        _logger.error("%s | data=%s", msg, data)
        raise ValueError(msg)
