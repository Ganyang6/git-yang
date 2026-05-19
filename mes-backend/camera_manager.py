"""
Camera manager module
Features:
  - Auto-detect available cameras
  - Config-driven: resolution, fps, device ID
  - Multi-thread capture with hot-plug support
  - Auto-reconnect mechanism
  - Video file input support (T7-02)
"""

import cv2
import os
import re
import logging
import threading
import time
from dataclasses import dataclass
from pathlib import Path
from typing import List, Optional, Callable, Dict, Any, Union
import logging

logger = logging.getLogger(__name__)

# Allowed video file extensions for path validation (N-P0-1)
_ALLOWED_VIDEO_EXTENSIONS = frozenset({".mp4", ".avi", ".mov", ".mkv", ".wmv", ".flv", ".webm"})
# Pattern to detect path traversal attempts
_PATH_TRAVERSAL_RE = re.compile(r"(?:^|[\\/])\.\.(?:[\\/]|$)")


def _validate_video_path(path: str) -> None:
    """Validate video file path to prevent path traversal attacks.

    Raises:
        ValueError: If the path is unsafe.
    """
    if not path or not isinstance(path, str):
        raise ValueError("Video path must be a non-empty string")

    # Reject path traversal patterns
    if _PATH_TRAVERSAL_RE.search(path):
        raise ValueError(f"Path traversal detected in video path: {path}")

    # Normalize and resolve the path
    resolved = Path(path).resolve()

    # Must be an absolute path after normalization
    if not resolved.is_absolute():
        raise ValueError(f"Video path must be absolute: {path}")

    # Check extension whitelist
    ext = resolved.suffix.lower()
    if ext not in _ALLOWED_VIDEO_EXTENSIONS:
        raise ValueError(
            f"Unsupported video extension '{ext}'. "
            f"Allowed: {', '.join(sorted(_ALLOWED_VIDEO_EXTENSIONS))}"
        )

    # Check file actually exists
    if not resolved.is_file():
        raise ValueError(f"Video file does not exist: {resolved}")

    logger.debug("Video path validated: %s", resolved)


def _safe_release(cap, timeout: float = 3.0, source_name: str = "source"):
    """Release a VideoCapture with timeout protection.

    OpenCV VideoCapture.release() can block indefinitely when the
    underlying V4L2 driver hangs (e.g. USB hot-plug, device fd race).
    This wrapper runs release() in a daemon thread and gives up after
    *timeout* seconds.
    """
    if cap is None:
        return
    def _release():
        try:
            cap.release()
        except Exception as e:
            logger.warning("Error releasing %s: %s", source_name, e)
    t = threading.Thread(target=_release, daemon=True)
    t.start()
    t.join(timeout=timeout)
    if t.is_alive():
        logger.warning(
            "%s release did not complete within %.1fs, "
            "likely V4L2 driver hang (abandoning daemon thread)",
            source_name, timeout,
        )


def _safe_read(cap, timeout: float = 5.0):
    """Read a frame from VideoCapture with timeout protection.

    cv2.VideoCapture.read() can block indefinitely when the underlying
    native C I/O stalls (Docker + WSL2 + NTFS bind mount, damaged file
    headers, V4L2 driver hangs).  This wrapper runs read() in a daemon
    thread and returns (False, None) if it does not complete within
    *timeout* seconds.

    .. note::
       This timeout is **not guaranteed** to fire if cap.read() is a
       native C call that holds the GIL during blocking I/O (e.g. FFmpeg
       reading from a stalled NTFS 9P mount).  Use
       ``main._copy_video_to_tmp`` to pre-copy videos to a local
       filesystem when running in Docker/WSL2.  In those environments the
       timeout serves only as a second line of defence.

    Args:
        cap: cv2.VideoCapture instance.
        timeout: Maximum seconds to wait for read() to return.

    Returns:
        (ret, frame): Same as cap.read(), or (False, None) on timeout/error.
    """
    if cap is None or not cap.isOpened():
        return False, None

    result: dict = {"ret": False, "frame": None}

    def _read():
        try:
            result["ret"], result["frame"] = cap.read()
        except Exception as exc:
            logger.warning(
                "cv2.VideoCapture.read() raised %s: %s",
                type(exc).__name__, exc,
            )
            result["ret"] = False

    t = threading.Thread(target=_read, daemon=True)
    t.start()
    t.join(timeout=timeout)

    if t.is_alive():
        logger.warning(
            "cv2.VideoCapture.read() blocked for %.1fs, aborting "
            "(possible Docker/WSL2/NTFS mount issue or corrupted video)",
            timeout,
        )
        return False, None

    return result["ret"], result["frame"]


@dataclass
class CameraInfo:
    """Camera / video source information"""
    device_id: Union[int, str]
    name: str
    resolution: tuple  # (width, height)
    fps: float
    backend: str
    is_opened: bool = False
    is_running: bool = False
    source_type: str = "camera"  # "camera" or "file"


class CameraCapture:
    """
    Single camera / video file capturer.
    Wraps OpenCV VideoCapture for stable frame acquisition.
    Supports device ID (int) and video file path (str).
    """

    BACKENDS = {
        'auto': cv2.CAP_ANY,
        'v4l2': cv2.CAP_V4L2,
        'msmf': cv2.CAP_MSMF,
        'dshow': cv2.CAP_DSHOW,
        'gstreamer': cv2.CAP_GSTREAMER,
        'ffmpeg': cv2.CAP_FFMPEG
    }

    def __init__(self, device_id: Union[int, str], name: str = None,
                 resolution: tuple = (1280, 720), fps: int = 30,
                 backend: str = 'auto', loop: bool = False):
        """
        Args:
            device_id: Device ID (0, 1, 2...) or video file path
            name: Camera name
            resolution: (width, height) -- only applied to camera devices
            fps: Target fps -- only applied to camera devices
            backend: Capture backend ('auto', 'v4l2', 'msmf', 'dshow')
            loop: Loop video file playback
        """
        self.device_id = device_id
        self.name = name or f"Camera_{device_id}"
        self.resolution = resolution
        self.target_fps = fps
        self.backend = self.BACKENDS.get(backend.lower(), cv2.CAP_ANY)
        self._loop = loop
        self._is_file_source = isinstance(device_id, str)

        # N-P0-1: Validate video file paths for security
        if self._is_file_source:
            _validate_video_path(device_id)

        self._cap: Optional[cv2.VideoCapture] = None
        self._is_running = False
        self._thread: Optional[threading.Thread] = None
        self._frame_callback: Optional[Callable] = None
        self._current_frame = None
        self._frame_lock = threading.Lock()

        # Thread-safe stats dict (N-P1-25)
        self._stats_lock = threading.Lock()
        self._stats = {
            'frames_captured': 0,
            'frames_dropped': 0,
            'last_error': None,
            'consecutive_failures': 0
        }

    def open(self) -> bool:
        """
        Open camera or video file.

        Returns:
            bool: Whether opened successfully
        """
        if self._cap is not None and self._cap.isOpened():
            return True

        try:
            self._cap = cv2.VideoCapture(self.device_id, self.backend)

            if not self._cap.isOpened():
                logger.error(f"Cannot open source {self.device_id}: {self.name}")
                with self._stats_lock:
                    self._stats['last_error'] = f"Source {self.device_id} not available"
                return False

            if self._is_file_source:
                # Video file: use its own resolution / fps, do NOT set BUFFERSIZE
                actual_width = self._cap.get(cv2.CAP_PROP_FRAME_WIDTH)
                actual_height = self._cap.get(cv2.CAP_PROP_FRAME_HEIGHT)
                actual_fps = self._cap.get(cv2.CAP_PROP_FPS)
                total_frames = int(self._cap.get(cv2.CAP_PROP_FRAME_COUNT))
                logger.info(f"Video source '{self.name}' opened: "
                            f"file={self.device_id}, "
                            f"resolution={actual_width}x{actual_height}, "
                            f"fps={actual_fps}, "
                            f"total_frames={total_frames}, "
                            f"loop={self._loop}")
            else:
                # Camera device: set resolution, fps, buffer size
                self._cap.set(cv2.CAP_PROP_FRAME_WIDTH, self.resolution[0])
                self._cap.set(cv2.CAP_PROP_FRAME_HEIGHT, self.resolution[1])
                self._cap.set(cv2.CAP_PROP_FPS, self.target_fps)

                actual_width = self._cap.get(cv2.CAP_PROP_FRAME_WIDTH)
                actual_height = self._cap.get(cv2.CAP_PROP_FRAME_HEIGHT)
                actual_fps = self._cap.get(cv2.CAP_PROP_FPS)

                logger.info(f"Camera '{self.name}' opened: "
                            f"resolution={actual_width}x{actual_height}, "
                            f"fps={actual_fps}")

                self._cap.set(cv2.CAP_PROP_BUFFERSIZE, 1)

            return True

        except Exception as e:
            logger.error(f"Error opening source {self.device_id}: {e}")
            with self._stats_lock:
                self._stats['last_error'] = str(e)
            return False

    def close(self, release_timeout: float = 3.0) -> None:
        """Close camera / video file.

        Args:
            release_timeout: Max seconds to wait for VideoCapture.release().
                Uses a daemon thread to avoid indefinite V4L2 hangs.
        """
        self.stop()
        if self._cap is not None:
            _safe_release(self._cap, timeout=release_timeout,
                          source_name=self.name)
            self._cap = None
        logger.info("Source '%s' closed", self.name)

    def start(self, callback: Callable[[Any], None]) -> bool:
        """
        Start capturing (background thread).

        Args:
            callback: Frame callback (frame, timestamp)

        Returns:
            bool: Whether started successfully
        """
        if self._is_running:
            return True

        if not self.open():
            return False

        self._frame_callback = callback
        self._is_running = True
        self._thread = threading.Thread(target=self._capture_loop, daemon=True)
        self._thread.start()

        logger.info(f"Source '{self.name}' started capturing")
        return True

    def stop(self) -> None:
        """Stop capturing"""
        self._is_running = False
        if self._thread is not None:
            self._thread.join(timeout=2.0)
            self._thread = None
        logger.info(f"Source '{self.name}' stopped capturing")

    def _capture_loop(self) -> None:
        """Capture loop (background thread)"""
        while self._is_running:
            if self._cap is None or not self._cap.isOpened():
                break

            ret, frame = _safe_read(self._cap, timeout=5.0)

            if not ret:
                if self._is_file_source:
                    # Video file ended
                    if self._loop:
                        logger.info(f"Video '{self.name}' looping")
                        self._cap.set(cv2.CAP_PROP_POS_FRAMES, 0)
                        continue
                    else:
                        logger.info(f"Video '{self.name}' playback completed")
                        self._is_running = False
                        break
                else:
                    # Camera: reconnect logic
                    with self._stats_lock:
                        self._stats['consecutive_failures'] += 1
                        if self._stats['consecutive_failures'] > 10:
                            should_reconnect = True
                        else:
                            should_reconnect = False
                    if should_reconnect:
                        logger.warning(f"Camera '{self.name}': consecutive read failures")
                        self._handle_disconnect()
                        break
                    continue

            with self._stats_lock:
                self._stats['consecutive_failures'] = 0
                self._stats['frames_captured'] += 1

            timestamp = time.perf_counter()

            with self._frame_lock:
                self._current_frame = (frame.copy(), timestamp)

            if self._frame_callback:
                try:
                    self._frame_callback(frame, timestamp)
                except Exception as e:
                    logger.error(f"Frame callback error: {e}")

    def _handle_disconnect(self) -> None:
        """Handle camera disconnect (only for camera devices)"""
        logger.warning(f"Camera '{self.name}' disconnected, attempting reconnect...")
        with self._stats_lock:
            self._stats['frames_dropped'] += 1

        for attempt in range(3):
            time.sleep(1.0)
            if self.open():
                logger.info(f"Camera '{self.name}' reconnected")
                return

        logger.error(f"Camera '{self.name}' failed to reconnect after 3 attempts")

    def read(self, timeout: float = 5.0) -> tuple[bool, Optional[Any]]:
        """Read one frame with timeout protection.

        Uses _safe_read to run the native C cap.read() in a dedicated
        thread, so that the timeout can fire even when the GIL is held
        by blocking I/O (NTFS 9P mount in Docker/WSL2).

        Args:
            timeout: Maximum seconds to wait for a frame. Defaults to 5.0.

        Returns:
            (success, frame): frame is None when success is False
        """
        if self._cap is None or not self._cap.isOpened():
            return False, None
        ret, frame = _safe_read(self._cap, timeout=timeout)
        with self._stats_lock:
            if ret:
                self._stats['frames_captured'] += 1
                self._stats['consecutive_failures'] = 0
            else:
                if self._is_file_source:
                    pass
                else:
                    self._stats['consecutive_failures'] += 1
                    self._stats['frames_dropped'] += 1
        return ret, frame

    def get_frame(self) -> Optional[Any]:
        """
        Get current frame (non-blocking).

        Returns:
            (frame, timestamp) or None
        """
        with self._frame_lock:
            return self._current_frame

    def get_stats(self) -> Dict[str, Any]:
        """Get capture statistics"""
        with self._stats_lock:
            return self._stats.copy()

    @property
    def is_opened(self) -> bool:
        return self._cap is not None and self._cap.isOpened()

    @property
    def is_running(self) -> bool:
        return self._is_running

    @property
    def is_file_source(self) -> bool:
        return self._is_file_source


class CameraManager:
    """
    Multi-source manager.
    Manages multiple cameras and/or video files for capture, config, and status monitoring.
    """

    def __init__(self):
        self._cameras: Dict[str, CameraCapture] = {}
        self._lock = threading.Lock()
        self._global_stats = {
            'total_frames': 0,
            'active_cameras': 0
        }

    def add_camera(self, device_id: Union[int, str], name: str = None,
                   resolution: tuple = (1280, 720), fps: int = 30,
                   backend: str = 'auto', loop: bool = False) -> CameraCapture:
        """
        Add a camera or video source.

        Args:
            device_id: Device ID or video file path
            name: Source name (used as internal key)
            resolution: (width, height) -- only for cameras
            fps: Target fps -- only for cameras
            backend: Capture backend
            loop: Loop video playback

        Returns:
            CameraCapture instance
        """
        cam_name = name or (f"Video_{Path(device_id).stem}" if isinstance(device_id, str)
                           else f"Camera_{device_id}")

        # N-P0-1: validate video file path to prevent path traversal attacks
        if isinstance(device_id, str):
            _validate_video_path(device_id)

        with self._lock:
            if cam_name in self._cameras:
                return self._cameras[cam_name]

            camera = CameraCapture(
                device_id=device_id,
                name=cam_name,
                resolution=resolution,
                fps=fps,
                backend=backend,
                loop=loop,
            )
            self._cameras[cam_name] = camera
            return camera

    def remove_camera(self, name: str) -> None:
        """Remove camera/video by name"""
        with self._lock:
            if name in self._cameras:
                self._cameras[name].close()
                del self._cameras[name]

    def get_camera(self, name: str) -> Optional[CameraCapture]:
        """Get camera/video by name"""
        return self._cameras.get(name)

    def list_cameras(self) -> List[CameraInfo]:
        """List all added sources"""
        cameras = []
        with self._lock:
            for cam_name, cam in self._cameras.items():
                cameras.append(CameraInfo(
                    device_id=cam.device_id,
                    name=cam.name,
                    resolution=cam.resolution,
                    fps=cam.target_fps,
                    backend=cam.backend,
                    is_opened=cam.is_opened,
                    is_running=cam.is_running,
                    source_type="file" if cam.is_file_source else "camera",
                ))
        return cameras

    @staticmethod
    def detect_available_cameras(max_devices: int = 10) -> List[int]:
        """
        Auto-detect available cameras.

        Args:
            max_devices: Max devices to check

        Returns:
            List[int]: Available device ID list
        """
        available = []
        for i in range(max_devices):
            cap = cv2.VideoCapture(i)
            if cap.isOpened():
                available.append(i)
                cap.release()
        return available

    def start_all(self, callback: Callable[[str, Any, float], None]) -> Dict[str, bool]:
        """
        Start all sources.

        Args:
            callback: (camera_name, frame, timestamp)

        Returns:
            Dict[str, bool]: Start result per source
        """
        results = {}

        # N-P1-33: Collect camera refs under lock, but start outside lock
        # to avoid holding lock during blocking camera.open()/thread.start() calls.
        cameras_to_start: list = []
        with self._lock:
            for cam_name, camera in self._cameras.items():
                cameras_to_start.append((cam_name, camera))

        for cam_name, camera in cameras_to_start:
            def make_cb(name):
                def cb(frame, timestamp):
                    self._global_stats['total_frames'] += 1
                    callback(name, frame, timestamp)
                return cb

            results[cam_name] = camera.start(make_cb(cam_name))

        self._global_stats['active_cameras'] = sum(1 for v in results.values() if v)
        return results

    def stop_all(self) -> None:
        """Stop all sources"""
        with self._lock:
            for camera in self._cameras.values():
                camera.stop()
        self._global_stats['active_cameras'] = 0

    def get_all_stats(self) -> Dict[str, Any]:
        """Get global statistics"""
        stats = self._global_stats.copy()
        with self._lock:
            camera_stats = {name: cam.get_stats() for name, cam in self._cameras.items()}
        stats['cameras'] = camera_stats
        return stats



