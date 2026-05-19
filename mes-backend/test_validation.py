"""
感知底座验收测试脚本
验证所有功能模块是否满足验收标准

验收标准：
  1. 单摄像头稳定跑 30 FPS
  2. 33 个关键点坐标实时输出到内存队列
  3. 端到端延迟 < 33ms
"""

import sys
import time
import logging
import unittest
from pathlib import Path
import numpy as np

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s [%(levelname)s] %(message)s'
)
logger = logging.getLogger(__name__)


class TestFrameBuffer(unittest.TestCase):
    """帧缓冲队列测试"""

    def setUp(self):
        from frame_buffer import FrameBuffer
        self.buffer = FrameBuffer(max_size=5, drop_old=True)

    def test_put_get(self):
        """测试基本存取"""
        frame = np.zeros((480, 640, 3), dtype=np.uint8)
        result = self.buffer.put(frame)
        self.assertIsNotNone(result)
        self.assertEqual(result.frame_id, 1)

    def test_full_queue_drop_old(self):
        """测试队列满时丢弃旧帧"""
        frame = np.zeros((100, 100, 3), dtype=np.uint8)
        for i in range(10):
            self.buffer.put(frame)

        self.assertEqual(self.buffer.size, 5)
        stats = self.buffer.get_stats()
        self.assertGreater(stats['dropped_frames'], 0)

    def test_latency_calculation(self):
        """测试延迟计算"""
        frame = np.zeros((100, 100, 3), dtype=np.uint8)
        frame_data = self.buffer.put(frame)
        time.sleep(0.01)  # 10ms
        latency = self.buffer.calculate_latency(frame_data)
        self.assertGreater(latency, 0)
        self.assertLess(latency, 100)  # 应该在100ms内


class TestCameraManager(unittest.TestCase):
    """摄像头管理测试"""

    def test_detect_cameras(self):
        """测试摄像头检测"""
        from camera_manager import CameraManager
        cameras = CameraManager.detect_available_cameras(max_devices=3)
        logger.info(f"检测到 {len(cameras)} 个摄像头")
        self.assertIsInstance(cameras, list)


class TestPoseEstimator(unittest.TestCase):
    """姿态识别测试"""

    def setUp(self):
        from pose_estimator import PoseEstimator
        self.estimator = PoseEstimator(model_complexity=1, smooth=True)

    def test_landmark_count(self):
        """测试关键点数量"""
        from pose_estimator import LandmarkName
        self.assertEqual(len(LandmarkName), 33)

    def test_estimate_with_blank_frame(self):
        """测试空白帧处理"""
        blank_frame = np.zeros((480, 640, 3), dtype=np.uint8)
        result = self.estimator.estimate(blank_frame)
        # 空白帧可能检测不到人，但不应报错
        self.assertIsNotNone(result)
        self.assertIsInstance(result.is_valid(), bool)

    def tearDown(self):
        self.estimator.close()


class TestConfig(unittest.TestCase):
    """配置管理测试"""

    def test_default_config(self):
        """测试默认配置"""
        from config import SystemConfig, load_config
        config = SystemConfig()
        self.assertEqual(config.performance.num_landmarks, 33)
        self.assertEqual(config.performance.target_fps, 30)

    def test_load_nonexistent_config(self):
        """测试加载不存在的配置文件"""
        from config import load_config
        config = load_config('nonexistent.yaml')
        self.assertIsNotNone(config)


def run_integration_test():
    """
    集成测试：端到端验证

    注意：需要实际摄像头才能运行完整测试
    """
    from camera_manager import CameraManager
    from pose_estimator import PoseEstimator
    from frame_buffer import FrameBuffer

    logger.info("=" * 50)
    logger.info("开始集成测试")
    logger.info("=" * 50)

    # 检测摄像头
    cameras = CameraManager.detect_available_cameras(max_devices=3)
    if not cameras:
        logger.warning("未检测到摄像头，跳过集成测试")
        return False

    camera_id = cameras[0]
    logger.info(f"使用摄像头 {camera_id}")

    # 创建组件
    camera_manager = CameraManager()
    camera = camera_manager.add_camera(device_id=camera_id)
    pose_estimator = PoseEstimator()
    frame_buffer = FrameBuffer()

    try:
        if not camera.open():
            logger.error("无法打开摄像头")
            return False

        # 测试采集和处理
        frame_count = 0
        fps_list = []
        latency_list = []
        landmarks_list = []

        test_duration = 5  # 5秒测试
        start_time = time.perf_counter()
        last_report = start_time

        logger.info(f"运行 {test_duration} 秒测试...")

        while time.perf_counter() - start_time < test_duration:
            ret, frame = camera.read()  # 使用公共 read() 方法，不直接访问 _cap
            if not ret:
                continue

            timestamp = time.perf_counter()

            # 姿态识别
            pose_result = pose_estimator.estimate(frame, timestamp)

            # 放入缓冲
            frame_data = frame_buffer.put(frame, pose_result, camera_id)

            if frame_data:
                latency = frame_buffer.calculate_latency(frame_data)
                latency_list.append(latency)
                landmarks_list.append(len(pose_result.landmarks))

            frame_count += 1

            # 每秒报告一次
            if time.perf_counter() - last_report >= 1.0:
                elapsed = time.perf_counter() - start_time
                current_fps = frame_count / elapsed if elapsed > 0 else 0
                fps_list.append(current_fps)
                frame_count = 0
                last_report = time.perf_counter()

        # 结果分析
        avg_fps = np.mean(fps_list) if fps_list else 0
        avg_latency = np.mean(latency_list) if latency_list else 0
        avg_landmarks = np.mean(landmarks_list) if landmarks_list else 0

        logger.info("=" * 50)
        logger.info("集成测试结果")
        logger.info("=" * 50)
        logger.info(f"平均 FPS: {avg_fps:.2f}")
        logger.info(f"平均延迟: {avg_latency:.2f}ms")
        logger.info(f"平均检测关键点数: {avg_landmarks:.1f}/33")

        # 验收标准检查
        fps_pass = avg_fps >= 28
        latency_pass = avg_latency < 33
        landmarks_pass = avg_landmarks >= 30

        logger.info("-" * 50)
        logger.info(f"FPS >= 28: {'通过' if fps_pass else '未通过'}")
        logger.info(f"延迟 < 33ms: {'通过' if latency_pass else '未通过'}")
        logger.info(f"关键点 >= 30: {'通过' if landmarks_pass else '未通过'}")
        logger.info("=" * 50)

        return fps_pass and latency_pass and landmarks_pass

    finally:
        camera.close()
        pose_estimator.close()


if __name__ == '__main__':
    logger.info("感知底座验收测试")
    logger.info("=" * 50)

    # 运行单元测试
    logger.info("运行单元测试...")
    unittest.main(exit=False, verbosity=2)

    # 尝试运行集成测试
    logger.info("")
    logger.info("尝试运行集成测试...")
    try:
        success = run_integration_test()
        sys.exit(0 if success else 1)
    except Exception as e:
        logger.error(f"集成测试出错: {e}")
        sys.exit(1)
