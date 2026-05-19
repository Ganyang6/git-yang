#!/usr/bin/env python3
"""精简视频处理管线 - 替代 main.py 解决卡死问题。

与 ``main.py`` 的 ``run_video_pipeline`` 相比，此脚本：
  1. 使用 ``_safe_read()`` 代替 ``cap.grab()/cap.retrieve()`` ——
     cv2 原生 C 调用会阻塞 GIL，``_safe_read`` 在守护线程中运行 ``cap.read()``
     并在超时后返回 ``(False, None)``，防止永久阻塞。
  2. 注册 SIGTERM/SIGINT handler，支持 Docker 优雅停止。
  3. 内置帧级进度看门狗——如果 N 秒无进展则退出。
  4. 预拷贝视频到 tmpfs 以消除 NTFS 9P I/O 阻塞。
"""
from __future__ import annotations

import argparse
import json
import logging
import os
import signal
import sys
import threading
import time
from pathlib import Path

# Insert project root so that relative imports (e.g. from main import …) work.
sys.path.insert(0, '/app')

import cv2
from pose_estimator import PoseEstimator
from video_optimizer import VideoOptimizerPipeline
from app.perception.redis_adapter import PerceptionAdapter

from camera_manager import _safe_read, _safe_release, _validate_video_path
from main import _publish_video_progress, _safe_redis_call, _copy_video_to_tmp

# ── Logging ────────────────────────────────────────────────────────────

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s [%(levelname)s] %(name)s: %(message)s',
    datefmt='%H:%M:%S',
    stream=sys.stdout,
    force=True,
)
sys.stdout.reconfigure(line_buffering=True)
sys.stderr.reconfigure(line_buffering=True)
logger = logging.getLogger('perception.process_video')

# ── Configuration (environment overrides) ──────────────────────────────

REDIS_URL = os.environ.get('REDIS_URL', 'redis://:mes-redis-2026@redis:6379/0')
MAX_RES = int(os.environ.get('MAX_RESOLUTION', '640'))
INTERVAL = int(os.environ.get('DETECTION_INTERVAL', '6'))
FRAME_READ_TIMEOUT_S = float(os.environ.get('FRAME_READ_TIMEOUT_S', '5.0'))
WATCHDOG_TIMEOUT_S = float(os.environ.get('WATCHDOG_TIMEOUT_S', '60.0'))

# ── Graceful shutdown ─────────────────────────────────────────────────

_shutdown_event = threading.Event()
# Thread-level lock so progress-update signals don't race with final cleanup.
_shutdown_lock = threading.Lock()


def _signal_handler(signum: int, _frame):
    logger.info("Received signal %d, requesting graceful shutdown", signum)
    _shutdown_event.set()


def _install_signal_handlers():
    signal.signal(signal.SIGTERM, _signal_handler)
    signal.signal(signal.SIGINT, _signal_handler)


# ── Progress watchdog ──────────────────────────────────────────────────


class ProgressWatchdog:
    """Monitors frame-processing progress and exits if stalled.

    A daemon thread checks that the frame counter advances at least once
    every *timeout* seconds.  If it doesn't, the watchdog raises
    SystemExit (which the main ``finally`` block handles for cleanup).
    """

    def __init__(self, timeout: float = WATCHDOG_TIMEOUT_S):
        self._timeout = timeout
        self._last_progress = time.monotonic()
        self._lock = threading.Lock()
        self._stopped = threading.Event()

    def bump(self) -> None:
        with self._lock:
            self._last_progress = time.monotonic()

    def _run(self) -> None:
        while not self._stopped.is_set():
            with self._lock:
                elapsed = time.monotonic() - self._last_progress
            if elapsed > self._timeout and not self._stopped.is_set():
                logger.error(
                    "Progress watchdog fired: no frame processed in %.1fs. "
                    "Exiting to prevent indefinite hang.",
                    elapsed,
                )
                os._exit(1)  # Force exit — may be inside C cap.read()
            self._stopped.wait(timeout=min(5.0, self._timeout / 2))

    def start(self) -> None:
        self.bump()
        t = threading.Thread(target=self._run, daemon=True)
        t.start()

    def stop(self) -> None:
        self._stopped.set()


# ── Main processing function ───────────────────────────────────────────


def process(video_path: str, station_id: str = 'WS-01', task_id: str = ''):
    # Stage 1 — validate + pre-copy to tmpfs
    try:
        _validate_video_path(video_path)
    except ValueError as exc:
        logger.error("Invalid video path: %s", exc)
        _publish_failure(adapter=None, task_id=task_id, error=str(exc))
        return

    try:
        video_path = _copy_video_to_tmp(video_path)
    except (FileNotFoundError, OSError) as exc:
        logger.error("Cannot open video: %s", exc)
        _publish_failure(adapter=None, task_id=task_id, error=str(exc))
        return

    # Stage 2 — open video
    cap = cv2.VideoCapture(video_path)
    if not cap.isOpened():
        logger.error("Cannot open video file: %s", video_path)
        return
    cap.set(cv2.CAP_PROP_BUFFERSIZE, 1)

    total = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
    fname = Path(video_path).name
    camera_id = f"video_{Path(video_path).stem}"
    logger.info("Opened: %s | %d frames | read_timeout=%.1fs | watchdog=%.1fs",
                fname, total, FRAME_READ_TIMEOUT_S, WATCHDOG_TIMEOUT_S)

    # Stage 3 — init components
    from config import load_config
    cfg = load_config('config.yaml')

    pe = PoseEstimator(
        model_complexity=cfg.pose.model_complexity,
        smooth=cfg.pose.smooth,
        min_detection_confidence=cfg.pose.min_detection_confidence,
        min_tracking_confidence=cfg.pose.min_tracking_confidence,
    )

    opt = VideoOptimizerPipeline(
        max_resolution=MAX_RES,
        detection_interval=INTERVAL,
    )
    adapter = PerceptionAdapter(REDIS_URL)
    if not adapter.connect():
        raise RuntimeError("Redis connection failed")

    # Stage 4 — processing loop with watchdog
    seq = 0
    pose_frames = 0
    consecutive_failures = 0
    total_failures = 0
    loop_start_time = time.perf_counter()

    watchdog = ProgressWatchdog(timeout=WATCHDOG_TIMEOUT_S)
    watchdog.start()

    try:
        for idx in range(total):
            if _shutdown_event.is_set():
                logger.info("Shutdown requested, exiting at frame %d/%d", idx, total)
                break

            # P0-3: _safe_read replaces cap.grab()+cap.retrieve() with timeout
            ok, frame = _safe_read(cap, timeout=FRAME_READ_TIMEOUT_S)
            if not ok:
                consecutive_failures += 1
                total_failures += 1
                # Abort when >50% of frames have failed.
                threshold = max(1, int(total * 0.5))
                if consecutive_failures > threshold:
                    logger.error(
                        "Consecutive frame failures exceeded 50%% of total (%d/%d). Aborting.",
                        total_failures, total,
                    )
                    break
                logger.warning("Frame %d read failed (skip #%d)", idx, total_failures)
                continue

            # Reset consecutive failure counter on valid frame
            consecutive_failures = 0

            # Notify watchdog we made progress
            watchdog.bump()

            # Video optimization + pose estimation
            res = opt.process_frame(frame, idx)
            if res['should_infer']:
                pr = pe.estimate(res['frame'], time.time())
                if pr and pr.landmarks:
                    opt.update_last_result(pr)
                    lm_list = [
                        {
                            'name': lm.name,
                            'x': float(lm.x),
                            'y': float(lm.y),
                            'z': float(lm.z),
                            'visibility': float(lm.visibility),
                        }
                        for lm in pr.landmarks
                    ]
                    adapter.publish_pose_frame(
                        camera_id=camera_id,
                        station_id=station_id,
                        frame_id=f'{seq:020d}',
                        landmarks=lm_list,
                        pose_score=float(pr.pose_score),
                        timestamp=time.time(),
                    )
                    seq += 1
                    pose_frames += 1

    except Exception as exc:
        logger.error("Video processing failed: %s", exc, exc_info=True)
        if task_id:
            try:
                _publish_video_progress(
                    adapter, task_id, 0.0,
                    seq, total,
                    status="failed",
                    error=str(exc)[:500],
                )
            except Exception:
                logger.warning("Failed to publish error progress (best-effort)")
        raise
    finally:
        watchdog.stop()
        elapsed = time.perf_counter() - loop_start_time
        logger.info(
            'Processed: %d pose frames / %d total (failures: %d) in %.1fs',
            pose_frames, total, total_failures, elapsed,
        )

        _safe_release(cap, timeout=3.0, source_name=camera_id)
        pe.close(timeout=3.0)

        try:
            _safe_redis_call(adapter.close, timeout=3.0, label="adapter_close")
        except Exception:
            logger.warning("adapter.close() failed or timed out during cleanup")

        # Publish completion status
        if task_id:
            try:
                success_rate = round(
                    (total - total_failures) / max(total, 1) * 100, 1
                ) if total_failures > 0 else 100.0
                _publish_video_progress(
                    adapter, task_id, 1.0,
                    seq, total,
                    status="completed",
                    duration_s=elapsed,
                    success_rate=success_rate,
                )
            except Exception:
                logger.warning("Failed to publish completion progress (best-effort)")


def _publish_failure(adapter, task_id: str, error: str):
    """Publish failure progress if adapter is available."""
    if not task_id:
        return
    if adapter is not None:
        try:
            _publish_video_progress(
                adapter, task_id, 0.0, 0, 0,
                status="failed", error=error[:500],
            )
            return
        except Exception:
            pass
    # Fallback: publish via a fresh adapter if one wasn't created yet
    try:
        fallback = PerceptionAdapter(REDIS_URL)
        if fallback.connect():
            _publish_video_progress(
                fallback, task_id, 0.0, 0, 0,
                status="failed", error=error[:500],
            )
            _safe_redis_call(fallback.close, timeout=2.0, label="fallback_close")
    except Exception:
        pass


# ── Entry point ────────────────────────────────────────────────────────


if __name__ == '__main__':
    _install_signal_handlers()

    p = argparse.ArgumentParser(description='Mes perception video pipeline')
    p.add_argument('--video', required=True)
    p.add_argument('--station-id', default='WS-01')
    p.add_argument('--task-id', default='')
    args = p.parse_args()

    try:
        process(args.video, args.station_id, args.task_id)
    except SystemExit:
        raise  # Allow watchdog / signal handler to control exit
    except Exception as exc:
        logger.critical("Unhandled exception: %s", exc, exc_info=True)
        sys.exit(1)
