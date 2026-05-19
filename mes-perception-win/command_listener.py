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
VIDEO_DIR = os.environ.get("MES_VIDEO_DIR", "/app/data/videos")
DEFAULT_PIPELINE_TIMEOUT_S = 1800  # 30 minutes
CONFIG_PATH = os.environ.get("MES_CONFIG_PATH", "/app/config/config.yaml")

# ── Graceful shutdown ─────────────────────────────────────────────────

_shutdown_event = threading.Event()


def _signal_handler(signum: int, _frame):
    logger.info("Received signal %d, shutting down listener", signum)
    _shutdown_event.set()


def _install_signal_handlers():
    signal.signal(signal.SIGTERM, _signal_handler)
    signal.signal(signal.SIGINT, _signal_handler)


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

            # Spawn main.py as subprocess
            cmd = [
                sys.executable, "main.py",
                "--no-display",
                "--config", CONFIG_PATH,
                "--video", video_path,
                "--station-id", station_id,
                "--redis-url", redis_url,
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
                else:
                    logger.error(
                        "Pipeline exited with code %d: task=%s",
                        result.returncode, task_id,
                    )
            except subprocess.TimeoutExpired:
                logger.error("Pipeline timed out after %ds: task=%s", timeout_s, task_id)
            except Exception as exc:
                logger.error("Pipeline subprocess error: task=%s error=%s", task_id, exc)

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
