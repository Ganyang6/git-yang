"""Redis command listener for perception container.

Subscribes to ``channel:video_commands`` and spawns ``main.py`` as a
subprocess for each video-processing task.

This is the receiving end of the T9-02 pipeline trigger bridge::

    api container  --publish-->  Redis channel:video_commands  --subscribe-->  perception container
"""

from __future__ import annotations

import json
import logging
import os
import signal
import subprocess
import sys
import threading
import time
from pathlib import Path

import redis

# ── Logging ────────────────────────────────────────────────────────────

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    datefmt="%H:%M:%S",
    stream=sys.stdout,
    force=True,
)
sys.stdout.reconfigure(line_buffering=True)
sys.stderr.reconfigure(line_buffering=True)
logger = logging.getLogger("perception.listener")

# ── Constants ──────────────────────────────────────────────────────────

CHANNEL_VIDEO_COMMANDS = "channel:video_commands"
REDIS_KEY_TASKS = "mes:video:tasks"
VIDEO_DIR = "/app/data/videos"
DEFAULT_PIPELINE_TIMEOUT_S = 1800  # 30 minutes

# ── Graceful shutdown ─────────────────────────────────────────────────

_shutdown_event = threading.Event()


def _signal_handler(signum: int, _frame):
    logger.info("Received signal %d, shutting down listener", signum)
    _shutdown_event.set()


def _install_signal_handlers():
    signal.signal(signal.SIGTERM, _signal_handler)
    signal.signal(signal.SIGINT, _signal_handler)


# ── Task status update ────────────────────────────────────────────────
# Uses a FRESH Redis connection (not the PubSub one) because a connection
# in subscriber mode cannot execute regular commands like HGET/HSET.


def _update_task_status(
    redis_url: str, task_id: str, status: str
) -> None:
    """Update task status via a dedicated Redis connection.

    Opens a fresh connection, updates the hash, then closes it.
    This avoids the 'connection in subscriber mode' restriction
    that prevents HGET/HSET on the PubSub connection.
    """
    conn = None
    try:
        conn = redis.Redis.from_url(
            redis_url,
            decode_responses=True,
            socket_connect_timeout=5,
            socket_timeout=5,
        )
        conn.ping()
        raw = conn.hget(REDIS_KEY_TASKS, task_id)
        if raw is None:
            logger.warning(
                "Task %s not found in Redis hash (will retry), skipping",
                task_id,
            )
            return
        task = json.loads(raw)
        task["status"] = status
        task["completed_at"] = time.time()
        if status == "failed":
            task["progress"] = 0.0
        conn.hset(REDIS_KEY_TASKS, task_id, json.dumps(task))
        logger.info(
            "Task hash updated: %s status=%s",
            task_id, status,
        )
    except Exception as exc:
        logger.warning(
            "Failed to update task status for %s: %s",
            task_id, exc,
        )
    finally:
        if conn is not None:
            try:
                conn.close()
            except Exception:
                pass


FLUSH_CHANNEL = "channel:flush_segments"


def _flush_aggregation(
    redis_url: str, task_id: str, station_id: str
) -> None:
    """Publish a flush_segments message after video pipeline completes.

    Opens a fresh Redis connection, publishes to the flush_segments
    channel, then closes it.  The API container's stream_consumer
    subscribes to this channel and calls aggregate_segments().
    """
    conn = None
    try:
        conn = redis.Redis.from_url(
            redis_url,
            decode_responses=True,
            socket_connect_timeout=5,
            socket_timeout=5,
        )
        payload = json.dumps({
            "task_id": task_id,
            "station_id": station_id,
        })
        conn.publish(FLUSH_CHANNEL, payload)
        logger.info(
            "Flush aggregation published: task=%s station=%s",
            task_id, station_id,
        )
    except Exception as exc:
        logger.warning(
            "Failed to publish flush aggregation: %s (task=%s)",
            exc, task_id,
        )
    finally:
        if conn is not None:
            try:
                conn.close()
            except Exception:
                pass


# ── Main loop ──────────────────────────────────────────────────────────


def main():
    _install_signal_handlers()

    redis_url = os.environ.get("REDIS_URL", "redis://redis:6379/0")
    timeout_s = int(
        os.environ.get("PIPELINE_TIMEOUT_S", str(DEFAULT_PIPELINE_TIMEOUT_S))
    )

    logger.info("=" * 50)
    logger.info("Perception command listener starting")
    logger.info("Redis URL:  %s", redis_url)
    logger.info("Channel:    %s", CHANNEL_VIDEO_COMMANDS)
    logger.info("Video dir:  %s", VIDEO_DIR)
    logger.info("Timeout:    %ds", timeout_s)
    logger.info("=" * 50)

    r = redis.Redis.from_url(
        redis_url,
        decode_responses=True,
        socket_connect_timeout=5,
        health_check_interval=30,
    )

    # Verify connection
    try:
        r.ping()
        logger.info("Redis connected")
    except redis.ConnectionError as exc:
        logger.error("Redis connection failed: %s", exc)
        sys.exit(1)

    pubsub = r.pubsub()
    pubsub.subscribe(CHANNEL_VIDEO_COMMANDS)
    logger.info("Subscribed to %s, waiting for commands...", CHANNEL_VIDEO_COMMANDS)

    # Drain initial subscribe confirmation message
    for _ in range(1):
        msg = pubsub.get_message(timeout=2.0)
        if msg is None:
            break

    try:
        while not _shutdown_event.is_set():
            # Block up to 1s so we can check shutdown_event periodically
            message = pubsub.get_message(timeout=1.0)
            if message is None or message["type"] != "message":
                continue

            data_str = message["data"]
            logger.info("Received command: %s", data_str)

            # Parse command
            try:
                data = json.loads(data_str)
                task_id = data["task_id"]
                filename = data["filename"]
                station_id = data.get("station_id", "WS-01")
            except (json.JSONDecodeError, KeyError) as exc:
                logger.error("Invalid command format: %s", exc)
                continue

            video_path = os.path.join(VIDEO_DIR, filename)

            # Path traversal guard: ensure resolved path stays within VIDEO_DIR
            resolved = Path(video_path).resolve()
            video_root = Path(VIDEO_DIR).resolve()
            if not resolved.is_relative_to(video_root):
                logger.error("Path traversal attempt: %s", video_path)
                continue

            if not os.path.isfile(video_path):
                logger.error("Video file not found: %s", video_path)
                continue

            logger.info(
                "Starting pipeline: task=%s file=%s station=%s",
                task_id, filename, station_id,
            )

            # Spawn process_video.py as subprocess
            cmd = [
                sys.executable, "process_video.py",
                "--video", video_path,
                "--station-id", station_id,
                "--task-id", task_id,
            ]

            try:
                result = subprocess.run(
                    cmd,
                    timeout=timeout_s,
                    # Inherit stdout/stderr so pipeline logs go to docker logs
                )
                if result.returncode == 0:
                    logger.info("Pipeline completed: task=%s", task_id)
                    _update_task_status(redis_url, task_id, "completed")
                    _flush_aggregation(redis_url, task_id, station_id)
                else:
                    logger.error(
                        "Pipeline exited with code %d: task=%s",
                        result.returncode, task_id,
                    )
                    _update_task_status(redis_url, task_id, "failed")
            except subprocess.TimeoutExpired:
                logger.error(
                    "Pipeline timed out after %ds: task=%s", timeout_s, task_id,
                )
                _update_task_status(redis_url, task_id, "failed")
            except Exception as exc:
                logger.error(
                    "Pipeline subprocess error: task=%s error=%s", task_id, exc,
                )
                _update_task_status(redis_url, task_id, "failed")

            logger.info("Ready for next command")

    except KeyboardInterrupt:
        pass
    finally:
        try:
            pubsub.unsubscribe()
            pubsub.close()
        except Exception:
            pass
        r.close()
        logger.info("Command listener stopped")


if __name__ == "__main__":
    main()
