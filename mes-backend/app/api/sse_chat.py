"""SSE streaming chat endpoint for AI analysis.

Provides a POST endpoint that returns a Server-Sent Events stream
with incremental AI response chunks from the AI Gateway.

Endpoints:
  POST /api/ai/chat/stream  - SSE streaming AI chat (requires JWT)
  GET  /api/ai/task/{task_id}/status  - async task status query
  POST /api/ai/chat/submit  - submit async analysis task
"""

from __future__ import annotations

import asyncio
import json
import logging
from datetime import datetime, timezone
from typing import Optional

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Request
from fastapi.responses import StreamingResponse
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from pydantic import BaseModel, Field, model_validator
from sqlalchemy.orm import Session

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/ai", tags=["ai-chat"])

_security = HTTPBearer(auto_error=False)

from app.api.deps import get_db_session
from app.models.schemas import ApiResponse

# Fallback gateway (used only when lifespan init failed)
_gateway = None
_gateway_lock = asyncio.Lock()


# ── Request/Response Models ──────────────────────────────────────────

class StreamChatRequest(BaseModel):
    message: str = Field(..., min_length=1, max_length=4000)
    context: Optional[dict] = Field(
        default=None,
        description="Key-value context pairs for AI analysis. "
        "Keys must match ^[a-zA-Z0-9_-]{1,32}$, values max 256 chars.",
    )

    @classmethod
    def _validate_context(cls, values):
        """Validate context keys and values.

        Kept as a standalone helper for backward compatibility.
        Called from the Pydantic V2 model_validator below.
        """
        ctx = values.get("context")
        if ctx is not None:
            import re
            for key, value in ctx.items():
                if not re.match(r"^[a-zA-Z0-9_-]{1,32}$", key):
                    raise ValueError(
                        f"Invalid context key: '{key}'. "
                        "Keys must be 1-32 chars, alphanumeric, underscore, or hyphen."
                    )
                if not isinstance(value, (str, int, float, bool, type(None))):
                    raise ValueError(f"Invalid context value type for key '{key}'")
                if isinstance(value, str) and len(value) > 256:
                    raise ValueError(
                        f"Context value for '{key}' exceeds 256 char limit"
                    )
        return values

    # Pydantic V2 model validator (replaces V1 __get_validators__)
    @model_validator(mode="before")
    @classmethod
    def _validate_all(cls, values):
        return cls._validate_context(values)


class SubmitAnalysisRequest(BaseModel):
    analysis_type: str = Field(..., pattern=r"^(worktime|line_balance|report|therblig_optimization)$")
    station_id: Optional[str] = None
    period: Optional[str] = "today"
    context_data: Optional[dict] = None


class SubmitAnalysisResponse(BaseModel):
    task_id: str


class TaskStatusResponse(BaseModel):
    task_id: str
    status: str
    progress: Optional[int] = None
    result: Optional[dict] = None
    error: Optional[str] = None


# ── Gateway Access ────────────────────────────────────────────────


async def _get_gateway(request: Request):
    """Get the AI Gateway from app.state (initialized in lifespan).

    Falls back to a standalone instance if lifespan init failed.
    """
    gateway = getattr(request.app.state, "ai_gateway", None)
    if gateway is not None:
        return gateway

    # Fallback: create standalone instance without cache
    global _gateway
    if _gateway is None:
        async with _gateway_lock:
            if _gateway is None:
                from app.services.ai_gateway import AIGateway
                _gateway = AIGateway()
                logger.warning("SSE chat: using fallback AI Gateway (no Redis cache)")
    return _gateway


# ── JWT Auth Helper ─────────────────────────────────────────────────

def _get_current_user(credentials: HTTPAuthorizationCredentials):
    """Extract current user from JWT, raise 401 if invalid."""
    if credentials is None:
        raise HTTPException(status_code=401, detail="Not authenticated")
    from app.api.v1.auth import get_current_user
    return get_current_user(credentials)


# ── SSE Streaming Endpoint ──────────────────────────────────────────

@router.post("/chat/stream")
async def chat_stream(
    req: StreamChatRequest,
    request: Request,
    credentials: HTTPAuthorizationCredentials = Depends(_security),
):
    """Stream AI chat responses via Server-Sent Events.

    Returns SSE stream with incremental response chunks.
    Requires JWT authentication.
    """
    user = _get_current_user(credentials)
    gateway = await _get_gateway(request)

    async def event_generator():
        try:
            async for chunk in gateway.analyze_stream(
                prompt=req.message,
                context=req.context or {},
            ):
                # Check if client disconnected
                if await request.is_disconnected():
                    break

                data = json.dumps({"content": chunk}, ensure_ascii=False)
                yield f"data: {data}\n\n"

            # Send completion event
            yield f"data: {json.dumps({'done': True}, ensure_ascii=False)}\n\n"

        except Exception as e:
            logger.error("SSE stream error for user %s: %s", user.get("sub", "?"), e, exc_info=True)
            error_data = json.dumps(
                {"type": "error", "message": "Internal server error"}, ensure_ascii=False,
            )
            yield f"data: {error_data}\n\n"

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )


# ── Async Task Submission ───────────────────────────────────────────

@router.post("/chat/submit", response_model=SubmitAnalysisResponse)
async def submit_analysis(
    req: SubmitAnalysisRequest,
    request: Request,
    background_tasks: BackgroundTasks,
    credentials: HTTPAuthorizationCredentials = Depends(_security),
    db: Session = Depends(get_db_session),
):
    """Submit an async AI analysis task.

    Returns a task_id for polling via GET /api/ai/task/{task_id}/status.
    """
    _get_current_user(credentials)
    gateway = await _get_gateway(request)

    from app.models.database import AIAnalysisResult

    try:
        from app.services.ai_tasks import (
            analyze_worktime_task,
            analyze_line_balance_task,
            analyze_therblig_task,
            generate_report_task,
        )

        if req.analysis_type == "worktime":
            task = analyze_worktime_task.delay(
                station_id=req.station_id or "unknown",
                period=req.period,
                context_data=req.context_data or {},
            )
        elif req.analysis_type == "line_balance":
            task = analyze_line_balance_task.delay(
                line_id=req.station_id or "unknown",
                context_data=req.context_data or {},
            )
        elif req.analysis_type == "therblig_optimization":
            ctx = req.context_data or {}
            task = analyze_therblig_task.delay(
                station_id=req.station_id or "unknown",
                therblig_stats=ctx.get("therblig_stats"),
                mod_data=ctx.get("mod_data"),
                context_data=ctx,
            )
        elif req.analysis_type == "report":
            task = generate_report_task.delay(
                report_type=req.context_data.get("report_type", "general") if req.context_data else "general",
                params=req.context_data or {},
            )
        else:
            raise HTTPException(status_code=400, detail="Unsupported analysis type")

        task_id = task.id

        # Persist task record via Depends-injected session (C-P1-3)
        def _persist_record():
            record = AIAnalysisResult(
                task_id=task_id,
                station_id=req.station_id,
                analysis_type=req.analysis_type,
                status="pending",
            )
            db.add(record)
            db.commit()

        await asyncio.get_running_loop().run_in_executor(None, _persist_record)

        return SubmitAnalysisResponse(task_id=task_id)

    except HTTPException:
        raise
    except Exception as e:
        logger.error("Failed to submit analysis task: %s", e, exc_info=True)
        raise HTTPException(status_code=500, detail="Task submission failed")


# ── Task Status Query ───────────────────────────────────────────────

@router.get("/task/{task_id}/status", response_model=TaskStatusResponse)
async def get_task_status(
    task_id: str,
    credentials: HTTPAuthorizationCredentials = Depends(_security),
    db: Session = Depends(get_db_session),
):
    """Query the status of an async AI analysis task.

    Checks both Celery result backend and local database for status.
    """
    _get_current_user(credentials)

    from app.models.database import AIAnalysisResult

    # Query local database (sync operation) in executor to avoid blocking event loop
    loop = asyncio.get_running_loop()

    def _query_record():
        return db.query(AIAnalysisResult).filter(
            AIAnalysisResult.task_id == task_id
        ).first()

    record = await loop.run_in_executor(None, _query_record)

    if record is None:
        raise HTTPException(status_code=404, detail="Task not found")

    response = TaskStatusResponse(
        task_id=record.task_id,
        status=record.status,
        result=json.loads(record.result) if record.result else None,
        error=record.error,
    )

    # If still pending/processing, also check Celery
    if record.status in ("pending", "processing"):
        try:
            from app.core.celery_app import celery
            async_result = celery.AsyncResult(task_id)

            if async_result.ready():
                if async_result.failed():
                    record.status = "failed"
                    _err_msg = str(async_result.result) if async_result.result else "Unknown error"
                    record.error = _err_msg[:500]
                    record.failed_at = datetime.now(timezone.utc)

                    def _update_failed():
                        db.commit()

                    await loop.run_in_executor(None, _update_failed)

                    response.status = "failed"
                    response.error = record.error
                else:
                    result_data = async_result.result
                    record.status = "completed"
                    record.result = json.dumps(result_data, ensure_ascii=False, default=str)
                    record.model_source = result_data.get("model_source", "unknown")
                    record.completed_at = datetime.now(timezone.utc)

                    def _update_completed():
                        db.commit()

                    await loop.run_in_executor(None, _update_completed)

                    response.status = "completed"
                    response.result = result_data
            elif async_result.state == "STARTED":
                response.status = "processing"

        except Exception as e:
            logger.warning("Celery status check failed: %s", e)

    return response


# ── Task List ────────────────────────────────────────────────────────

@router.get("/tasks")
async def list_tasks(
    analysis_type: Optional[str] = None,
    station_id: Optional[str] = None,
    limit: int = 20,
    offset: int = 0,
    credentials: HTTPAuthorizationCredentials = Depends(_security),
    db: Session = Depends(get_db_session),
):
    """List AI analysis tasks with optional filtering."""
    _get_current_user(credentials)

    from app.models.database import AIAnalysisResult

    loop = asyncio.get_running_loop()

    def _query_tasks():
        query = db.query(AIAnalysisResult).order_by(AIAnalysisResult.created_at.desc())

        if analysis_type:
            query = query.filter(AIAnalysisResult.analysis_type == analysis_type)
        if station_id:
            query = query.filter(AIAnalysisResult.station_id == station_id)

        total = query.count()
        records = query.offset(offset).limit(limit).all()
        return total, records

    total, records = await loop.run_in_executor(None, _query_tasks)

    import time as _time

    return ApiResponse(
        data={
            "tasks": [
                {
                    "task_id": r.task_id,
                    "station_id": r.station_id,
                    "analysis_type": r.analysis_type,
                    "status": r.status,
                    "model_source": r.model_source,
                    "created_at": r.created_at.isoformat() if r.created_at else None,
                    "completed_at": r.completed_at.isoformat() if r.completed_at else None,
                    "duration_ms": r.duration_ms,
                }
                for r in records
            ],
            "total": total,
            "limit": limit,
            "offset": offset,
        },
        timestamp=_time.time(),
    )


# ── AI Health / Context ──────────────────────────────────────────────

@router.get("/health")
async def ai_health(
    request: Request,
    credentials: HTTPAuthorizationCredentials = Depends(_security),
):
    """Get AI service health status."""
    _get_current_user(credentials)
    gateway = await _get_gateway(request)
    return ApiResponse(
        data=gateway.get_status(),
    )
