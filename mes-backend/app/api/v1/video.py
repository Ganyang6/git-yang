"""Video upload and task management API routes.

Endpoints:
  POST /api/v1/video/upload        - Upload video file
  GET  /api/v1/video/tasks         - List all video processing tasks
  GET  /api/v1/video/tasks/{id}    - Get single task detail
  POST /api/v1/video/tasks/{id}/cancel - Cancel a processing task
  GET  /api/v1/video/tasks/{id}/stream  - SSE progress stream

Phase 9: Web-based video upload replacing manual CLI workflow.
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import re
import tempfile
import time
import uuid
from pathlib import Path
from typing import Optional

import jwt

from fastapi import APIRouter, Depends, HTTPException, Query, Request, UploadFile, File, Form
from fastapi.responses import StreamingResponse

from app.api.deps import require_auth, require_engineer_or_above
from app.models.schemas import ApiResponse
from app.services.video_task_manager import get_task_manager
from app.core.redis_client import CHANNEL_VIDEO_COMMANDS

logger = logging.getLogger("mes_backend.video")

router = APIRouter(prefix="/api/v1/video", tags=["video"])


def _get_mgr(request: Request):
    """Get VideoTaskManager with shared Redis client from app state."""
    redis_client = getattr(request.app.state, "redis_client", None)
    return get_task_manager(use_redis=True, redis_client=redis_client)

# Configurable via environment variable or patch in tests
VIDEO_UPLOAD_DIR = Path("data/videos")
VIDEO_SIZE_LIMIT_MB = int(os.environ.get("VIDEO_SIZE_LIMIT_MB", "500"))

# Video format magic bytes (first N bytes of the file)
# ISO BMFF (MP4/MOV) shares ftyp box at offset 4 -- brand at bytes 8-12 disambiguates.
_VIDEO_SIGNATURES = [
    (b"ftyp", 4, "mp4"),       # ISO BMFF: ftyp box at offset 4 (further brand check below)
    (b"RIFF", 0, "avi"),       # AVI: RIFF header
    (b"\x1a\x45\xdf\xa3", 0, "mkv"),  # MKV: EBML header
]

# ISO BMFF brands: "qt  " -> MOV, others (isom/mp41/mp42/M4V/etc.) -> MP4
_MOV_BRANDS = {b"qt  "}
_ALLOWED_EXTENSIONS = {".mp4", ".avi", ".mov", ".mkv"}

_STATION_ID_RE = re.compile(r"^[A-Za-z0-9_-]{1,32}$")


def _detect_video_format(content: bytes) -> Optional[str]:
    """Detect video format from file header magic bytes.

    For ISO BMFF containers (ftyp at offset 4), extracts the brand field
    at bytes 8-12 to distinguish MOV ("qt  ") from MP4 (all others).
    """
    if len(content) < 12:
        return None

    for magic, offset, fmt in _VIDEO_SIGNATURES:
        if content[offset:offset + len(magic)] == magic:
            # Disambiguate MOV vs MP4 for ISO BMFF (ftyp)
            if fmt == "mp4" and len(content) >= 12:
                brand = content[8:12]
                if brand in _MOV_BRANDS:
                    return "mov"
            return fmt

    return None


async def _publish_pipeline_command(
    redis_client,
    task_id: str,
    filename: str,
    station_id: str,
    shift: str = "morning",
    line: str = "",
) -> bool:
    """Publish a pipeline trigger command to Redis Pub/Sub.

    The perception container subscribes to CHANNEL_VIDEO_COMMANDS and
    starts the video pipeline upon receiving a command message.

    Message format: {"task_id": ..., "filename": ..., "station_id": ..., "shift": ...}

    Returns True if published successfully, False otherwise.
    """
    message = json.dumps({
        "task_id": task_id,
        "filename": filename,
        "station_id": station_id,
        "shift": shift,
        "line": line,
    })

    try:
        result = await redis_client.publish_channel(CHANNEL_VIDEO_COMMANDS, message)
        if result:
            logger.info(
                "Pipeline command published: task_id=%s file=%s station=%s",
                task_id, filename, station_id,
            )
        else:
            logger.warning("Pipeline command publish returned 0 subscribers")
        return result
    except Exception as e:
        logger.error("Failed to publish pipeline command: %s", e)
        return False


# ── Stations ──────────────────────────────────────────────────────────


@router.get("/stations")
def list_stations(
    _user: dict = Depends(require_auth),
):
    """Return available workstation list."""
    return {
        "code": 0,
        "data": [
            {"id": "WS-01", "name": "工位 1"},
            {"id": "WS-02", "name": "工位 2"},
            {"id": "WS-03", "name": "工位 3"},
            {"id": "WS-04", "name": "工位 4"},
        ],
    }


# ── Upload ────────────────────────────────────────────────────────────


@router.post("/upload")
async def upload_video(
    request: Request,
    file: UploadFile = File(...),
    station_id: str = Form("WS-01"),
    shift: str = Form("morning"),
    line: str = Form(""),
    _user: dict = Depends(require_engineer_or_above),
):
    """Upload a video file for processing.

    Accepts mp4, avi, mov, mkv formats (validated by file header).
    File size limited by VIDEO_SIZE_LIMIT_MB (default 500MB).
    Saved to VIDEO_UPLOAD_DIR with UUID filename.
    Registers a task in VideoTaskManager.
    """
    # Validate station_id format
    if not _STATION_ID_RE.match(station_id):
        raise HTTPException(
            status_code=422,
            detail="station_id must be 1-32 alphanumeric characters, hyphens or underscores",
        )

    # Ensure upload directory exists
    upload_dir = Path(VIDEO_UPLOAD_DIR)
    upload_dir.mkdir(parents=True, exist_ok=True)

    # Stream to temporary file to avoid loading entire content into memory
    temp_path: Optional[Path] = None
    size_limit = VIDEO_SIZE_LIMIT_MB * 1024 * 1024
    chunk_size = 1024 * 1024  # 1MB chunks
    total_size = 0

    try:
        with tempfile.NamedTemporaryFile(
            dir=str(upload_dir), delete=False, suffix=".upload"
        ) as tmp:
            temp_path = Path(tmp.name)
            while True:
                chunk = await file.read(chunk_size)
                if not chunk:
                    break
                total_size += len(chunk)
                if total_size > size_limit:
                    raise HTTPException(
                        status_code=413,
                        detail=f"File size exceeds limit {VIDEO_SIZE_LIMIT_MB}MB",
                    )
                tmp.write(chunk)

        # Validate format by reading file header from disk
        header = temp_path.read_bytes()[:12] if temp_path.exists() else b""
        fmt = _detect_video_format(header)
        if fmt is None:
            temp_path.unlink(missing_ok=True)
            raise HTTPException(
                status_code=400,
                detail="Unsupported video format. Accepted: mp4, avi, mov, mkv",
            )

        # Generate UUID filename preserving extension
        original_ext = Path(file.filename).suffix.lower() if file.filename else f".{fmt}"
        if original_ext not in _ALLOWED_EXTENSIONS:
            original_ext = f".{fmt}"
        saved_filename = f"{uuid.uuid4()}{original_ext}"
        saved_path = upload_dir / saved_filename

        # Atomic rename from temp to final path
        temp_path.rename(saved_path)
        temp_path = None  # prevent cleanup in finally

    except HTTPException:
        raise
    except Exception as exc:
        logger.error("Video upload write failed: %s", exc)
        if temp_path is not None:
            temp_path.unlink(missing_ok=True)
        raise HTTPException(status_code=500, detail="Failed to save uploaded file")
    finally:
        if temp_path is not None:
            temp_path.unlink(missing_ok=True)

    # Register task in manager
    mgr = _get_mgr(request)
    task = mgr.create_task(
        filename=saved_filename,
        original_name=file.filename or "",
        size=total_size,
        station_id=station_id,
        shift=shift,
        line=line,
        video_format=fmt,
    )

    size_mb = total_size / (1024 * 1024)
    logger.info(
        "Video uploaded: task_id=%s file=%s size=%.1fMB fmt=%s station=%s shift=%s",
        task["task_id"], saved_filename, size_mb, fmt, station_id, shift,
    )

    # Attempt to trigger the perception pipeline via Redis command
    redis_client = _get_redis_client(request)
    pipeline_triggered = False
    if redis_client is not None and redis_client.is_connected:
        pipeline_triggered = await _publish_pipeline_command(
            redis_client,
            task_id=task["task_id"],
            filename=saved_filename,
            station_id=station_id,
            shift=shift,
            line=line,
        )
        if not pipeline_triggered:
            logger.warning(
                "Pipeline command publish returned 0 subscribers, "
                "task %s started anyway (will be picked up when "
                "perception container subscribes)",
                task["task_id"],
            )

    # Always start the task regardless of Redis availability.
    # The perception container will pick up the task when it subscribes.
    mgr.start_task(task["task_id"])

    return ApiResponse(
        data={
            "task_id": task["task_id"],
            "filename": saved_filename,
            "original_name": file.filename or "",
            "size": total_size,
            "format": fmt,
            "station_id": station_id,
            "shift": shift,
            "line": line,
            "status": task["status"],
        },
        timestamp=time.time(),
    )


# ── Task Management ───────────────────────────────────────────────────


@router.get("/tasks")
async def list_tasks(
    request: Request,
    _user: dict = Depends(require_auth),
):
    """List all video processing tasks, newest first."""
    mgr = _get_mgr(request)
    tasks = mgr.list_tasks()
    return ApiResponse(data=tasks, timestamp=time.time())


@router.get("/tasks/{task_id}")
async def get_task(
    task_id: str,
    request: Request,
    _user: dict = Depends(require_auth),
):
    """Get details of a single video processing task."""
    mgr = _get_mgr(request)
    task = mgr.get_task(task_id)
    if task is None:
        raise HTTPException(status_code=404, detail="Task not found")
    return ApiResponse(data=task, timestamp=time.time())


@router.post("/tasks/{task_id}/cancel")
async def cancel_task(
    task_id: str,
    request: Request,
    _user: dict = Depends(require_engineer_or_above),
):
    """Cancel a processing video task.

    Only tasks in 'processing' state can be cancelled.
    """
    mgr = _get_mgr(request)
    task = mgr.get_task(task_id)
    if task is None:
        raise HTTPException(status_code=404, detail="Task not found")

    if task["status"] != "processing":
        raise HTTPException(
            status_code=400,
            detail=f"Cannot cancel task in '{task['status']}' state",
        )

    success = mgr.cancel_task(task_id)
    if not success:
        raise HTTPException(status_code=400, detail="Failed to cancel task")

    return ApiResponse(
        data={"task_id": task_id, "status": "cancelled"},
        timestamp=time.time(),
    )


# ── SSE Progress Stream ─────────────────────────────────────────────


def _get_redis_client(request: Request):
    """Retrieve the RedisClient from app.state."""
    return getattr(request.app.state, "redis_client", None)


def _format_sse(event_type: str, data: dict) -> str:
    """Format data as Server-Sent Events string."""
    payload = json.dumps(data, ensure_ascii=False)
    return f"event: {event_type}\ndata: {payload}\n\n"


@router.get("/tasks/{task_id}/stream")
async def stream_task_progress(
    task_id: str,
    request: Request,
):
    """SSE endpoint for real-time video processing progress.

    Subscribes to Redis Pub/Sub channel:video_progress and filters
    messages for the given task_id. Falls back to polling the
    VideoTaskManager if Redis is unavailable.

    Authentication: uses Authorization header (Bearer token) only.
    """
    # JWT authentication: Authorization header only (P1-13)
    auth_header = request.headers.get("authorization", "")
    auth_token = ""
    if auth_header.startswith("Bearer "):
        auth_token = auth_header[7:]

    if not auth_token:
        async def auth_fail():
            yield _format_sse("error", {"status": "auth_required"})
        return StreamingResponse(auth_fail(), media_type="text/event-stream")

    try:
        from app.api.v1.auth import _get_jwt_secret
        secret = _get_jwt_secret()
        jwt.decode(auth_token, secret, algorithms=["HS256"])
    except (jwt.InvalidTokenError, jwt.ExpiredSignatureError, KeyError, ValueError):
        async def invalid():
            yield _format_sse("error", {"status": "auth_failed"})
        return StreamingResponse(invalid(), media_type="text/event-stream")

    mgr = _get_mgr(request)
    task = mgr.get_task(task_id)

    # Check if already terminal -- return immediately
    if task is not None and task["status"] in ("completed", "failed", "cancelled"):
        async def terminal_gen():
            yield _format_sse("progress", {
                "task_id": task_id,
                "progress": task.get("progress", 0.0),
                "status": task.get("status"),
                "total_frames": task.get("total_frames", 0),
                "processed_frames": task.get("processed_frames", 0),
                "duration_s": task.get("duration_s", 0.0),
                "error": task.get("error"),
            })
        return StreamingResponse(terminal_gen(), media_type="text/event-stream")

    # Subscribe to Redis Pub/Sub for live progress
    redis_client = _get_redis_client(request)
    if redis_client is None or not redis_client.is_connected:
        logger.info("SSE progress: Redis not available, using fallback")
        return StreamingResponse(
            _poll_fallback(mgr, task_id, redis_client),
            media_type="text/event-stream",
        )

    from app.core.redis_client import CHANNEL_VIDEO_PROGRESS
    channel = f"{CHANNEL_VIDEO_PROGRESS}:{task_id}"

    async def event_generator():
        """Subscribe to Redis Pub/Sub and forward progress events."""

        # P1-2 FIX: Send current state immediately with timeout awareness
        if task is not None:
            status = task.get("status", "unknown")
            progress = task.get("progress", 0.0)
            
            # If task has been PENDING too long, notify frontend
            import time as _time
            created_at = task.get("created_at", 0)
            pending_timeout = _time.time() - created_at if created_at else 0
            if status == "pending" and pending_timeout > 30:
                yield _format_sse("progress", {
                    "task_id": task_id,
                    "progress": 0.0,
                    "status": "waiting",
                    "message": "Waiting for perception container (timeout)",
                    "total_frames": 0,
                    "processed_frames": 0,
                    "error": None,
                })
                return
            
            yield _format_sse("progress", {
                "task_id": task_id,
                "progress": progress,
                "status": status,
                "total_frames": task.get("total_frames", 0),
                "processed_frames": task.get("processed_frames", 0),
                "error": task.get("error"),
                "message": "waiting_for_perception" if status == "pending" else None,
                "pending_seconds": round(pending_timeout, 1) if status == "pending" else None,
            })

        try:
            channel_iter = redis_client.listen_channel(channel)

            while not await request.is_disconnected():
                try:
                    raw_msg = await asyncio.wait_for(
                        channel_iter.__anext__(),
                        timeout=30.0,
                    )
                except asyncio.TimeoutError:
                    # Heartbeat to keep connection alive
                    yield _format_sse("heartbeat", {"time": time.time()})
                    continue
                except StopAsyncIteration:
                    # Channel closed (e.g. unsubscribe)
                    break

                # raw_msg from listen_channel is the data field (bytes/str)
                if isinstance(raw_msg, bytes):
                    raw_msg = raw_msg.decode("utf-8", errors="replace")

                try:
                    data = json.loads(raw_msg)
                except (json.JSONDecodeError, TypeError):
                    continue

                # Update task manager with progress
                mgr.update_progress(
                    task_id,
                    progress=data.get("progress", 0.0),
                    processed_frames=data.get("processed_frames", 0),
                    total_frames=data.get("total_frames", 0),
                )

                status = data.get("status", "processing")

                # Handle terminal statuses
                if status == "completed":
                    mgr.complete_task(
                        task_id,
                        total_frames=data.get("total_frames", 0),
                        duration_s=data.get("duration_s", 0.0),
                    )
                elif status == "failed":
                    mgr.fail_task(task_id, error=data.get("error", "Unknown error"))

                # Phase 1 修正：从 mgr 获取最新数据，覆盖 Pub/Sub 原始数据中的字段
                updated = mgr.get_task(task_id)
                if updated and updated.get("processed_frames", 0) > (data.get("processed_frames", 0) or 0):
                    data["processed_frames"] = updated["processed_frames"]
                if updated and updated.get("total_frames", 0) > (data.get("total_frames", 0) or 0):
                    data["total_frames"] = updated["total_frames"]

                yield _format_sse("progress", data)

                # Stop on terminal status
                if status in ("completed", "failed", "cancelled"):
                    break

        except asyncio.CancelledError:
            logger.info("SSE progress stream cancelled")

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )




async def _poll_fallback(mgr, task_id: str, redis_client=None):
    """Poll VideoTaskManager and Redis Stream when Pub/Sub is unavailable.
    
    P1-4 FIX: Added timeout detection for PENDING tasks.
    """
    start_time = time.time()
    for i in range(60):  # 60 polls * 2s = 2 minutes max fallback
        task = mgr.get_task(task_id)
        progress_data = {
            "task_id": task_id,
            "progress": 0.0,
            "status": "unknown",
        }
        
        # P1-4 FIX: Check if task has been PENDING too long (>60s)
        if task and task.get("status") == "pending":
            elapsed = time.time() - start_time
            if elapsed > 60:
                logger.warning(
                    "Task %s PENDING for %.0fs, marking as failed",
                    task_id, elapsed,
                )
                mgr.fail_task(task_id, error="Perception container not responding (timeout)")
                progress_data.update({
                    "progress": 0.0,
                    "status": "failed",
                    "error": "Perception container not responding after 60s",
                })
                yield _format_sse("progress", progress_data)
                break
        
        # Try to get latest progress from Redis Stream first
        if redis_client and redis_client.is_connected:
            try:
                import redis.asyncio as aioredis
                r = await redis_client.ensure_connected()
                # Get recent progress entries from Stream (max 50 entries)
                result = await r.xrevrange(
                    "mes:video_progress",
                    count=50,
                )
                if result:
                    for msg_id, fields in result:
                        if fields.get("task_id") == task_id:
                            progress_data = {
                                "task_id": task_id,
                                "progress": float(fields.get("progress", 0.0)),
                                "status": fields.get("status", "processing"),
                                "processed_frames": int(fields.get("processed_frames", 0)),
                                "total_frames": int(fields.get("total_frames", 0)),
                                "duration_s": float(fields.get("duration_s", 0.0)),
                                "error": fields.get("error", ""),
                            }
                            break
            except Exception:
                logger.warning("P1-7: Redis Stream fallback read failed for task %s", task_id, exc_info=True)
        
        # Fall back to task manager if Stream not available
        if task:
            progress_data.update({
                "progress": task.get("progress", progress_data["progress"]),
                "status": task.get("status", progress_data["status"]),
            })
            if task["status"] in ("completed", "failed", "cancelled"):
                yield _format_sse("progress", progress_data)
                break
        
        yield _format_sse("progress", progress_data)
        await asyncio.sleep(2.0)
