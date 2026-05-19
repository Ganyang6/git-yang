"""
CameraCapture / CameraManager / CameraConfig 单元测试
不依赖真实摄像头，使用 unittest.mock 模拟 cv2.VideoCapture
"""

import threading
from unittest.mock import MagicMock, patch, PropertyMock
import numpy as np
import pytest


# -----------------------------------------------------------------------
# Fixtures
# -----------------------------------------------------------------------

@pytest.fixture
def mock_cap():
    """模拟一个已打开、可正常读帧的 cv2.VideoCapture"""
    cap = MagicMock()
    cap.isOpened.return_value = True
    cap.get.side_effect = lambda prop: {
        # CAP_PROP_FRAME_WIDTH=3, CAP_PROP_FRAME_HEIGHT=4, CAP_PROP_FPS=5
        3: 1280.0,
        4: 720.0,
        5: 30.0,
    }.get(prop, 0.0)
    # 每次 read() 返回一个随机 720p 帧
    rng = np.random.default_rng(seed=0)
    cap.read.return_value = (True, rng.integers(0, 256, (720, 1280, 3), dtype=np.uint8))
    return cap


@pytest.fixture
def mock_video_cap():
    """模拟一个视频文件 VideoCapture (额外返回 CAP_PROP_FRAME_COUNT)"""
    cap = MagicMock()
    cap.isOpened.return_value = True
    cap.get.side_effect = lambda prop: {
        3: 1920.0,   # CAP_PROP_FRAME_WIDTH
        4: 1080.0,   # CAP_PROP_FRAME_HEIGHT
        5: 25.0,     # CAP_PROP_FPS
        7: 500.0,    # CAP_PROP_FRAME_COUNT
    }.get(prop, 0.0)
    rng = np.random.default_rng(seed=42)
    cap.read.return_value = (True, rng.integers(0, 256, (1080, 1920, 3), dtype=np.uint8))
    return cap


@pytest.fixture
def camera_capture(mock_cap):
    """使用 mock VideoCapture 的 CameraCapture 实例"""
    from camera_manager import CameraCapture
    with patch('camera_manager.cv2.VideoCapture', return_value=mock_cap):
        cam = CameraCapture(device_id=0, name='test_cam', resolution=(1280, 720), fps=30)
        cam.open()
        yield cam
        cam.close()


@pytest.fixture
def video_capture(mock_video_cap):
    """使用 mock 视频文件的 CameraCapture 实例"""
    from camera_manager import CameraCapture
    with patch('camera_manager.cv2.VideoCapture', return_value=mock_video_cap):
        cam = CameraCapture(device_id='/data/test.mp4', name='test_video', loop=False)
        cam.open()
        yield cam
        cam.close()


# -----------------------------------------------------------------------
# CameraConfig 测试 (T7-01 + T7-07)
# -----------------------------------------------------------------------

class TestCameraConfig:
    """CameraConfig dataclass 字段和属性"""

    def test_default_source_type_is_camera(self):
        """默认构造时 source_type 为 'camera'"""
        from config import CameraConfig
        cfg = CameraConfig()
        assert cfg.source_type == "camera"

    def test_source_type_file_when_video_path_set(self):
        """设置 video_path 时 source_type 为 'file'"""
        from config import CameraConfig
        cfg = CameraConfig(video_path="/data/test.mp4")
        assert cfg.source_type == "file"

    def test_source_property_returns_device_id_for_camera(self):
        """摄像头模式下 source 返回 device_id"""
        from config import CameraConfig
        cfg = CameraConfig(device_id=2)
        assert cfg.source == 2

    def test_source_property_returns_video_path_for_file(self):
        """文件模式下 source 返回 video_path"""
        from config import CameraConfig
        cfg = CameraConfig(video_path="/data/test.mp4", device_id=0)
        assert cfg.source == "/data/test.mp4"

    def test_source_property_priority_video_over_device_id(self):
        """video_path 优先于 device_id"""
        from config import CameraConfig
        cfg = CameraConfig(device_id=3, video_path="/data/other.mp4")
        assert cfg.source_type == "file"
        assert cfg.source == "/data/other.mp4"

    def test_station_id_default(self):
        """默认 station_id 为 WS-01"""
        from config import CameraConfig
        cfg = CameraConfig()
        assert cfg.station_id == "WS-01"

    def test_station_id_custom(self):
        """自定义 station_id"""
        from config import CameraConfig
        cfg = CameraConfig(station_id="WS-03")
        assert cfg.station_id == "WS-03"

    def test_loop_default_false(self):
        """默认 loop 为 False"""
        from config import CameraConfig
        cfg = CameraConfig()
        assert cfg.loop is False

    def test_loop_custom(self):
        """自定义 loop"""
        from config import CameraConfig
        cfg = CameraConfig(loop=True)
        assert cfg.loop is True

    def test_video_path_default_none(self):
        """默认 video_path 为 None"""
        from config import CameraConfig
        cfg = CameraConfig()
        assert cfg.video_path is None


class TestCameraConfigYamlRoundTrip:
    """config.yaml 的 load/save 包含新字段"""

    def test_load_config_with_video_path(self, tmp_path):
        """从 YAML 加载 video_path / station_id / loop"""
        from config import load_config
        yaml_content = """
cameras:
  - video_path: "/app/data/videos/line.mp4"
    name: "Video_WS01"
    station_id: "WS-02"
    enabled: true
    loop: true
"""
        cfg_file = tmp_path / "config.yaml"
        cfg_file.write_text(yaml_content, encoding='utf-8')

        config = load_config(str(cfg_file))
        assert len(config.cameras) == 1
        cam = config.cameras[0]
        assert cam.video_path == "/app/data/videos/line.mp4"
        assert cam.station_id == "WS-02"
        assert cam.loop is True
        assert cam.source_type == "file"

    def test_save_config_includes_new_fields(self, tmp_path):
        """save_config 序列化包含 video_path / station_id / loop"""
        from config import CameraConfig, SystemConfig, save_config, load_config
        cfg = SystemConfig()
        cfg.cameras.append(CameraConfig(
            video_path="/data/test.mp4",
            name="Video_WS03",
            station_id="WS-03",
            loop=True,
        ))
        out = tmp_path / "out.yaml"
        save_config(cfg, str(out))

        reloaded = load_config(str(out))
        assert len(reloaded.cameras) == 1
        assert reloaded.cameras[0].video_path == "/data/test.mp4"
        assert reloaded.cameras[0].station_id == "WS-03"
        assert reloaded.cameras[0].loop is True


# -----------------------------------------------------------------------
# CameraCapture 测试 -- 原有摄像头功能
# -----------------------------------------------------------------------

class TestCameraCaptureOpen:
    """open() 行为"""

    def test_open_success(self, mock_cap):
        """mock 摄像头可以成功打开"""
        from camera_manager import CameraCapture
        with patch('camera_manager.cv2.VideoCapture', return_value=mock_cap):
            cam = CameraCapture(device_id=0)
            assert cam.open() is True
            cam.close()

    def test_open_already_opened_returns_true(self, camera_capture):
        """已打开的摄像头再次调用 open() 应直接返回 True"""
        assert camera_capture.open() is True

    def test_open_failed_when_cap_not_opened(self):
        """VideoCapture.isOpened() 返回 False 时，open() 应返回 False"""
        from camera_manager import CameraCapture
        failed_cap = MagicMock()
        failed_cap.isOpened.return_value = False
        with patch('camera_manager.cv2.VideoCapture', return_value=failed_cap):
            cam = CameraCapture(device_id=99)
            assert cam.open() is False

    def test_is_opened_property(self, camera_capture):
        """is_opened 属性应反映真实打开状态"""
        assert camera_capture.is_opened is True


class TestCameraCaptureRead:
    """公共 read() 方法"""

    def test_read_returns_tuple(self, camera_capture):
        """read() 应返回 (bool, frame) 元组"""
        ret, frame = camera_capture.read()
        assert isinstance(ret, bool)

    def test_read_success(self, camera_capture):
        """mock 正常帧时，read() 应返回 True 和非 None 帧"""
        ret, frame = camera_capture.read()
        assert ret is True
        assert frame is not None

    def test_read_increments_captured_count(self, camera_capture):
        """成功 read() 后，stats['frames_captured'] 应递增"""
        before = camera_capture.get_stats()['frames_captured']
        camera_capture.read()
        after = camera_capture.get_stats()['frames_captured']
        assert after == before + 1

    def test_read_failed_increments_dropped_count(self, mock_cap):
        """read() 返回 False 时，stats['frames_dropped'] 应递增"""
        from camera_manager import CameraCapture
        mock_cap.read.return_value = (False, None)
        with patch('camera_manager.cv2.VideoCapture', return_value=mock_cap):
            cam = CameraCapture(device_id=0)
            cam.open()
            ret, frame = cam.read()
            assert ret is False
            assert cam.get_stats()['frames_dropped'] == 1
            cam.close()

    def test_read_when_not_opened_returns_false(self):
        """未打开的摄像头调用 read() 应返回 (False, None)"""
        from camera_manager import CameraCapture
        cam = CameraCapture(device_id=0)
        ret, frame = cam.read()
        assert ret is False
        assert frame is None


class TestCameraCaptureStats:
    """统计信息"""

    def test_initial_stats(self, camera_capture):
        """初始统计应全为 0"""
        stats = camera_capture.get_stats()
        assert stats['frames_captured'] == 0
        assert stats['frames_dropped'] == 0
        assert stats['consecutive_failures'] == 0

    def test_stats_returns_copy(self, camera_capture):
        """get_stats() 应返回副本，外部修改不影响内部状态"""
        stats = camera_capture.get_stats()
        stats['frames_captured'] = 9999
        assert camera_capture.get_stats()['frames_captured'] == 0


# -----------------------------------------------------------------------
# CameraCapture 测试 -- 视频文件源 (T7-02)
# -----------------------------------------------------------------------

class TestCameraCaptureVideoSource:
    """CameraCapture 视频文件输入支持"""

    @pytest.fixture(autouse=True)
    def _bypass_video_validation(self):
        """Bypass _validate_video_path for tests using fake paths (N-P0-1)."""
        with patch('camera_manager._validate_video_path'):
            yield

    def test_is_file_source_true_for_str_device_id(self):
        """device_id 为 str 时 is_file_source 为 True"""
        from camera_manager import CameraCapture
        cam = CameraCapture(device_id='/data/test.mp4')
        assert cam.is_file_source is True

    def test_is_file_source_false_for_int_device_id(self):
        """device_id 为 int 时 is_file_source 为 False"""
        from camera_manager import CameraCapture
        cam = CameraCapture(device_id=0)
        assert cam.is_file_source is False

    def test_open_video_file_does_not_set_buffersize(self, mock_video_cap):
        """打开视频文件时不设置 BUFFERSIZE"""
        from camera_manager import CameraCapture
        with patch('camera_manager.cv2.VideoCapture', return_value=mock_video_cap) as mock_vc:
            cam = CameraCapture(device_id='/data/test.mp4', name='vid')
            cam.open()
            # BUFFERSIZE (38) should NOT be set for file sources
            set_calls = [c for c in mock_video_cap.set.call_args_list
                         if c[0][0] != 38]
            # For video files, only resolution/fps reads happen, no set calls
            # (set is not called at all for file sources)
            cam.close()

    def test_open_video_file_logs_video_info(self, mock_video_cap):
        """打开视频文件时日志包含视频元数据"""
        from camera_manager import CameraCapture
        with patch('camera_manager.cv2.VideoCapture', return_value=mock_video_cap):
            cam = CameraCapture(device_id='/data/test.mp4', name='vid')
            cam.open()
            # Verify video metadata was read (get called with CAP_PROP_FRAME_COUNT=7)
            mock_video_cap.get.assert_any_call(7)
            cam.close()

    def test_name_default_from_video_path(self):
        """CameraManager.add_camera 不指定 name 时，从视频文件路径推导 name"""
        from camera_manager import CameraManager
        mgr = CameraManager()
        cam = mgr.add_camera(device_id='/data/videos/assembly_line.mp4')
        assert cam.name == "Video_assembly_line"

    def test_video_read_failure_does_not_count_dropped(self, mock_video_cap):
        """视频文件 read 失败不记为 frames_dropped"""
        from camera_manager import CameraCapture
        mock_video_cap.read.return_value = (False, None)
        with patch('camera_manager.cv2.VideoCapture', return_value=mock_video_cap):
            cam = CameraCapture(device_id='/data/test.mp4')
            cam.open()
            cam.read()
            assert cam.get_stats()['frames_dropped'] == 0
            assert cam.get_stats()['consecutive_failures'] == 0
            cam.close()

    def test_camera_read_failure_counts_dropped(self, mock_cap):
        """摄像头 read 失败记为 frames_dropped (对比测试)"""
        from camera_manager import CameraCapture
        mock_cap.read.return_value = (False, None)
        with patch('camera_manager.cv2.VideoCapture', return_value=mock_cap):
            cam = CameraCapture(device_id=0)
            cam.open()
            cam.read()
            assert cam.get_stats()['frames_dropped'] == 1
            assert cam.get_stats()['consecutive_failures'] == 1
            cam.close()


class TestCameraCaptureVideoEnd:
    """视频文件结束行为"""

    @pytest.fixture(autouse=True)
    def _bypass_video_validation(self):
        """Bypass _validate_video_path for tests using fake paths (N-P0-1)."""
        with patch('camera_manager._validate_video_path'):
            yield

    def test_video_end_stops_capture_loop(self, mock_video_cap):
        """视频读完时 _capture_loop 停止，不触发重连"""
        import cv2
        from camera_manager import CameraCapture

        # read() returns 2 frames then EOF
        frames = [(True, np.zeros((100, 100, 3), dtype=np.uint8)),
                  (True, np.zeros((100, 100, 3), dtype=np.uint8)),
                  (False, None)]
        mock_video_cap.read.side_effect = frames

        with patch('camera_manager.cv2.VideoCapture', return_value=mock_video_cap):
            cam = CameraCapture(device_id='/data/test.mp4', name='vid', loop=False)
            cam.open()
            # Manually run capture loop
            cam._is_running = True
            cam._capture_loop()
            assert cam.is_running is False
            # Should NOT trigger reconnect
            assert mock_video_cap.release.call_count == 0  # no reconnect attempts
            cam.close()

    def test_video_end_with_loop_restarts(self, mock_video_cap):
        """loop=True 时视频读完触发 CAP_PROP_POS_FRAMES reset"""
        import cv2
        from camera_manager import CameraCapture

        frame = np.zeros((100, 100, 3), dtype=np.uint8)
        reset_count = [0]
        read_count = [0]

        def read_fn():
            """After reset (pos_frames=0), return a frame then EOF again"""
            idx = read_count[0]
            read_count[0] += 1
            if idx == 0:
                return (True, frame)  # first frame
            elif idx == 1:
                return (False, None)  # EOF -> triggers loop reset
            # After reset, if pos_frames was set to 0, return one more frame then stop
            if reset_count[0] > 0 and idx == 2:
                return (True, frame)
            # Stop the loop by setting _is_running to False
            return (False, None)

        mock_video_cap.read.side_effect = read_fn

        def set_fn(prop, value):
            if prop == cv2.CAP_PROP_POS_FRAMES and value == 0:
                reset_count[0] += 1
                # After first reset, let the loop run one more iteration then stop
                if reset_count[0] >= 2:
                    # Force stop on next iteration by making is_opened False
                    mock_video_cap.isOpened.return_value = False

        mock_video_cap.set.side_effect = set_fn

        with patch('camera_manager.cv2.VideoCapture', return_value=mock_video_cap):
            cam = CameraCapture(device_id='/data/test.mp4', name='vid', loop=True)
            cam.open()
            cam._is_running = True
            cam._capture_loop()

            # Verify loop restart happened at least once
            assert reset_count[0] >= 1
            cam.close()

    def test_camera_read_failure_triggers_reconnect(self, mock_cap):
        """摄像头连续读失败触发重连 (对比测试)"""
        from camera_manager import CameraCapture

        # 11 consecutive failures -> triggers disconnect handling
        mock_cap.read.return_value = (False, None)
        with patch('camera_manager.cv2.VideoCapture', return_value=mock_cap):
            cam = CameraCapture(device_id=0, name='cam')
            cam.open()
            cam._is_running = True
            cam._capture_loop()
            # After >10 failures, _handle_disconnect should have been called
            assert cam.get_stats()['consecutive_failures'] > 10
            cam.close()

    def test_read_uses_safe_read_to_avoid_gil_block(self, mock_cap):
        """CameraCapture.read() must use _safe_read so that native C blocking
        I/O (e.g. NTFS 9P mount in Docker/WSL2) can be interrupted by the
        threading timeout -- NOT bare cap.read() which holds the GIL.

        This test simulates a blocking cap.read() that releases the GIL
        (time.sleep) to verify the timeout mechanism fires correctly.
        A real native C read() would hold the GIL and make join() useless;
        _safe_read solves this by running read() in a dedicated thread.
        """
        import time
        from camera_manager import CameraCapture

        blocking_called = {"count": 0}

        def blocking_read():
            blocking_called["count"] += 1
            time.sleep(10)
            return (True, mock_cap.read.return_value[1])

        mock_cap.read.side_effect = blocking_read

        with patch("camera_manager.cv2.VideoCapture", return_value=mock_cap):
            cam = CameraCapture(device_id=0, name="test_gil_cam")
            cam.open()

            start = time.perf_counter()
            ret, frame = cam.read(timeout=0.5)
            elapsed = time.perf_counter() - start

            assert ret is False, "Blocking read should time out and return False"
            assert frame is None
            assert elapsed < 2.0, f"Should return within ~0.5s, took {elapsed:.1f}s"
            assert blocking_called["count"] == 1, "Blocking read was called once before timeout"

            cam.close()


# -----------------------------------------------------------------------
# CameraManager 测试 (T7-03)
# -----------------------------------------------------------------------

class TestCameraManager:
    """CameraManager 多源管理 (str key)"""

    def test_add_camera_returns_capture_instance(self):
        """add_camera() 应返回 CameraCapture 实例"""
        from camera_manager import CameraManager, CameraCapture
        mgr = CameraManager()
        cam = mgr.add_camera(device_id=0)
        assert isinstance(cam, CameraCapture)

    def test_add_same_device_id_returns_same_instance(self):
        """相同 device_id 且未指定 name 时，默认 name 相同，返回同一实例"""
        from camera_manager import CameraManager
        mgr = CameraManager()
        cam1 = mgr.add_camera(device_id=0)
        cam2 = mgr.add_camera(device_id=0)
        assert cam1 is cam2

    def test_get_camera_by_name(self):
        """get_camera(name) 应返回正确的实例"""
        from camera_manager import CameraManager
        mgr = CameraManager()
        mgr.add_camera(device_id=1, name='cam_1')
        assert mgr.get_camera('cam_1') is not None

    def test_get_camera_by_default_name(self):
        """get_camera() 使用自动生成的默认 name"""
        from camera_manager import CameraManager
        mgr = CameraManager()
        cam = mgr.add_camera(device_id=2)
        assert mgr.get_camera('Camera_2') is cam

    def test_get_nonexistent_camera_returns_none(self):
        """get_camera() 查询不存在的 name 应返回 None"""
        from camera_manager import CameraManager
        mgr = CameraManager()
        assert mgr.get_camera('nonexistent') is None

    def test_list_cameras_after_add(self):
        """add_camera() 后 list_cameras() 应包含新增源"""
        from camera_manager import CameraManager
        mgr = CameraManager()
        mgr.add_camera(device_id=0, name='cam_a')
        mgr.add_camera(device_id=1, name='cam_b')
        cameras = mgr.list_cameras()
        assert len(cameras) == 2

    def test_remove_camera_by_name(self):
        """remove_camera(name) 后 get_camera() 应返回 None"""
        from camera_manager import CameraManager
        mgr = CameraManager()
        mgr.add_camera(device_id=0, name='cam_0')
        mgr.remove_camera('cam_0')
        assert mgr.get_camera('cam_0') is None

    def test_detect_cameras_returns_list(self):
        """detect_available_cameras() 应返回列表类型"""
        from camera_manager import CameraManager
        with patch('camera_manager.cv2.VideoCapture') as mock_vc:
            mock_vc.return_value.isOpened.return_value = False
            result = CameraManager.detect_available_cameras(max_devices=3)
        assert isinstance(result, list)


class TestCameraManagerVideoSource:
    """CameraManager 管理视频文件源"""

    @pytest.fixture(autouse=True)
    def _bypass_video_validation(self):
        """Bypass _validate_video_path for tests using fake paths (N-P0-1)."""
        with patch('camera_manager._validate_video_path'):
            yield

    def test_add_video_source(self):
        """add_camera 接受文件路径"""
        from camera_manager import CameraManager, CameraCapture
        mgr = CameraManager()
        cam = mgr.add_camera(device_id='/data/test.mp4', name='vid_0')
        assert isinstance(cam, CameraCapture)
        assert cam.is_file_source is True

    def test_add_video_source_default_name(self):
        """视频文件默认 name 从文件名推导"""
        from camera_manager import CameraManager
        mgr = CameraManager()
        cam = mgr.add_camera(device_id='/data/videos/assembly.mp4')
        assert mgr.get_camera('Video_assembly') is cam

    def test_mixed_sources(self):
        """同时管理摄像头和视频源"""
        from camera_manager import CameraManager
        mgr = CameraManager()
        mgr.add_camera(device_id=0, name='cam_0')
        mgr.add_camera(device_id=1, name='cam_1')
        mgr.add_camera(device_id='/data/test.mp4', name='vid_0')

        cameras = mgr.list_cameras()
        assert len(cameras) == 3

        source_types = {c.source_type for c in cameras}
        assert source_types == {"camera", "camera", "file"}

    def test_get_video_source_by_name(self):
        """通过 name 获取视频源"""
        from camera_manager import CameraManager
        mgr = CameraManager()
        mgr.add_camera(device_id='/data/test.mp4', name='vid_0')
        cam = mgr.get_camera('vid_0')
        assert cam is not None
        assert cam.is_file_source is True

    def test_remove_video_source(self):
        """移除视频源"""
        from camera_manager import CameraManager
        mgr = CameraManager()
        mgr.add_camera(device_id='/data/test.mp4', name='vid_0')
        mgr.remove_camera('vid_0')
        assert mgr.get_camera('vid_0') is None
        assert len(mgr.list_cameras()) == 0


# -----------------------------------------------------------------------
# Direct tests for _validate_video_path (security function)
# These test the real implementation, NOT patched.
# -----------------------------------------------------------------------


class TestValidateVideoPath:
    """_validate_video_path security tests -- no patching, call real logic."""

    def test_reject_empty_string(self):
        """空字符串抛出 ValueError"""
        from camera_manager import _validate_video_path
        with pytest.raises(ValueError, match="non-empty string"):
            _validate_video_path("")

    def test_reject_none(self):
        """None 输入抛出 ValueError"""
        from camera_manager import _validate_video_path
        with pytest.raises(ValueError, match="non-empty string"):
            _validate_video_path(None)

    def test_reject_dotdot_traversal_unix(self):
        """Unix 风格路径穿越 ../ 被拒绝"""
        from camera_manager import _validate_video_path
        with pytest.raises(ValueError, match="Path traversal"):
            _validate_video_path("/data/../etc/passwd.mp4")

    def test_reject_dotdot_traversal_windows(self):
        """Windows 风格路径穿越 ..\\ 被拒绝"""
        from camera_manager import _validate_video_path
        with pytest.raises(ValueError, match="Path traversal"):
            _validate_video_path("C:\\data\\..\\Windows\\System32\\config.mp4")

    def test_reject_dotdot_at_start(self):
        """路径以 .. 开头被拒绝"""
        from camera_manager import _validate_video_path
        with pytest.raises(ValueError, match="Path traversal"):
            _validate_video_path("../../etc/shadow.mp4")

    def test_reject_disallowed_extension(self):
        """非白名单扩展名被拒绝"""
        from camera_manager import _validate_video_path
        with pytest.raises(ValueError, match="Unsupported video extension"):
            _validate_video_path("/data/videos/evil.exe")

    def test_reject_nonexistent_file(self):
        """不存在的文件路径被拒绝"""
        from camera_manager import _validate_video_path
        with pytest.raises(ValueError, match="does not exist"):
            _validate_video_path("/tmp/nonexistent_video_file_abcdef.mp4")

    def test_accept_real_file(self, tmp_path):
        """真实存在的 .mp4 文件通过校验"""
        from camera_manager import _validate_video_path
        video = tmp_path / "test.mp4"
        video.write_bytes(b"\x00" * 16)
        # Should not raise
        _validate_video_path(str(video))
