"""Video task manager service.

Manages the lifecycle of video processing tasks:
  pending -> processing -> completed/failed/cancelled

Singleton instance accessible via get_task_manager().
"""

from __future__ import annotations

import asyncio
import concurrent.futures
import json
import logging
import os
import time
import uuid
from datetime import datetime, timedelta, timezone
from enum import Enum
from pathlib import Path
from typing import Dict, List, Optional

from app.core.redis_client import RedisClient

# Celery app for periodic task registration
# (imported here to keep video cleanup logic co-located)
from app.core.celery_app import celery
import redis as sync_redis
from app.core.metrics import tasks_created, tasks_completed, tasks_failed, tasks_archived

logger = logging.getLogger("mes_backend.video_tasks")

TASK_TIMEOUT_S = int(os.environ.get("VIDEO_TASK_TIMEOUT_S", "1800"))

REDIS_KEY_TASKS = "mes:video:tasks"
REDIS_KEY_LOCK = "mes:video:processing:lock"
REDIS_LOCK_TTL = 300

# Upload directory used for file cleanup
VIDEO_UPLOAD_DIR = Path("data/videos")


class TaskStatus(str, Enum):
    PENDING = "pending"
    PROCESSING = "processing"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"


_main_loop: Optional[asyncio.AbstractEventLoop] = None


def set_main_loop(loop: asyncio.AbstractEventLoop) -> None:
    """Store the main event loop reference for thread-safe coroutine dispatch."""
    global _main_loop
    _main_loop = loop


def _run_async(coro, default=None):
    """Run an async coroutine from a sync context.

    When called from within the running event loop (FastAPI route handlers),
    runs the coroutine in a **separate thread with its own event loop** to
    avoid deadlocking the main loop.

    Note: async coroutines that use Redis operations from app.state.redis_client
    (which has a pool bound to the main loop) will fail when called from a
    different loop. The VideoTaskManager now uses its own sync Redis client
    (redis.Redis) instead of the async one to avoid this issue.

    When called from outside any event loop (CLI / test), uses asyncio.run().

    Args:
        coro: The async coroutine to execute.
        default: Value to return on timeout (None = raise TimeoutError).

    Returns:
        The coroutine's return value, or *default* on timeout.

    Raises:
        Exception from the coroutine on failure.
    """
    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:
        loop = None

    if loop is not None and loop.is_running():
        executor = concurrent.futures.ThreadPoolExecutor(max_workers=1)
        try:
            future = executor.submit(_run_coro_in_new_loop, coro)
            return future.result(timeout=10.0)
        except concurrent.futures.TimeoutError:
            if default is None:
                raise TimeoutError(
                    f"Coroutine {coro.__qualname__} did not complete within 10s"
                )
            logger.warning(
                "Coroutine %s timed out after 10s in thread, returning default",
                coro.__qualname__,
            )
            return default
        finally:
            executor.shutdown(wait=False)
    else:
        return asyncio.run(coro)


def _run_coro_in_new_loop(coro):
    """Run an async coroutine in a fresh event loop (called from a thread)."""
    new_loop = asyncio.new_event_loop()
    asyncio.set_event_loop(new_loop)
    try:
        return new_loop.run_until_complete(coro)
    finally:
        new_loop.close()


def _validate_filename(filename: str) -> Path:
    """Validate a filename is safe (no path traversal) and return its Path.

    Raises ValueError if the filename contains path traversal components
    ("..") or is an absolute path.
    """
    p = Path(filename)
    if p.is_absolute():
        raise ValueError(f"Absolute path not allowed: {filename}")
    # Normalize and check for directory traversal
    normalized = p.as_posix()
    if ".." in normalized.split("/"):
        raise ValueError(f"Path traversal detected: {filename}")
    if "/" in normalized:
        raise ValueError(f"Subdirectory paths not allowed: {filename}")

    resolved = (VIDEO_UPLOAD_DIR / p).resolve()
    upload_dir_resolved = VIDEO_UPLOAD_DIR.resolve()
    if not str(resolved).startswith(str(upload_dir_resolved)):
        raise ValueError(f"Filename escapes upload directory: {filename}")
    return resolved


def _delete_video_file(filename: str) -> bool:
    """Delete a video source file by filename with safety checks.

    Validates the filename for path traversal, then removes the file.
    Returns True if deleted (or already gone), False on error.
    """
    try:
        filepath = _validate_filename(filename)
    except ValueError as e:
        logger.warning("Skipping file deletion - invalid filename '%s': %s", filename, e)
        return False

    try:
        if filepath.exists():
            os.remove(str(filepath))
            logger.info("Deleted source file: %s", filename)
            return True
        else:
            logger.warning("Source file already missing: %s", filename)
            return True  # Already gone, consider success
    except OSError as e:
        logger.error("Failed to delete source file %s: %s", filename, e)
        return False


class VideoTaskManager:
    """Video processing task manager with Redis support.

    Supports both in-memory (single-process) and Redis (multi-process) storage.
    Uses Redis distributed lock to ensure only one task is processing at a time.

    When an external redis_client is provided (from app.state.redis_client),
    it is reused directly instead of creating a new connection.
    """

    def __init__(
        self,
        task_timeout_s: float = TASK_TIMEOUT_S,
        use_redis: bool = False,
        redis_client: Optional[RedisClient] = None,
    ):
        self._tasks: Dict[str, dict] = {}
        self._processing_task_id: Optional[str] = None
        self._task_timeout_s = task_timeout_s
        self.use_redis = use_redis
        self._sync_r = None

        if self.use_redis:
            try:
                redis_url = os.environ.get(
                    "REDIS_URL",
                    os.environ.get("CELERY_BROKER_URL", "redis://redis:6379/0"),
                )
                self._sync_r = sync_redis.Redis.from_url(
                    redis_url,
                    decode_responses=True,
                    socket_connect_timeout=5,
                    socket_timeout=5,
                )
                self._sync_r.ping()
                logger.info(
                    "VideoTaskManager initialized with sync Redis backend (%s)",
                    redis_url.split("@")[-1],
                )
            except Exception as e:
                logger.error("Failed to initialize sync Redis client: %s", e)
                self.use_redis = False
                self._sync_r = None
                logger.warning("Falling back to in-memory storage")

    def create_task(
        self,
        filename: str,
        original_name: str,
        size: int,
        station_id: str,
        video_format: str,
        shift: str = "morning",
        line: str = "",
    ) -> dict:
        task_id = str(uuid.uuid4())
        now = time.time()

        task = {
            "task_id": task_id,
            "filename": filename,
            "original_name": original_name,
            "size": size,
            "station_id": station_id,
            "line": line,
            "shift": shift,
            "format": video_format,
            "status": TaskStatus.PENDING,
            "created_at": now,
            "started_at": None,
            "completed_at": None,
            "progress": 0.0,
            "total_frames": 0,
            "processed_frames": 0,
            "duration_s": 0.0,
            "error": None,
        }

        if self.use_redis:
            try:
                saved = self._save_task_sync(task)
                if not saved:
                    logger.warning(
                        "Redis save failed for task %s (may be timed out), "
                        "falling back to in-memory store",
                        task_id,
                    )
                    self.use_redis = False
                    self._tasks[task_id] = task
            except Exception as e:
                logger.error(
                    "Failed to save task %s to Redis: %s", task_id, e,
                )
                self.use_redis = False
                self._tasks[task_id] = task
        else:
            self._tasks[task_id] = task

        tasks_created.inc()
        logger.info("Task created: %s file=%s station=%s shift=%s", task_id, filename, station_id, shift)
        return task

    def _save_task_sync(self, task: dict) -> bool:
        if not self._sync_r:
            return False
        try:
            self._sync_r.hset(REDIS_KEY_TASKS, task["task_id"], json.dumps(task))
            return True
        except Exception as e:
            logger.error("Failed to save task to Redis: %s", e)
            return False

    def get_task(self, task_id: str) -> Optional[dict]:
        if self.use_redis:
            try:
                return self._load_task_sync(task_id)
            except Exception as e:
                logger.error("Failed to get task from Redis: %s", e)
                return self._tasks.get(task_id)
        else:
            return self._tasks.get(task_id)

    def _load_task_sync(self, task_id: str) -> Optional[dict]:
        if not self._sync_r:
            return None
        try:
            data = self._sync_r.hget(REDIS_KEY_TASKS, task_id)
            if data:
                return json.loads(data)
            # Fallback: check archive key (terminal-state tasks with TTL)
            archived = self._sync_r.get(f"{REDIS_KEY_TASKS}:archive:{task_id}")
            if archived:
                try:
                    return json.loads(archived)
                except (json.JSONDecodeError, TypeError) as e:
                    logger.warning("Failed to parse archive data for task %s: %s", task_id, e)
            return None
        except Exception as e:
            logger.error("Failed to load task from Redis: %s", e)
            return None

    def list_tasks(self) -> List[dict]:
        if self.use_redis:
            try:
                tasks = self._load_all_tasks_sync()
                return sorted(
                    tasks,
                    key=lambda t: t.get("created_at", 0),
                    reverse=True,
                )
            except Exception as e:
                logger.error("Failed to list tasks from Redis: %s", e)
                return sorted(
                    self._tasks.values(),
                    key=lambda t: t.get("created_at", 0),
                    reverse=True,
                )
        else:
            return sorted(
                self._tasks.values(),
                key=lambda t: t.get("created_at", 0),
                reverse=True,
            )

    def _load_all_tasks_sync(self) -> List[dict]:
        if not self._sync_r:
            return []
        try:
            raw = self._sync_r.hgetall(REDIS_KEY_TASKS)
            tasks = []
            for key, value in raw.items():
                try:
                    tasks.append(json.loads(value))
                except Exception as e:
                    logger.error("Failed to parse task data: %s", e)
            return tasks
        except Exception as e:
            logger.error("Failed to load all tasks from Redis: %s", e)
            return []

    def start_task(self, task_id: str) -> bool:
        timed_out = self.check_timeouts()
        for tid in timed_out:
            logger.warning("Auto-failed timed out task: %s", tid)

        task = self.get_task(task_id)
        if task is None:
            return False

        if self.use_redis:
            acquired = self._acquire_lock_sync()
            if not acquired:
                logger.warning("Cannot start %s: failed to acquire Redis lock", task_id)
                return False
            # Re-fetch under lock to avoid TOCTOU race:
            # the task status may have changed between the initial
            # get_task() and the lock acquisition.
            task = self.get_task(task_id)
            if task is None:
                return False
        else:
            if self._processing_task_id is not None:
                existing = self.get_task(self._processing_task_id)
                if existing and existing["status"] == TaskStatus.PROCESSING:
                    logger.warning(
                        "Cannot start %s: %s is already processing",
                        task_id, self._processing_task_id,
                    )
                    return False

        if task["status"] != TaskStatus.PENDING:
            if self.use_redis:
                self._release_lock_sync()
            return False

        task["status"] = TaskStatus.PROCESSING
        task["started_at"] = time.time()
        self._processing_task_id = task_id

        if self.use_redis:
            try:
                saved = self._save_task_sync(task)
                if not saved:
                    logger.warning(
                        "Redis save of PROCESSING status failed for task %s, "
                        "falling back to in-memory store",
                        task_id,
                    )
                    self.use_redis = False
                    self._tasks[task_id] = task
            except Exception as e:
                logger.error(
                    "Failed to save task %s status to Redis: %s",
                    task_id, e,
                )
                self.use_redis = False
                self._tasks[task_id] = task
        else:
            self._tasks[task_id] = task

        logger.info("Task started: %s", task_id)
        return True

    def _acquire_lock_sync(self) -> bool:
        if not self._sync_r:
            return False
        try:
            result = self._sync_r.set(REDIS_KEY_LOCK, "1", ex=REDIS_LOCK_TTL, nx=True)
            return result is not None
        except Exception as e:
            logger.error("Failed to acquire Redis lock: %s", e)
            return False

    def complete_task(
        self,
        task_id: str,
        total_frames: int = 0,
        duration_s: float = 0.0,
    ) -> bool:
        task = self.get_task(task_id)
        if task is None or task["status"] != TaskStatus.PROCESSING:
            return False

        task["status"] = TaskStatus.COMPLETED
        task["completed_at"] = time.time()
        task["total_frames"] = total_frames
        task["duration_s"] = duration_s
        task["progress"] = 1.0

        if self._processing_task_id == task_id:
            self._processing_task_id = None
            if self.use_redis:
                try:
                    self._release_lock_sync()
                except Exception as e:
                    logger.error("Failed to release Redis lock: %s", e)

        if self.use_redis:
            try:
                self._save_task_sync(task)
            except Exception as e:
                logger.error("Failed to save task status to Redis: %s", e)
        else:
            self._tasks[task_id] = task

        logger.info(
            "Task completed: %s frames=%d duration=%.1fs",
            task_id, total_frames, duration_s,
        )

        # Clean up source file
        filename = task.get("filename", "")
        if filename:
            _delete_video_file(filename)

        # Clean up Redis hash entry (terminal state: no longer needed in hash)
        if self.use_redis:
            try:
                self._remove_task_from_redis_sync(task_id)
            except Exception as e:
                logger.error(
                    "Failed to remove completed task %s from Redis hash: %s",
                    task_id, e,
                )

        tasks_completed.inc()
        return True

    def _release_lock_sync(self) -> bool:
        if not self._sync_r:
            return False
        try:
            self._sync_r.delete(REDIS_KEY_LOCK)
            return True
        except Exception as e:
            logger.error("Failed to release Redis lock: %s", e)
            return False

    def fail_task(self, task_id: str, error: str = "") -> bool:
        task = self.get_task(task_id)
        if task is None or task["status"] != TaskStatus.PROCESSING:
            return False

        task["status"] = TaskStatus.FAILED
        task["completed_at"] = time.time()
        task["error"] = error

        if self._processing_task_id == task_id:
            self._processing_task_id = None
            if self.use_redis:
                try:
                    self._release_lock_sync()
                except Exception as e:
                    logger.error("Failed to release Redis lock: %s", e)

        if self.use_redis:
            try:
                self._save_task_sync(task)
            except Exception as e:
                logger.error("Failed to save task status to Redis: %s", e)
        else:
            self._tasks[task_id] = task

        logger.error("Task failed: %s error=%s", task_id, error)

        # Clean up source file
        filename = task.get("filename", "")
        if filename:
            _delete_video_file(filename)

        # Clean up Redis hash entry (terminal state: no longer needed in hash)
        if self.use_redis:
            try:
                self._remove_task_from_redis_sync(task_id)
            except Exception as e:
                logger.error(
                    "Failed to remove failed task %s from Redis hash: %s",
                    task_id, e,
                )

        tasks_failed.inc()
        return True

    def cancel_task(self, task_id: str) -> bool:
        task = self.get_task(task_id)
        if task is None or task["status"] != TaskStatus.PROCESSING:
            return False

        task["status"] = TaskStatus.CANCELLED
        task["completed_at"] = time.time()

        if self._processing_task_id == task_id:
            self._processing_task_id = None
            if self.use_redis:
                try:
                    self._release_lock_sync()
                except Exception as e:
                    logger.error("Failed to release Redis lock: %s", e)

        if self.use_redis:
            try:
                self._save_task_sync(task)
            except Exception as e:
                logger.error("Failed to save task status to Redis: %s", e)
        else:
            self._tasks[task_id] = task

        logger.info("Task cancelled: %s", task_id)

        # Clean up source file (terminal state, consistent with complete_task/fail_task)
        filename = task.get("filename", "")
        if filename:
            _delete_video_file(filename)

        # Archive Redis hash entry (terminal state)
        if self.use_redis:
            try:
                self._remove_task_from_redis_sync(task_id)
            except Exception as e:
                logger.error(
                    "Failed to archive cancelled task %s from Redis hash: %s",
                    task_id, e,
                )

        return True

    def update_progress(
        self,
        task_id: str,
        progress: float,
        processed_frames: int = 0,
        total_frames: int = 0,
    ) -> bool:
        task = self.get_task(task_id)
        if task is None:
            return False

        task["progress"] = progress
        task["processed_frames"] = processed_frames
        if total_frames > 0:
            task["total_frames"] = total_frames

        # Phase1: sync processed_frames with total_frames if not explicitly set
        if task.get("total_frames", 0) > 0 and task.get("processed_frames", 0) == 0:
            _p = task.get("progress", 0)
            if _p >= 1.0:
                task["processed_frames"] = task["total_frames"]
            else:
                task["processed_frames"] = int(task["total_frames"] * _p)

        if self.use_redis:
            try:
                self._save_task_sync(task)
            except Exception as e:
                logger.error("Failed to save task progress to Redis: %s", e)
        else:
            self._tasks[task_id] = task

        return True

    def check_timeouts(self) -> List[str]:
        now = time.time()
        timed_out = []

        if self.use_redis:
            try:
                tasks = self._load_all_tasks_sync()
                for task in tasks:
                    if task["status"] != TaskStatus.PROCESSING:
                        continue
                    started = task.get("started_at")
                    if started is None:
                        continue
                    elapsed = now - started
                    if elapsed > self._task_timeout_s:
                        self.fail_task(
                            task["task_id"],
                            error=f"Processing timed out after {elapsed:.0f}s "
                                  f"(limit: {self._task_timeout_s}s)",
                        )
                        timed_out.append(task["task_id"])
            except Exception as e:
                logger.error("Failed to check timeouts from Redis: %s", e)
                for task_id, task in self._tasks.items():
                    if task["status"] != TaskStatus.PROCESSING:
                        continue
                    started = task.get("started_at")
                    if started is None:
                        continue
                    elapsed = now - started
                    if elapsed > self._task_timeout_s:
                        self.fail_task(
                            task_id,
                            error=f"Processing timed out after {elapsed:.0f}s "
                                  f"(limit: {self._task_timeout_s}s)",
                        )
                        timed_out.append(task_id)
        else:
            for task_id, task in self._tasks.items():
                if task["status"] != TaskStatus.PROCESSING:
                    continue
                started = task.get("started_at")
                if started is None:
                    continue
                elapsed = now - started
                if elapsed > self._task_timeout_s:
                    self.fail_task(
                        task_id,
                        error=f"Processing timed out after {elapsed:.0f}s "
                              f"(limit: {self._task_timeout_s}s)",
                    )
                    timed_out.append(task_id)

        # 兜底：清理超 1h 的已完成任务
        self.cleanup_stale_completed_tasks(max_age_hours=1)

        return timed_out

    @property
    def current_processing_task(self) -> Optional[str]:
        if self._processing_task_id:
            task = self.get_task(self._processing_task_id)
            if task and task["status"] == TaskStatus.PROCESSING:
                return self._processing_task_id
        if self.use_redis:
            try:
                tasks = self._load_all_tasks_sync()
                for task in tasks:
                    if task["status"] == TaskStatus.PROCESSING:
                        return task["task_id"]
            except Exception as e:
                logger.error("Failed to check current processing task from Redis: %s", e)
        return None

    def reset(self) -> None:
        if self.use_redis:
            try:
                self._clear_redis_sync()
            except Exception as e:
                logger.error("Failed to reset Redis data: %s", e)
        self._tasks.clear()
        self._processing_task_id = None

    def _remove_task_from_redis_sync(self, task_id: str) -> bool:
        """Archive terminal-state task: write archive key with TTL=3600s, then HDEL from active hash.

        This keeps the active hash bounded while allowing get_task() to
        return completed/failed/cancelled tasks for 1 hour via the archive key.
        """
        if not self._sync_r:
            logger.warning("Cannot archive task %s: sync Redis not available", task_id)
            return False
        try:
            # 1. Read current data from active hash
            raw = self._sync_r.hget(REDIS_KEY_TASKS, task_id)
            # 2. Write archive key with TTL=3600s for get_task() fallback
            if raw:
                self._sync_r.setex(f"{REDIS_KEY_TASKS}:archive:{task_id}", 3600, raw)
            # 3. HDEL from active hash to keep it bounded
            self._sync_r.hdel(REDIS_KEY_TASKS, task_id)
            logger.debug(
                "Archived task %s (TTL=3600s), removed from active hash %s",
                task_id, REDIS_KEY_TASKS,
            )
            tasks_archived.inc()
            return True
        except Exception as e:
            logger.error(
                "Failed to archive task %s from Redis hash: %s", task_id, e,
            )
            return False

    def cleanup_stale_completed_tasks(self, max_age_hours: int = 1) -> int:
        """
        定时兜底：扫描 hash 中 status=completed/failed 超过 max_age_hours 的任务，
        清理文件 + archive。
        返回清理的任务数。
        """
        if not self.use_redis or not self._sync_r:
            return 0

        cleaned = 0
        try:
            tasks = self._sync_r.hgetall(REDIS_KEY_TASKS)
            now = time.time()
            for task_id, raw in tasks.items():
                try:
                    task = json.loads(raw)
                    status = task.get("status", "")
                    if status not in (TaskStatus.COMPLETED, TaskStatus.FAILED, TaskStatus.CANCELLED):
                        continue
                    completed_at = task.get("completed_at", 0)
                    if not completed_at or (now - completed_at) < max_age_hours * 3600:
                        continue

                    # Clean up file
                    filename = task.get("filename", "")
                    if filename:
                        _delete_video_file(filename)

                    # Archive from hash
                    raw_json = json.dumps(task, ensure_ascii=False)
                    self._sync_r.setex(f"{REDIS_KEY_TASKS}:archive:{task_id}", 3600, raw_json)
                    self._sync_r.hdel(REDIS_KEY_TASKS, task_id)
                    cleaned += 1
                    logger.info("Cleanup: archived stale task %s (status=%s, age=%.1fh)", task_id, status, (now - completed_at) / 3600)
                except Exception as e:
                    logger.warning("Cleanup: failed to process task %s: %s", task_id, e)
        except Exception as e:
            logger.error("Cleanup: failed to scan tasks: %s", e)

        # Phase 2: data consistency check
        consistency = self.verify_data_consistency()
        if consistency["inconsistent"] > 0:
            logger.warning("Data consistency check: %d/%d tasks have issues", consistency["inconsistent"], consistency["checked"])
            for issue in consistency["issues"]:
                logger.warning("  Consistency issue: %s", issue)

            # Phase 2: auto-clean inconsistent tasks
            for issue in consistency["issues"]:
                task_id = issue.split(":")[0].strip()
                raw = self._sync_r.hget(REDIS_KEY_TASKS, task_id)
                if raw:
                    try:
                        task = json.loads(raw)
                        raw_json = json.dumps(task, ensure_ascii=False)
                        self._sync_r.setex(f"{REDIS_KEY_TASKS}:archive:{task_id}", 3600, raw_json)
                        self._sync_r.hdel(REDIS_KEY_TASKS, task_id)
                        logger.info("Auto-archived inconsistent task %s", task_id)
                    except Exception:
                        pass

        return cleaned

    def verify_data_consistency(self) -> dict:
        """
        Phase 2: 校验 Redis hash vs 数据库数据一致性。
        返回 { "checked": N, "inconsistent": N, "issues": [...] }
        """
        result = {"checked": 0, "inconsistent": 0, "issues": []}
        if not self.use_redis or not self._sync_r:
            return result

        try:
            tasks = self._sync_r.hgetall(REDIS_KEY_TASKS)
            for task_id, raw in tasks.items():
                result["checked"] += 1
                try:
                    task = json.loads(raw)
                    status = task.get("status", "")
                    # 如果 status 为 terminal 但 progress<1.0 -> 不一致
                    if status in ("completed", "failed", "cancelled") and task.get("progress", 0) < 1.0:
                        result["inconsistent"] += 1
                        result["issues"].append(f"{task_id}: status={status} but progress={task.get('progress')}")
                    # 如果 status 为 terminal 但没有 completed_at -> 不一致
                    if status in ("completed", "failed", "cancelled") and not task.get("completed_at"):
                        result["inconsistent"] += 1
                        result["issues"].append(f"{task_id}: status={status} but no completed_at")
                except Exception as e:
                    result["inconsistent"] += 1
                    result["issues"].append(f"{task_id}: parse error - {e}")
        except Exception as e:
            result["issues"].append(f"scan error: {e}")

        return result

    def _clear_redis_sync(self) -> bool:
        if not self._sync_r:
            return False
        try:
            self._sync_r.delete(REDIS_KEY_TASKS)
            self._sync_r.delete(REDIS_KEY_LOCK)
            # Also clean up archive keys (TTL 3600 tasks)
            try:
                cursor = 0
                while True:
                    cursor, keys = self._sync_r.scan(cursor, match=f"{REDIS_KEY_TASKS}:archive:*", count=100)
                    if keys:
                        self._sync_r.delete(*keys)
                    if cursor == 0:
                        break
            except Exception as e:
                logger.error("Failed to clean up archive keys: %s", e)
            return True
        except Exception as e:
            logger.error("Failed to clear Redis data: %s", e)
            return False


_managers: Dict[bool, VideoTaskManager] = {}


def get_task_manager(
    use_redis: bool = False,
    redis_client: Optional[RedisClient] = None,
) -> VideoTaskManager:
    """Get the VideoTaskManager instance for the specified mode.

    When redis_client is provided, it is reused instead of creating
    a new connection. This is critical when called from FastAPI routes
    that already have a running event loop.
    """
    if use_redis not in _managers:
        _managers[use_redis] = VideoTaskManager(
            use_redis=use_redis,
            redis_client=redis_client,
        )
    elif redis_client is not None and _managers[use_redis]._sync_r is None:
        _managers[use_redis]._sync_r = redis_client
        _managers[use_redis].use_redis = True
    return _managers[use_redis]


def reset_task_manager() -> None:
    for mgr in _managers.values():
        mgr.reset()
    _managers.clear()


# ── Celery Periodic Task: Stale Video Cleanup ───────────────────────

@celery.task(name="cleanup_stale_videos")
def cleanup_stale_videos():
    """Delete video files in data/videos/ that are >7 days old and not
    referenced by any task in the Redis mes:video:tasks hash.

    Scheduled: daily at 3:00 AM via Celery Beat.
    """
    import redis as sync_redis

    upload_dir = Path(VIDEO_UPLOAD_DIR).resolve()
    if not upload_dir.is_dir():
        logger.info("Upload directory %s does not exist, skipping cleanup", upload_dir)
        return

    # Collect all referenced filenames from Redis task hash
    broker_url = os.getenv("CELERY_BROKER_URL", "redis://redis:6379/0")
    referenced: set[str] = set()
    try:
        r = sync_redis.Redis.from_url(broker_url, decode_responses=True, socket_timeout=5)
        tasks_data = r.hgetall(REDIS_KEY_TASKS)
        if tasks_data:
            for _, value in tasks_data.items():
                try:
                    task = json.loads(value)
                    filename = task.get("filename", "")
                    if filename:
                        referenced.add(filename)
                except (json.JSONDecodeError, TypeError):
                    continue
        r.close()
    except Exception as e:
        logger.error("Failed to query Redis for stale video cleanup: %s", e)
        return

    # Scan upload directory
    cutoff = datetime.now(timezone.utc) - timedelta(days=7)
    deleted_count = 0
    kept_count = 0

    for entry in upload_dir.iterdir():
        if not entry.is_file():
            continue
        if entry.suffix in (".upload", ".tmp"):
            # Skip temporary / in-progress upload files
            continue

        mtime = datetime.fromtimestamp(entry.stat().st_mtime, tz=timezone.utc)
        if mtime > cutoff:
            # File is newer than 7 days, keep it
            kept_count += 1
            continue

        if entry.name in referenced:
            # File is still referenced by a task, keep it
            kept_count += 1
            continue

        # Old and unreferenced: delete
        try:
            os.remove(str(entry))
            deleted_count += 1
            logger.info("Cleanup deleted stale video: %s (age=%.0fd)", entry.name, (datetime.now(timezone.utc) - mtime).total_seconds() / 86400)
        except OSError as e:
            logger.error("Failed to delete stale video %s: %s", entry.name, e)

    logger.info(
        "Cleanup complete: deleted=%d kept=%d dir=%s",
        deleted_count, kept_count, upload_dir,
    )


@celery.task(name="cleanup_stale_completed_tasks")
def run_cleanup_stale_completed_tasks():
    """Celery beat task: scan and archive stale completed/failed/cancelled tasks."""
    try:
        manager = get_task_manager(use_redis=True)
        if manager:
            count = manager.cleanup_stale_completed_tasks(max_age_hours=1)
            if count:
                logger.info("Beat cleanup: archived %d stale tasks", count)
    except Exception as e:
        logger.error("Beat cleanup failed: %s", e)
