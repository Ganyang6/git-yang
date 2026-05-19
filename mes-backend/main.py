"""
感知底座主程序
整合摄像头采集、帧缓冲、姿态识别
验收标准：
  - 单摄像头稳定跑 30 FPS
  - 33 个关键点坐标实时输出到内存队列
  - 端到端延迟 < 33ms
"""

import json
try:
    import cv2  # type: ignore
except Exception:
    cv2 = None
import os
import sys
import time
import shutil
import logging
import argparse
import signal
import threading
from pathlib import Path

# 配置日志
import sys
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s [%(levelname)s] %(name)s: %(message)s',
    datefmt='%H:%M:%S',
    stream=sys.stdout,
    force=True,
)
# Ensure unbuffered output in Docker environments
sys.stdout.reconfigure(line_buffering=True)
sys.stderr.reconfigure(line_buffering=True)
logger = logging.getLogger(__name__)


def _redact_redis_url(url: str) -> str:
    """Mask password in Redis URL for safe logging.

    redis://:password@host:port/db -> redis://:****@host:port/db
    Also handles redis://user:password@host and passwords with literal '@'.
    """
    import re as _re
    m = _re.match(r'^(rediss?://)(.*@)([^@]+)$', url)
    if m:
        scheme, credentials_with_at, host_part = m.groups()
        inner = credentials_with_at[:-1]  # strip trailing '@'
        colon_pos = inner.rfind(':')
        if colon_pos >= 0:
            return f"{scheme}{inner[:colon_pos]}:****@{host_part}"
    return url


# ── Graceful shutdown support (Docker SIGTERM handling) ──────────────
# Python signal handlers are deferred until the next bytecode instruction.
# When the main thread is blocked inside a C extension (e.g. MediaPipe
# detect()), the signal cannot be processed.  We set a threading.Event
# and check it at the top of every main-loop iteration so the loop can
# break out as soon as control returns to Python code.
_shutdown_event: threading.Event = threading.Event()


def _safe_redis_call(fn, timeout: float = 3.0, label: str = "redis"):
    """Run a Redis operation with timeout protection.

    Redis-py XADD/close can block indefinitely if the connection is in
    a bad state (e.g. after a signal interrupts the socket).  This
    wrapper runs *fn* in a daemon thread and gives up after *timeout*
    seconds.
    """
    result = [None]
    error = [None]

    def _run():
        try:
            result[0] = fn()
        except Exception as exc:
            error[0] = exc

    t = threading.Thread(target=_run, daemon=True)
    t.start()
    t.join(timeout=timeout)
    if t.is_alive():
        logger.warning("%s did not complete within %.1fs (abandoning)", label, timeout)
    elif error[0] is not None:
        raise error[0]
    return result[0]


# Temp directory for video pre-copy (avoids NTFS 9P I/O blocking).
# Files in /tmp/ live on tmpfs (or ext4 inside Docker), immune to
# the WSL2<->Windows NTFS bridge stalls that block native C read() calls
# even when GIL is held.
TMP_VIDEO_DIR = os.environ.get(
    "MES_TMP_VIDEO_DIR",
    "/tmp/mes-videos" if os.name != "nt" else os.path.join(
        os.environ.get("TEMP", os.environ.get("TMP", "C:\\temp")),
        "mes-videos"
    )
)


def _copy_video_to_tmp(video_path: str) -> str:
    """Copy a video file to a local temp directory before opening.

    In Docker + WSL2, videos are bind-mounted from the Windows NTFS host
    via the 9P protocol.  cv2.VideoCapture.read() is a native C call that
    does NOT release the GIL while doing blocking I/O, so threading-based
    timeouts cannot interrupt it.  By copying the file to /tmp/ (tmpfs or
    container ext4) first, all subsequent reads happen on a local filesystem
    and the GIL-block problem is eliminated at the root.

    If the video is already under TMP_VIDEO_DIR, the same path is returned
    without copying (idempotent).

    Args:
        video_path: Absolute path to the source video file.

    Returns:
        Path to the local copy under TMP_VIDEO_DIR.

    Raises:
        FileNotFoundError: If *video_path* does not exist.
    """
    resolved = Path(video_path).resolve()
    if not resolved.is_file():
        raise FileNotFoundError(f"Video file does not exist: {video_path}")

    # Already a local copy — nothing to do.
    try:
        if resolved.is_relative_to(TMP_VIDEO_DIR):
            return str(resolved)
    except (ValueError, TypeError):
        pass

    # Ensure temp directory exists.
    os.makedirs(TMP_VIDEO_DIR, exist_ok=True)

    # Clean up previous temp copy for this file (match by stem).
    dest = Path(TMP_VIDEO_DIR) / resolved.name
    if dest.exists():
        dest.unlink()

    logger.info(
        "Pre-copying video to local filesystem: %s -> %s "
        "(avoids NTFS 9P I/O blocking in Docker/WSL2)",
        resolved, dest,
    )
    shutil.copy2(str(resolved), str(dest))
    return str(dest)


# Re-export _safe_read from camera_manager so that existing
# ``from main import _safe_read`` references continue to work.
from camera_manager import _safe_read


# Redis hash key used by VideoTaskManager to persist task state
_REDIS_KEY_TASKS = "mes:video:tasks"


def _update_task_hash(adapter, task_id: str, status: str, total_frames: int,
                      duration_s: float, error: str, progress: float) -> None:
    """Update the VideoTaskManager Redis hash with a terminal status.

    This is the critical callback bridge: when the perception container
    finishes processing a video (or it fails), this function updates the
    ``mes:video:tasks`` hash so that subsequent GET /tasks/{id} calls
    return the correct terminal status.

    Without this, the task would stay in "processing" forever unless
    someone was connected to the SSE progress stream.

    Args:
        adapter: PerceptionAdapter instance (or anything with ``_client.client``).
        task_id: The video task UUID.
        status: "completed" or "failed".
        total_frames: Total processed frame count.
        duration_s: Processing duration in seconds.
        error: Error message (for "failed" status).
        progress: Progress value (1.0 for completed).
    """
    try:
        raw_client = getattr(adapter, "_client", None)
        if raw_client is None:
            logger.warning("Cannot update task hash: adapter has no _client")
            return
        r = getattr(raw_client, "client", None)
        if r is None:
            logger.warning("Cannot update task hash: RedisSyncClient.client is None")
            return

        # Read current task from hash
        raw_data = r.hget(_REDIS_KEY_TASKS, task_id)
        if raw_data is None:
            logger.warning("Task %s not found in Redis hash, cannot update status", task_id)
            return

        task = json.loads(raw_data)
        task["status"] = status
        task["completed_at"] = time.time()
        task["total_frames"] = total_frames
        task["duration_s"] = round(duration_s, 1)
        task["progress"] = progress
        if error:
            task["error"] = error

        r.hset(_REDIS_KEY_TASKS, task_id, json.dumps(task))
        logger.info(
            "Task hash updated: %s status=%s frames=%d duration=%.1fs",
            task_id, status, total_frames, duration_s,
        )
    except Exception as exc:
        logger.warning("Failed to update task hash for %s: %s", task_id, exc)


def _publish_video_progress(
    adapter,
    task_id: str,
    progress: float,
    processed_frames: int,
    total_frames: int,
    status: str = "processing",
    duration_s: float = 0.0,
    error: str = "",
    success_rate: float | None = None,
) -> None:
    """Publish video processing progress to Redis Pub/Sub and Stream.

    The SSE endpoint in the api container subscribes to this channel
    and forwards progress events to the frontend.

    For terminal statuses (completed/failed), this function also updates
    the VideoTaskManager Redis hash (``mes:video:tasks``) directly,
    ensuring the task status is persisted regardless of SSE connection.

    Uses best-effort publish with retry mechanism; failures are logged but not raised.
    """
    message = json.dumps({
        "task_id": task_id,
        "progress": progress,
        "processed_frames": processed_frames,
        "total_frames": total_frames,
        "status": status,
        "duration_s": round(duration_s, 1),
        "error": error,
        "timestamp": time.time(),
        "success_rate": success_rate,
    })

    # Try to publish to Pub/Sub with retry
    max_retries = 3
    retry_delay = 0.5
    
    for attempt in range(max_retries):
        try:
            _safe_redis_call(
                lambda: (adapter._client.publish(
                    f"channel:video_progress:{task_id}", message,
                )),
                timeout=2.0,
                label="progress-publish",
            )
            # Also store in Redis Stream for persistence
            _safe_redis_call(
                lambda: adapter._client.xadd(
                    "mes:video_progress",
                    {
                        "task_id": task_id,
                        "progress": str(progress),
                        "status": status,
                        "processed_frames": str(processed_frames),
                        "total_frames": str(total_frames),
                        "duration_s": str(round(duration_s, 1)),
                        "error": error,
                        "timestamp": str(time.time()),
                    },
                    maxlen=1000,
                    approximate=True,
                ),
                timeout=2.0,
                label="progress-stream",
            )
            break
        except Exception as exc:
            if attempt < max_retries - 1:
                logger.warning(f"Failed to publish video progress (attempt {attempt+1}/{max_retries}): %s, retrying...", exc)
                time.sleep(retry_delay)
                retry_delay *= 2
            else:
                logger.warning(f"Failed to publish video progress after {max_retries} attempts: %s", exc)

    # ── Terminal status: update VideoTaskManager Redis hash directly ─────
    # This ensures the task status is persisted even when no SSE client
    # is connected to receive the Pub/Sub progress event.
    if status in ("completed", "failed"):
        _update_task_hash(
            adapter, task_id, status,
            total_frames, duration_s, error, progress,
        )


def _setup_signal_handlers() -> None:
    """Register SIGTERM/SIGINT handlers for Docker graceful shutdown.

    Raises SystemExit to short-circuit any in-progress operations
    (including blocking Redis calls).  The ``finally`` blocks in
    ``run_video_pipeline`` and ``main`` handle resource cleanup with
    timeout protection, so a forced exit is safe.
    """
    def _handler(signum: int, frame) -> None:
        logger.info("Received signal %d, shutting down", signum)
        raise SystemExit(0)

    signal.signal(signal.SIGTERM, _handler)
    signal.signal(signal.SIGINT, _handler)


def _build_arg_parser():
    """Build and return the ArgumentParser (for reuse in tests)."""
    parser = argparse.ArgumentParser(
        description='边缘AI感知底座 - 视频采集与姿态识别'
    )
    parser.add_argument(
        '--config', '-c',
        type=str,
        default='config.yaml',
        help='配置文件路径'
    )
    parser.add_argument(
        '--camera-id', '-i',
        type=int,
        default=int(os.environ.get('CAMERA_ID', '0')),
        help='摄像头设备ID (env: CAMERA_ID, default: 0)'
    )
    parser.add_argument(
        '--no-display',
        action='store_true',
        help='禁用实时显示'
    )
    parser.add_argument(
        '--test-only',
        action='store_true',
        help='仅运行性能测试'
    )
    parser.add_argument(
        '--detect-cameras',
        action='store_true',
        help='Detect available cameras'
    )
    # --- Video playback mode parameters ---
    parser.add_argument(
        '--video', '-v',
        type=str,
        default=None,
        help='Video file path, enables video playback mode'
    )
    parser.add_argument(
        '--station-id',
        type=str,
        default=os.environ.get('STATION_ID', 'WS-01'),
        help='Station ID (env: STATION_ID, default: WS-01)'
    )
    parser.add_argument(
        '--loop',
        action='store_true',
        help='Loop video playback'
    )
    parser.add_argument(
        '--max-resolution',
        type=int,
        default=int(os.environ.get('MAX_RESOLUTION', '640')),
        help='Max frame width for downscaling (env: MAX_RESOLUTION, default: 640, 0=disable)'
    )
    parser.add_argument(
        '--redis-url',
        type=str,
        default=os.environ.get('REDIS_URL', 'redis://redis:6379/0'),
        help='Redis URL (env: REDIS_URL, default: redis://redis:6379/0)'
    )
    parser.add_argument(
        '--task-id',
        type=str,
        default=os.environ.get('TASK_ID', ''),
        help='Video processing task ID for progress tracking (env: TASK_ID)'
    )
    return parser


def parse_args(argv=None):
    """解析命令行参数"""
    return _build_arg_parser().parse_args(argv)


def detect_available_cameras(max_devices=10):
    """检测可用摄像头"""
    from camera_manager import CameraManager
    cameras = CameraManager.detect_available_cameras(max_devices)
    if cameras:
        logger.info(f"发现 {len(cameras)} 个可用摄像头: {cameras}")
    else:
        logger.warning("未检测到可用摄像头")
    return cameras


def run_realtime_pipeline(config_path='config.yaml',
                         camera_id=0,
                         show_display=True,
                         max_resolution=640):
    """
    运行实时处理流水线

    Args:
        config_path: 配置文件路径
        camera_id: 摄像头设备ID
        show_display: 是否显示实时画面
    """
    import cv2
    import numpy as np

    # 加载配置
    from config import load_config, CameraConfig, PoseConfig
    config = load_config(config_path)

    # 导入模块
    from camera_manager import CameraManager
    from pose_estimator import PoseEstimator, RealTimePoseProcessor
    from frame_buffer import FrameBuffer
    from video_optimizer import VideoOptimizerPipeline

    # 如果配置为空，添加默认摄像头
    if not config.cameras:
        config.cameras.append(CameraConfig(
            device_id=camera_id,
            name=f"Camera_{camera_id}",
            enabled=True,
            resolution_width=1280,
            resolution_height=720,
            fps=30
        ))

    # 创建组件
    camera_manager = CameraManager()
    pose_estimator = PoseEstimator(
        model_complexity=config.pose.model_complexity,
        smooth=config.pose.smooth,
        min_detection_confidence=config.pose.min_detection_confidence,
        min_tracking_confidence=config.pose.min_tracking_confidence
    )
    frame_buffer = FrameBuffer(
        max_size=config.buffer.max_queue_size,
        drop_old=config.buffer.drop_old_frames
    )

    # 初始化视频优化流水线 (4K CPU 性能)
    actual_resolution = max_resolution if max_resolution > 0 else 0
    optimizer = VideoOptimizerPipeline(
        max_resolution=actual_resolution,
        detection_interval=6,
        enable_clahe=True,
        clahe_clip_limit=2.0
    )
    logger.info("VideoOptimizer initialized: resolution=%d, interval=%d, CLAHE=True",
                actual_resolution, 6)

    logger.info("=" * 50)
    logger.info("感知底座启动")
    logger.info(f"摄像头: {config.cameras[0].name}")
    logger.info(f"分辨率: {config.cameras[0].resolution_width}x{config.cameras[0].resolution_height}")
    logger.info(f"目标帧率: {config.cameras[0].fps} FPS")
    logger.info(f"关键点数量: {config.performance.num_landmarks}")
    logger.info("=" * 50)

    # 打开摄像头
    camera = camera_manager.add_camera(
        device_id=config.cameras[0].device_id,
        name=config.cameras[0].name,
        resolution=(config.cameras[0].resolution_width,
                   config.cameras[0].resolution_height),
        fps=config.cameras[0].fps
    )

    if not camera.open():
        logger.error("无法打开摄像头")
        return False

    # 统计变量
    frame_count = 0
    fps_start_time = time.perf_counter()
    actual_fps = 0.0
    latency_list = []

    logger.info("开始采集，按 'q' 退出...")

    try:
        while True:
            if _shutdown_event.is_set():
                logger.info("Shutdown requested, exiting realtime loop")
                break

            ret, frame = camera.read()  # 使用公共 read() 方法，不直接访问 _cap
            if not ret:
                logger.warning("帧读取失败")
                continue

            timestamp = time.perf_counter()

            # 应用视频优化流水线 (降采样 + CLAHE + 跳帧检测)
            # Use positional argument for compatibility with tests
            opt_result = optimizer.process_frame(frame, frame_count)
            processed_frame = opt_result['frame']
            should_infer = opt_result['should_infer']

            # 姿态识别
            if should_infer:
                pose_result = pose_estimator.estimate(processed_frame, timestamp)
                optimizer.update_last_result(pose_result)
            else:
                pose_result = optimizer.get_last_result()
                if not pose_result:
                    # 如果还没有任何结果，强制进行一次推理
                    pose_result = pose_estimator.estimate(processed_frame, timestamp)
                    optimizer.update_last_result(pose_result)

            # 放入缓冲队列
            frame_data = frame_buffer.put(
                frame, pose_result, camera_id
            )

            # 计算延迟
            if frame_data:
                latency_ms = frame_buffer.calculate_latency(frame_data)
                latency_list.append(latency_ms)

            # FPS计算
            frame_count += 1
            elapsed = time.perf_counter() - fps_start_time
            if elapsed >= 1.0:
                actual_fps = frame_count / elapsed
                frame_count = 0
                fps_start_time = time.perf_counter()

                # 延迟统计
                if latency_list:
                    avg_latency = np.mean(latency_list)
                    max_latency = np.max(latency_list)
                    latency_list = []

                    # 输出状态
                    landmarks_detected = len(pose_result.landmarks) if pose_result.landmarks else 0
                    logger.info(
                        f"FPS: {actual_fps:.1f} | "
                        f"关键点: {landmarks_detected}/33 | "
                        f"延迟: {avg_latency:.1f}ms (max: {max_latency:.1f}ms) | "
                        f"队列: {frame_buffer.size}/{frame_buffer.max_size}"
                    )

            # 显示画面（无论是否检测到关键点，都显示原始帧）
            if show_display:
                if pose_result.landmarks:
                    # 有关键点：绘制骨架
                    output_frame = PoseEstimator.draw_landmarks(
                        frame.copy(), pose_result
                    )
                else:
                    # 无关键点：显示原始帧，并提示未检测到人体
                    output_frame = frame.copy()
                    cv2.putText(output_frame, "No pose detected",
                                (10, 60), cv2.FONT_HERSHEY_SIMPLEX,
                                0.7, (0, 0, 255), 2)

                # 添加状态信息
                landmarks_detected = len(pose_result.landmarks) if pose_result.landmarks else 0
                info_text = (
                    f"FPS: {actual_fps:.1f} | "
                    f"Landmarks: {landmarks_detected}/33 | "
                    f"Latency: {np.mean(latency_list[-30:]) if latency_list else 0:.1f}ms"
                )
                cv2.putText(output_frame, info_text,
                          (10, 30), cv2.FONT_HERSHEY_SIMPLEX,
                          0.7, (0, 255, 0), 2)

                cv2.imshow('Pose Estimation', output_frame)

                if cv2.waitKey(1) & 0xFF == ord('q'):
                    break

    except KeyboardInterrupt:
        logger.info("用户中断")
    except SystemExit:
        raise
    except Exception as e:
        logger.error("Realtime pipeline error: %s", e, exc_info=True)
    finally:
        camera.close()
        pose_estimator.close()
        if show_display:
            cv2.destroyAllWindows()

        # 输出最终统计
        logger.info("=" * 50)
        logger.info("运行结束 - 最终统计")
        logger.info(f"平均FPS: {actual_fps:.2f}")
        logger.info(f"姿态识别器统计: {pose_estimator.get_stats()}")
        logger.info(f"帧缓冲统计: {frame_buffer.get_stats()}")

    return True


def run_video_pipeline(config_path='config.yaml',
                       video_path: str = '',
                       station_id: str = 'WS-01',
                       redis_url: str = 'redis://redis:6379/0',
                       loop: bool = False,
                       max_resolution: int = 640,
                       task_id: str = ''):
    """
    Video file playback pipeline: frame-by-frame pose detection + Redis Stream publish.

    Args:
        config_path: Config file path (for PoseEstimator params)
        video_path: Video file path
        station_id: Station ID
        redis_url: Redis connection URL
        loop: Loop playback
        max_resolution: Max frame width in pixels. Frames wider than this are
                        downscaled proportionally. Default 640 for CPU
                        compatibility. Set 0 to disable resizing.
    """
    import cv2

    from config import load_config
    config = load_config(config_path)

    from pose_estimator import PoseEstimator
    from app.perception.redis_adapter import PerceptionAdapter

    pose_estimator = PoseEstimator(
        model_complexity=config.pose.model_complexity,
        smooth=config.pose.smooth,
        min_detection_confidence=config.pose.min_detection_confidence,
        min_tracking_confidence=config.pose.min_tracking_confidence,
    )

    # Lazy-init HandEstimator only when enabled
    hand_estimator = None
    if config.hand_estimation.enabled:
        try:
            from hand_estimator import HandEstimator
            hand_estimator = HandEstimator(
                num_hands=config.hand_estimation.num_hands,
                min_detection_confidence=config.hand_estimation.min_detection_confidence,
                min_tracking_confidence=config.hand_estimation.min_tracking_confidence,
            )
            logger.info(
                "HandEstimator initialized (num_hands=%d)",
                config.hand_estimation.num_hands,
            )
        except Exception as exc:
            logger.warning(
                "HandEstimator init failed (graceful degradation): %s", exc
            )
            hand_estimator = None

    adapter = PerceptionAdapter(redis_url)

    # Initialize video optimization pipeline (4K CPU performance)
    from video_optimizer import VideoOptimizerPipeline
    actual_resolution = max_resolution if max_resolution > 0 else 0
    optimizer = VideoOptimizerPipeline(
        max_resolution=actual_resolution,
        detection_interval=6,
        enable_clahe=True,
        clahe_clip_limit=2.0
    )
    logger.info("VideoOptimizer initialized: resolution=%d, interval=%d, CLAHE=%s",
                actual_resolution, 6, True)

    logger.info("=" * 50)
    logger.info("Video playback pipeline starting")
    logger.info(f"Video path: %s", video_path)
    logger.info(f"Station ID:  %s", station_id)
    logger.info(f"Redis URL:   %s", _redact_redis_url(redis_url))
    logger.info(f"Loop:        %s", loop)
    logger.info(f"Hand est.:   %s", "enabled" if hand_estimator else "disabled")
    logger.info("=" * 50)

    # N-P0-2: Validate video path before opening
    from camera_manager import _validate_video_path, _safe_release
    from hand_estimator import HandAngleCalculator
    try:
        _validate_video_path(video_path)
    except ValueError as e:
        logger.error("Invalid video path: %s", e)
        return False

    # P1-fix: Copy video to local tmpfs before opening with cv2.
    # Eliminates NTFS 9P I/O blocking that makes threading-based timeouts
    # ineffective (native C read() holds the GIL).
    try:
        video_path = _copy_video_to_tmp(video_path)
    except FileNotFoundError:
        logger.error("Video file not found: %s", video_path)
        return False
    except OSError as exc:
        logger.error("Failed to copy video to local filesystem: %s", exc)
        return False

    cap = None
    global_frame_seq = 0  # init before try so finally can safely reference
    camera_id = f"video_{Path(video_path).stem}"
    # Init before try so except block can safely reference for progress publishing
    processed_frames = 0
    total_frames_in_video = 0
    loop_start_time = 0.0

    try:
        cap = cv2.VideoCapture(video_path)
        if not cap.isOpened():
            logger.error("Cannot open video file: %s", video_path)
            return False

        # Reduce internal buffer to minimise latency and prevent
        # read() from blocking on buffer-fill operations in Docker/WSL2.
        # Ignored by backends that do not support it (non-fatal).
        cap.set(cv2.CAP_PROP_BUFFERSIZE, 1)

        total_frames_in_video = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
        video_fps = cap.get(cv2.CAP_PROP_FPS) or 30.0
        video_width = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
        video_height = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
        video_duration_s = total_frames_in_video / video_fps if video_fps > 0 else 0.0

        logger.info("Video info: %dx%d | %.1f FPS | %d frames | %.1fs duration",
                    video_width, video_height, video_fps,
                    total_frames_in_video, video_duration_s)

        # Auto downscale for CPU-only environments (e.g. Docker containers)
        scale_factor = 1.0
        if max_resolution > 0 and video_width > max_resolution:
            scale_factor = max_resolution / video_width
            target_width = max_resolution
            target_height = int(video_height * scale_factor)
            logger.info("Downscaling %dx%d -> %dx%d (factor=%.2f, max_resolution=%d)",
                        video_width, video_height, target_width, target_height,
                        scale_factor, max_resolution)

        if not adapter.connect():
            logger.error("Redis connection failed, aborting video playback")
            return False

        adapter.publish_system_event(
            event_type="video_playback_start",
            source="perception",
            level="info",
            camera_id=camera_id,
            message=f"Station={station_id} Video={video_path} "
                    f"Frames={total_frames_in_video} Duration={video_duration_s:.1f}s",
        )

        frame_interval = 1.0 / video_fps if video_fps > 0 else 0.0
        global_frame_seq = 0
        iteration = 0
        processed_frames = 0
        pose_detected_frames = 0
        frame_fail_count = 0  # P1-1: Track consecutive frame failures
        consecutive_failures = 0

        while True:
            iteration += 1
            processed_frames = 0
            pose_detected_frames = 0
            loop_start_time = time.perf_counter()

            logger.info("--- Iteration %d start ---", iteration)

            while True:
                if _shutdown_event.is_set():
                    logger.info("Shutdown requested, exiting video loop")
                    break

                ret, frame = _safe_read(cap, timeout=5.0)
                if not ret:
                    break

                # Apply video optimization pipeline (downscale + CLAHE + skip detection)
                opt_result = optimizer.process_frame(frame, frame_index=global_frame_seq)
                processed_frame = opt_result['frame']
                should_infer = opt_result['should_infer']

                frame_timestamp = time.time()
                processed_frames += 1
                global_frame_seq += 1

                try:
                    if should_infer:
                        pose_result = pose_estimator.estimate(processed_frame, frame_timestamp)
                        optimizer.update_last_result(pose_result)
                    else:
                        pose_result = optimizer.get_last_result()
                except Exception as exc:
                    # P1-1 FIX: Track consecutive frame failures with threshold
                    consecutive_failures += 1
                    frame_fail_count += 1
                    if consecutive_failures > 10 or (total_frames_in_video > 0 and 
                        frame_fail_count > total_frames_in_video * 0.5):
                        logger.error(
                            "Frame processing failure threshold exceeded: "
                            "%d consecutive failures, %d total failures",
                            consecutive_failures, frame_fail_count,
                        )
                        # Publish error status via progress channel
                        if task_id:
                            _publish_video_progress(
                                adapter, task_id, 0.0,
                                processed_frames, total_frames_in_video,
                                status="failed",
                                error=(
                                    f"Frame processing failure threshold exceeded: "
                                    f"{frame_fail_count} frames failed"
                                ),
                            )
                        raise  # Exit the video loop with exception
                    logger.warning(
                        "Frame %d inference error: %s (skipping) [fail#%d]",
                        global_frame_seq, exc, consecutive_failures,
                    )
                    pose_result = None

                if pose_result and pose_result.landmarks:
                    pose_detected_frames += 1

                    landmarks_list = [
                        {
                            "name": lm.name,
                            "x": float(lm.x),
                            "y": float(lm.y),
                            "z": float(lm.z),
                            "visibility": float(lm.visibility),
                        }
                        for lm in pose_result.landmarks
                    ]

                    # Run HandEstimator if enabled
                    hand_landmarks_list: list[dict] = []
                    hand_features_dict: dict[str, float] = {}
                    hand_count = 0
                    if hand_estimator is not None:
                        try:
                            hand_result = hand_estimator.estimate(
                                processed_frame, timestamp=frame_timestamp
                            )
                            if hand_result.is_valid():
                                # Collect hand landmarks from all detected hands
                                for hand in [
                                    hand_result.left_hand,
                                    hand_result.right_hand,
                                ]:
                                    if hand and hand.is_valid():
                                        hand_count += 1
                                        hand_landmarks_list.extend(
                                            {
                                                "name": lm.name,
                                                "x": float(lm.x),
                                                "y": float(lm.y),
                                                "z": float(lm.z),
                                                "visibility": float(lm.visibility),
                                            }
                                            for lm in hand.landmarks
                                        )
                                        # Compute hand features (grip, spread, pinch)
                                        feats = (
                                            HandAngleCalculator.extract_features(hand)
                                        )
                                        hand_features_dict = feats.to_dict()
                                        # Keep features from the first valid hand
                                        # (averaging双手 is an option for future)
                                        break
                        except Exception as exc:
                            logger.warning(
                                "Frame %d hand estimation error: %s (skipping)",
                                global_frame_seq, exc,
                            )

                    frame_id = f"{global_frame_seq:020d}"

                    adapter.publish_pose_frame(
                        camera_id=camera_id,
                        timestamp=frame_timestamp,
                        frame_id=frame_id,
                        landmarks=landmarks_list,
                        pose_score=float(pose_result.pose_score),
                        station_id=station_id,
                        landmark_count=len(pose_result.landmarks),
                        hand_count=hand_count,
                        hand_landmarks=hand_landmarks_list or None,
                        hand_features=hand_features_dict or None,
                    )

                if adapter.check_backpressure():
                    time.sleep(0.05)

                if frame_interval > 0:
                    elapsed_in_frame = time.perf_counter() - frame_timestamp
                    sleep_time = frame_interval - elapsed_in_frame
                    if sleep_time > 0:
                        time.sleep(sleep_time)

                if processed_frames % max(1, int(video_fps)) == 0:
                    logger.info(
                        "Frame progress: %d/%d | Pose detected: %d frames",
                        processed_frames, total_frames_in_video,
                        pose_detected_frames,
                    )

                # Publish progress via Redis Pub/Sub (every 10% of total frames)
                if task_id and total_frames_in_video > 0:
                    progress_interval = max(1, total_frames_in_video // 10)
                    if processed_frames > 0 and processed_frames % progress_interval == 0:
                        progress = processed_frames / total_frames_in_video
                        _publish_video_progress(
                            adapter, task_id, progress,
                            processed_frames, total_frames_in_video,
                        )

            loop_elapsed = time.perf_counter() - loop_start_time
            actual_fps = processed_frames / loop_elapsed if loop_elapsed > 0 else 0.0
            detection_rate = (pose_detected_frames / processed_frames * 100
                              if processed_frames > 0 else 0.0)

            adapter.publish_system_event(
                event_type="video_playback_end",
                source="perception",
                level="info",
                camera_id=camera_id,
                message=(f"Station={station_id} Iteration={iteration} "
                         f"Frames={processed_frames} PoseFrames={pose_detected_frames} "
                         f"FPS={actual_fps:.1f} Duration={loop_elapsed:.1f}s"),
            )

            # Publish completed status if task_id is set
            if task_id:
                success_rate = round(
                    (processed_frames - frame_fail_count) / max(processed_frames, 1) * 100, 1
                ) if frame_fail_count > 0 else 100.0
                _publish_video_progress(
                    adapter, task_id, 1.0,
                    processed_frames, total_frames_in_video,
                    status="completed", duration_s=loop_elapsed,
                    success_rate=success_rate,
                )

            logger.info("=" * 50)
            logger.info("Iteration %d finished - Statistics", iteration)
            logger.info("  Total frames:     %d", processed_frames)
            logger.info("  Processing FPS:   %.1f", actual_fps)
            logger.info("  Pose frames:      %d", pose_detected_frames)
            logger.info("  Detection rate:   %.1f%%", detection_rate)
            logger.info("  Video duration:   %.1fs", video_duration_s)
            logger.info("  Processing time:  %.1fs", loop_elapsed)
            logger.info("=" * 50)

            if not loop or _shutdown_event.is_set():
                break

            cap.set(cv2.CAP_PROP_POS_FRAMES, 0)
            logger.info("Loop mode: restarting playback...")

    except KeyboardInterrupt:
        logger.info("Video playback interrupted by user")
        if task_id:
            try:
                _elapsed = time.perf_counter() - loop_start_time if loop_start_time else 0.0
                _publish_video_progress(
                    adapter, task_id, 0.0,
                    processed_frames, total_frames_in_video,
                    status="cancelled",
                    duration_s=_elapsed,
                    error="Interrupted by user",
                )
            except Exception:
                pass
    except SystemExit:
        raise
    except Exception as e:
        logger.error("Video pipeline error: %s", e, exc_info=True)
        # Publish failed status if task_id is set
        if task_id:
            try:
                _elapsed = time.perf_counter() - loop_start_time if loop_start_time else 0.0
                _publish_video_progress(
                    adapter, task_id, 0.0,
                    processed_frames, total_frames_in_video,
                    status="failed",
                    duration_s=_elapsed,
                    error=str(e)[:500],
                )
            except Exception:
                pass  # best-effort, don't mask original error
    finally:
        # Best-effort cleanup: each operation has timeout protection
        # to prevent hanging during Docker SIGTERM shutdown.
        try:
            _safe_redis_call(
                lambda: adapter.publish_system_event(
                    event_type="video_playback_stop",
                    source="perception",
                    level="warn",
                    camera_id=camera_id,
                    message=f"Station={station_id} UserInterrupt TotalFrames={global_frame_seq}",
                ),
                timeout=3.0,
                label="publish_stop_event",
            )
        except Exception:
            logger.warning("Failed to publish stop event during shutdown")

        _safe_release(cap, timeout=3.0, source_name=camera_id)
        pose_estimator.close(timeout=5.0)
        if hand_estimator is not None:
            hand_estimator.close(timeout=5.0)

        try:
            _safe_redis_call(adapter.close, timeout=3.0, label="adapter_close")
        except Exception:
            logger.warning("Failed to close Redis adapter during shutdown")

        logger.info("Video playback pipeline closed")

    return True


def run_performance_test(camera_id=0, show_display=True):
    """
    运行性能测试

    测试项目：
    1. 帧率稳定性（目标 30 FPS）
    2. 端到端延迟（目标 < 33ms）
    3. 关键点检测率

    Args:
        camera_id: 摄像头设备ID
        show_display: 是否显示实时预览窗口（True = 显示，按 q 可提前退出）
    """
    import cv2
    import numpy as np

    from camera_manager import CameraManager
    from pose_estimator import PoseEstimator
    from config import load_config

    logger.info("=" * 50)
    logger.info("性能测试开始")
    logger.info("=" * 50)

    # 加载配置
    config = load_config('config.yaml')

    # 创建组件
    camera_manager = CameraManager()
    camera = camera_manager.add_camera(
        device_id=camera_id,
        resolution=(1280, 720),
        fps=30
    )

    pose_estimator = PoseEstimator(
        model_complexity=config.pose.model_complexity,
        smooth=config.pose.smooth
    )

    if not camera.open():
        logger.error("无法打开摄像头，测试失败")
        return False

    # 测试数据收集
    test_duration = 10  # 测试时长（秒）
    fps_list = []
    latency_list = []
    inference_time_list = []
    landmarks_count_list = []

    logger.info(f"测试时长: {test_duration} 秒")
    if show_display:
        logger.info("预览窗口已启动，按 'q' 可提前结束测试...")
    logger.info("开始采集测试数据...")

    start_time = time.perf_counter()
    frame_count = 0
    actual_fps = 0.0

    try:
        while time.perf_counter() - start_time < test_duration:
            ret, frame = camera.read()  # 使用公共 read() 方法，不直接访问 _cap
            if not ret:
                continue

            frame_start = time.perf_counter()

            # 姿态识别
            pose_result = pose_estimator.estimate(frame, time.perf_counter())

            # 计算延迟
            latency = (time.perf_counter() - frame_start) * 1000.0

            frame_count += 1
            elapsed = time.perf_counter() - start_time

            if elapsed >= 1.0:
                actual_fps = frame_count / elapsed
                fps_list.append(actual_fps)
                frame_count = 0
                start_time = time.perf_counter()

            latency_list.append(latency)
            inference_time_list.append(pose_result.inference_time_ms)
            landmarks_count_list.append(len(pose_result.landmarks))

            # 实时预览窗口
            if show_display:
                # 在原帧上绘制关键点（有检测结果时）
                if pose_result.landmarks:
                    output_frame = PoseEstimator.draw_landmarks(
                        frame.copy(), pose_result
                    )
                else:
                    output_frame = frame.copy()

                # 剩余时间
                remaining = max(0.0, test_duration - (time.perf_counter() - start_time))

                # 叠加状态信息
                landmarks_detected = len(pose_result.landmarks) if pose_result.landmarks else 0
                info_lines = [
                    f"FPS: {actual_fps:.1f}  Latency: {latency:.1f}ms",
                    f"Landmarks: {landmarks_detected}/33",
                    f"Remaining: {remaining:.1f}s  [q] to quit",
                ]
                for idx, text in enumerate(info_lines):
                    cv2.putText(
                        output_frame, text,
                        (10, 30 + idx * 28),
                        cv2.FONT_HERSHEY_SIMPLEX, 0.7, (0, 255, 0), 2
                    )

                cv2.imshow('Performance Test - Pose Estimation', output_frame)

                # 按 q 提前退出
                if cv2.waitKey(1) & 0xFF == ord('q'):
                    logger.info("用户按 q 提前结束测试")
                    break

    finally:
        camera.close()
        pose_estimator.close()
        if show_display:
            cv2.destroyAllWindows()

    # 分析结果
    logger.info("=" * 50)
    logger.info("测试结果分析")
    logger.info("=" * 50)

    # FPS分析
    avg_fps = np.mean(fps_list) if fps_list else 0
    min_fps = np.min(fps_list) if fps_list else 0
    fps_stability = "通过" if avg_fps >= 28 else "未通过"
    logger.info(f"[FPS] 平均: {avg_fps:.2f} | 最低: {min_fps:.2f} | 状态: {fps_stability} (目标 >= 28)")

    # 延迟分析
    avg_latency = np.mean(latency_list)
    max_latency = np.max(latency_list)
    p95_latency = np.percentile(latency_list, 95)
    latency_status = "通过" if avg_latency < 33 else "未通过"
    logger.info(f"[延迟] 平均: {avg_latency:.2f}ms | P95: {p95_latency:.2f}ms | 最大: {max_latency:.2f}ms | 状态: {latency_status} (目标 < 33ms)")

    # 推理时间分析
    avg_inference = np.mean(inference_time_list)
    max_inference = np.max(inference_time_list)
    logger.info(f"[推理] 平均: {avg_inference:.2f}ms | 最大: {max_inference:.2f}ms")

    # 关键点检测分析
    avg_landmarks = np.mean(landmarks_count_list)
    detection_rate = sum(1 for x in landmarks_count_list if x > 0) / len(landmarks_count_list) * 100
    landmarks_status = "通过" if avg_landmarks >= 30 else "未通过"
    logger.info(f"[关键点] 平均检测: {avg_landmarks:.1f}/33 | 检测率: {detection_rate:.1f}% | 状态: {landmarks_status} (目标 >= 30)")

    # 综合评估
    logger.info("=" * 50)
    all_pass = fps_stability == "通过" and latency_status == "通过" and landmarks_status == "通过"
    logger.info(f"综合评估: {'全部通过' if all_pass else '部分未通过'}")
    logger.info("=" * 50)

    return all_pass


def main():
    """主入口"""
    _setup_signal_handlers()
    args = parse_args()

    # 检测摄像头
    if args.detect_cameras:
        detect_available_cameras()
        return

    # Performance test mode
    if args.test_only:
        success = run_performance_test(args.camera_id, show_display=not args.no_display)
        sys.exit(0 if success else 1)

    # Video playback mode (--video takes priority, fallback to VIDEO_MODE env)
    video_mode = args.video or (
        os.environ.get('VIDEO_MODE', '').lower() in ('true', '1', 'yes')
    )
    video_path = args.video or os.environ.get('VIDEO_PATH', '')
    if video_mode and video_path:
        run_video_pipeline(
            config_path=args.config,
            video_path=video_path,
            station_id=args.station_id,
            redis_url=args.redis_url,
            loop=args.loop,
            max_resolution=args.max_resolution,
            task_id=args.task_id,
        )
        return

    # Default: realtime camera mode
    run_realtime_pipeline(
        config_path=args.config,
        camera_id=args.camera_id,
        show_display=not args.no_display,
        max_resolution=args.max_resolution
    )


if __name__ == '__main__':
    main()
