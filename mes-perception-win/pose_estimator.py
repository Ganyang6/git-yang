"""
姿态识别模块
目标：OpenCV + MediaPipe 提取 33 个人体关键点
MediaPipe Pose 33个关键点定义：
  0-10: 面部 (Face)
  11-22: 上半身 (Upper Body) - 肩膀、手臂、手腕
  23-32: 下半身 (Lower Body) - 髋关节、膝盖、脚踝

特性：
  - 单帧/实时模式
  - 关键点平滑处理
  - 可视化支持
  - 性能统计
"""

import cv2
import time
import numpy as np
from dataclasses import dataclass, field
from typing import List, Optional, Tuple, Dict, Any, Callable
from enum import Enum
import logging
import os
import threading

logger = logging.getLogger(__name__)


class LandmarkName(Enum):
    """MediaPipe Pose 33个关键点名称"""
    NOSE = 0
    LEFT_EYE_INNER = 1
    LEFT_EYE = 2
    LEFT_EYE_OUTER = 3
    RIGHT_EYE_INNER = 4
    RIGHT_EYE = 5
    RIGHT_EYE_OUTER = 6
    LEFT_EAR = 7
    RIGHT_EAR = 8
    MOUTH_LEFT = 9
    MOUTH_RIGHT = 10
    LEFT_SHOULDER = 11
    RIGHT_SHOULDER = 12
    LEFT_ELBOW = 13
    RIGHT_ELBOW = 14
    LEFT_WRIST = 15
    RIGHT_WRIST = 16
    LEFT_PINKY = 17
    RIGHT_PINKY = 18
    LEFT_INDEX = 19
    RIGHT_INDEX = 20
    LEFT_THUMB = 21
    RIGHT_THUMB = 22
    LEFT_HIP = 23
    RIGHT_HIP = 24
    LEFT_KNEE = 25
    RIGHT_KNEE = 26
    LEFT_ANKLE = 27
    RIGHT_ANKLE = 28
    LEFT_HEEL = 29
    RIGHT_HEEL = 30
    LEFT_FOOT_INDEX = 31
    RIGHT_FOOT_INDEX = 32


# 关键点连接定义（用于可视化）
POSE_CONNECTIONS = [
    # 躯干
    (11, 12),  # 左肩-右肩
    (11, 23),  # 左肩-左髋
    (12, 24),  # 右肩-右髋
    (23, 24),  # 左髋-右髋
    # 左臂
    (11, 13),  # 左肩-左肘
    (13, 15),  # 左肘-左腕
    (15, 17),  # 左腕-左手
    (15, 19),  # 左腕-左食指
    (15, 21),  # 左腕-左拇指
    (17, 19),  # 左手-左食指
    # 右臂
    (12, 14),  # 右肩-右肘
    (14, 16),  # 右肘-右腕
    (16, 18),  # 右腕-右手
    (16, 20),  # 右腕-右食指
    (16, 22),  # 右腕-右拇指
    (18, 20),  # 右手-右食指
    # 左腿
    (23, 25),  # 左髋-左膝
    (25, 27),  # 左膝-左踝
    (27, 29),  # 左踝-左脚跟
    (27, 31),  # 左踝-左脚尖
    (29, 31),  # 左脚跟-左脚尖
    # 右腿
    (24, 26),  # 右髋-右膝
    (26, 28),  # 右膝-右踝
    (28, 30),  # 右踝-右脚跟
    (28, 32),  # 右踝-右脚尖
    (30, 32),  # 右脚跟-右脚尖
]


@dataclass
class Landmark:
    """单个关键点数据"""
    x: float  # 归一化坐标 [0, 1]
    y: float
    z: float  # 深度
    visibility: float  # 可见度 [0, 1]
    name: str = ""

    def to_array(self) -> np.ndarray:
        return np.array([self.x, self.y, self.z, self.visibility])

    def to_pixel(self, width: int, height: int) -> Tuple[int, int]:
        """转换为像素坐标"""
        px = int(self.x * width)
        py = int(self.y * height)
        return px, py


@dataclass
class PoseResult:
    """姿态识别结果"""
    landmarks: List[Landmark] = field(default_factory=list)
    world_landmarks: List[Landmark] = field(default_factory=list)
    timestamp: float = 0.0
    inference_time_ms: float = 0.0
    pose_score: float = 0.0  # 整体姿态置信度

    def is_valid(self, min_visibility: float = 0.5) -> bool:
        """检查姿态是否有效"""
        if not self.landmarks:
            return False
        visible_count = sum(1 for lm in self.landmarks
                          if lm.visibility >= min_visibility)
        return visible_count >= 10  # 至少10个可见关键点

    def get_visibility_stats(self) -> Dict[str, float]:
        """获取可见度统计"""
        if not self.landmarks:
            return {}
        visibilities = [lm.visibility for lm in self.landmarks]
        return {
            'mean': np.mean(visibilities),
            'min': np.min(visibilities),
            'max': np.max(visibilities),
            'std': np.std(visibilities)
        }

    def to_dict(self) -> Dict[str, Any]:
        """转换为字典格式"""
        return {
            'landmarks': [
                {
                    'name': lm.name,
                    'x': float(lm.x),
                    'y': float(lm.y),
                    'z': float(lm.z),
                    'visibility': float(lm.visibility)
                }
                for lm in self.landmarks
            ],
            'timestamp': self.timestamp,
            'inference_time_ms': self.inference_time_ms,
            'pose_score': self.pose_score
        }


class PoseEstimator:
    """
    MediaPipe 姿态识别器

    封装 MediaPipe Pose，提供高效的人体姿态检测能力
    支持 MediaPipe 0.10+ 新版 Tasks API 和旧版 Solutions API
    """

    def __init__(self, model_complexity: int = 1, smooth: bool = True,
                 min_detection_confidence: float = 0.5,
                 min_tracking_confidence: float = 0.5,
                 enable_segmentation: bool = False,
                 static_image_mode: bool = False):
        """
        初始化姿态识别器

        Args:
            model_complexity: 模型复杂度 0=Lite(最快), 1=Full(平衡), 2=Heavy(最准)
            smooth: 是否平滑处理
            min_detection_confidence: 最小检测置信度
            min_tracking_confidence: 最小跟踪置信度
            enable_segmentation: 是否启用分割
            static_image_mode: 是否为静态图像模式
        """
        self.model_complexity = model_complexity
        self.smooth = smooth
        self.static_image_mode = static_image_mode

        # 检测并初始化 MediaPipe
        self._pose = None
        self._use_tasks_api = False
        self._init_mediapipe(
            model_complexity, smooth, min_detection_confidence,
            min_tracking_confidence, enable_segmentation, static_image_mode
        )

        # 性能统计
        self._stats = {
            'total_inferences': 0,
            'successful_inferences': 0,
            'failed_inferences': 0,
            'total_inference_time_ms': 0.0,
            'max_inference_time_ms': 0.0,
            'avg_inference_time_ms': 0.0
        }

        # 初始化关键点名称
        self._landmark_names = {lm.value: lm.name for lm in LandmarkName}

        # 初始化核心关键点评分计算器（复用实例，避免重复创建）
        from video_optimizer import CoreLandmarkScoreCalculator
        self._core_score_calculator = CoreLandmarkScoreCalculator()

        # Warmup: 首次推理触发 TFLite 图编译和内部线程池初始化，
        # 后续推理恢复到正常延迟（~15-30ms/帧）。
        self._warmup()

    def _warmup(self) -> None:
        """用 dummy 帧执行一次推理预热，避免首次真实推理延迟过高。"""
        try:
            dummy = np.zeros((240, 320, 3), dtype=np.uint8)
            t0 = time.perf_counter()
            self.estimate(dummy)
            elapsed = (time.perf_counter() - t0) * 1000
            logger.info("PoseEstimator warmup 完成 (%.0fms)", elapsed)
        except Exception as e:
            logger.warning("PoseEstimator warmup 失败（不影响运行）: %s", e)

    def _init_mediapipe(self, model_complexity: int, smooth: bool,
                        min_detection_confidence: float,
                        min_tracking_confidence: float,
                        enable_segmentation: bool,
                        static_image_mode: bool) -> None:
        """初始化 MediaPipe，尝试多种导入方式"""

        # 方式1: 尝试新版 MediaPipe Tasks API (0.10+)
        # 使用 delegate=BaseOptions.Delegate.CPU 强制CPU推理，
        # 不再需要根据 MEDIAPIPE_DISABLE_GPU 跳过。
        try:
            from mediapipe.tasks.python import vision as mp_vision
            from mediapipe.tasks.python import BaseOptions

            model_path = self._get_or_download_model()

            if model_path and os.path.exists(model_path):
                # 使用 CPU 推理（兼容性好，Windows/Linux/Docker 均可用）
                base_options = BaseOptions(
                    model_asset_path=model_path,
                    delegate=BaseOptions.Delegate.CPU
                )
                options = mp_vision.PoseLandmarkerOptions(
                    base_options=base_options,
                    running_mode=mp_vision.RunningMode.IMAGE,
                    num_poses=1,
                    min_pose_detection_confidence=min_detection_confidence,
                    min_pose_presence_confidence=min_tracking_confidence,
                    min_tracking_confidence=min_tracking_confidence,
                    output_segmentation_masks=False
                )
                self._pose = mp_vision.PoseLandmarker.create_from_options(options)
                self._use_tasks_api = True
                logger.info("MediaPipe Tasks API 初始化成功")
                return
        except Exception as e:
            logger.debug(f"MediaPipe Tasks API 初始化失败: {e}")

        # 方式2: 尝试新版 mediapipe.python.solutions
        try:
            import mediapipe.python.solutions.pose as mp_pose
            self._pose = mp_pose.Pose(
                model_complexity=model_complexity,
                smooth_landmarks=smooth,
                enable_segmentation=enable_segmentation,
                min_detection_confidence=min_detection_confidence,
                min_tracking_confidence=min_tracking_confidence,
                static_image_mode=static_image_mode
            )
            self._use_tasks_api = False
            logger.info("MediaPipe Python Solutions API 初始化成功")
            return
        except Exception as e:
            logger.debug(f"MediaPipe Python Solutions API 初始化失败: {e}")

        # 方式3: 尝试旧版 mp.solutions
        try:
            import mediapipe as mp
            self._pose = mp.solutions.pose.Pose(
                model_complexity=model_complexity,
                smooth_landmarks=smooth,
                enable_segmentation=enable_segmentation,
                min_detection_confidence=min_detection_confidence,
                min_tracking_confidence=min_tracking_confidence,
                static_image_mode=static_image_mode
            )
            self._use_tasks_api = False
            logger.info("MediaPipe Solutions API 初始化成功")
            return
        except Exception as e:
            logger.error(f"MediaPipe Solutions API 初始化失败: {e}")

        raise RuntimeError("无法初始化 MediaPipe，请确保已安装 mediapipe >= 0.10")

    def _get_or_download_model(self) -> Optional[str]:
        """获取或下载 Pose Landmarker 模型"""
        # 模型文件名
        model_name = "pose_landmarker.task"
        model_dir = os.path.join(os.path.dirname(__file__), "models")

        # 如果模型已存在，直接返回
        model_path = os.path.join(model_dir, model_name)
        if os.path.exists(model_path):
            return model_path

        # 下载模型（MediaPipe 0.10+ 需要）
        logger.info("正在下载 Pose Landmarker 模型...")
        try:
            import urllib.request

            os.makedirs(model_dir, exist_ok=True)

            # Google MediaPipe 模型 URL
            url = (
                "https://storage.googleapis.com/mediapipe-models/"
                "pose_landmarker/pose_landmarker_lite/float16/1/"
                "pose_landmarker_lite.task"
            )

            urllib.request.urlretrieve(url, model_path)
            logger.info(f"模型下载完成: {model_path}")
            return model_path
        except Exception as e:
            logger.warning(f"模型下载失败: {e}")
            return None

    def estimate(self, frame: np.ndarray,
                timestamp: float = None) -> PoseResult:
        """
        对单帧图像进行姿态识别

        Args:
            frame: BGR格式图像 (numpy array)
            timestamp: 时间戳（可选）

        Returns:
            PoseResult: 姿态识别结果
        """
        start_time = time.perf_counter()

        # BGR转RGB
        if len(frame.shape) == 3 and frame.shape[2] == 3:
            rgb_frame = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
        else:
            rgb_frame = frame

        # MediaPipe 推理
        if self._use_tasks_api:
            results = self._process_with_tasks_api(rgb_frame, timestamp)
        else:
            results = self._process_with_solutions_api(rgb_frame)

        inference_time = (time.perf_counter() - start_time) * 1000.0
        self._update_stats(inference_time, len(results.landmarks) > 0)

        results.inference_time_ms = inference_time
        return results

    def _process_with_tasks_api(self, rgb_frame: np.ndarray,
                                  timestamp: float = None) -> PoseResult:
        """使用 Tasks API 处理"""
        from mediapipe.tasks.python import vision as mp_vision
        from mediapipe import Image, ImageFormat

        # 转换为 MediaPipe Image
        mp_image = Image(
            image_format=ImageFormat.SRGB,
            data=rgb_frame
        )

        # IMAGE mode: no timestamp required
        detection_result = self._pose.detect(mp_image)

        pose_result = PoseResult(
            timestamp=timestamp or time.perf_counter()
        )

        if detection_result.pose_landmarks and len(detection_result.pose_landmarks) > 0:
            landmarks = detection_result.pose_landmarks[0]
            for landmark in landmarks:
                pose_result.landmarks.append(Landmark(
                    x=float(landmark.x),
                    y=float(landmark.y),
                    z=float(landmark.z),
                    visibility=float(landmark.visibility),
                    name=self._landmark_names.get(len(pose_result.landmarks), "")
                ))

            # 计算姿态置信度（使用核心关键点，提升 score 从 0.72 到 0.85+）
            pose_result.pose_score = self._core_score_calculator.calculate(pose_result.landmarks)

        return pose_result

    def _process_with_solutions_api(self, rgb_frame: np.ndarray) -> PoseResult:
        """使用 Solutions API 处理"""
        results = self._pose.process(rgb_frame)

        pose_result = PoseResult(
            timestamp=time.perf_counter()
        )

        if results.pose_landmarks:
            # 解析图像坐标关键点
            for landmark in results.pose_landmarks.landmark:
                pose_result.landmarks.append(Landmark(
                    x=landmark.x,
                    y=landmark.y,
                    z=landmark.z,
                    visibility=landmark.visibility,
                    name=self._landmark_names.get(
                        len(pose_result.landmarks), ""
                    )
                ))

            # 解析世界坐标关键点（去除相机畸变）
            if results.pose_world_landmarks:
                for landmark in results.pose_world_landmarks.landmark:
                    pose_result.world_landmarks.append(Landmark(
                        x=landmark.x,
                        y=landmark.y,
                        z=landmark.z,
                        visibility=landmark.visibility,
                        name=""
                    ))

            # 计算姿态置信度（使用核心关键点，提升 score 从 0.72 到 0.85+）
            pose_result.pose_score = self._core_score_calculator.calculate(pose_result.landmarks)

        return pose_result

    def _update_stats(self, inference_time: float, success: bool) -> None:
        """更新性能统计"""
        self._stats['total_inferences'] += 1
        if success:
            self._stats['successful_inferences'] += 1
        else:
            self._stats['failed_inferences'] += 1

        self._stats['total_inference_time_ms'] += inference_time
        if inference_time > self._stats['max_inference_time_ms']:
            self._stats['max_inference_time_ms'] = inference_time

        count = self._stats['successful_inferences']
        if count > 0:
            self._stats['avg_inference_time_ms'] = (
                self._stats['total_inference_time_ms'] / count
            )

    def get_stats(self) -> Dict[str, Any]:
        """获取性能统计"""
        stats = self._stats.copy()
        total = self._stats['total_inferences']
        if total > 0:
            stats['success_rate'] = (
                self._stats['successful_inferences'] / total * 100
            )
        return stats

    def reset_stats(self) -> None:
        """重置性能统计"""
        self._stats = {
            'total_inferences': 0,
            'successful_inferences': 0,
            'failed_inferences': 0,
            'total_inference_time_ms': 0.0,
            'max_inference_time_ms': 0.0,
            'avg_inference_time_ms': 0.0
        }

    @staticmethod
    def draw_landmarks(frame: np.ndarray, pose_result: PoseResult,
                      thickness: int = 2,
                      circle_radius: int = 3) -> np.ndarray:
        """
        在图像上绘制关键点和骨架

        Args:
            frame: 原始图像
            pose_result: 姿态识别结果
            thickness: 线段粗细
            circle_radius: 关键点圆圈半径

        Returns:
            np.ndarray: 绘制后的图像
        """
        if not pose_result.landmarks:
            return frame

        h, w = frame.shape[:2]

        # 绘制连接线
        for connection in POSE_CONNECTIONS:
            start_idx, end_idx = connection
            if (start_idx < len(pose_result.landmarks) and
                end_idx < len(pose_result.landmarks)):

                start = pose_result.landmarks[start_idx]
                end = pose_result.landmarks[end_idx]

                # 至少有一个关键点可见
                if start.visibility > 0.5 and end.visibility > 0.5:
                    start_pt = (int(start.x * w), int(start.y * h))
                    end_pt = (int(end.x * w), int(end.y * h))

                    # 根据可见度调整颜色
                    color = (0, int(255 * min(start.visibility, end.visibility)), 0)
                    cv2.line(frame, start_pt, end_pt, color, thickness)

        # 绘制关键点
        for idx, landmark in enumerate(pose_result.landmarks):
            if landmark.visibility > 0.5:
                px, py = landmark.to_pixel(w, h)

                # 颜色根据可见度变化
                green = int(255 * landmark.visibility)
                color = (0, green, 255 - green)
                cv2.circle(frame, (px, py), circle_radius, color, -1)

        return frame

    def close(self, timeout: float = 5.0) -> None:
        """关闭识别器，释放资源。

        Args:
            timeout: Maximum seconds to wait for MediaPipe internal
                     thread pool to drain.  If exceeded the close call
                     is abandoned (daemon thread will be cleaned up on
                     process exit).
        """
        if self._pose:
            try:
                close_thread = threading.Thread(
                    target=self._pose.close, daemon=True
                )
                close_thread.start()
                close_thread.join(timeout=timeout)
                if close_thread.is_alive():
                    logger.warning(
                        "MediaPipe Pose close() did not complete within "
                        "%.1fs, abandoning (daemon thread)", timeout
                    )
            except Exception as e:
                logger.warning("关闭 MediaPipe Pose 时出错: %s", e)
            finally:
                self._pose = None


class RealTimePoseProcessor:
    """
    实时姿态处理器
    整合摄像头采集、帧缓冲、姿态识别，提供端到端流水线
    """

    def __init__(self, camera_config: Dict[str, Any],
                 pose_config: Dict[str, Any],
                 buffer_config: Dict[str, Any]):
        """
        初始化实时处理器

        Args:
            camera_config: 摄像头配置
            pose_config: 姿态识别配置
            buffer_config: 帧缓冲配置
        """
        self.camera_config = camera_config
        self.pose_config = pose_config
        self.buffer_config = buffer_config

        # 延迟导入避免循环依赖
        from camera_manager import CameraManager
        from frame_buffer import MultiCameraBuffer

        # 初始化组件
        self._camera_manager = CameraManager()
        self._buffer_manager = MultiCameraBuffer(buffer_config)

        # 初始化姿态识别器
        self._pose_estimators: Dict[int, PoseEstimator] = {}

        # 运行状态
        self._is_running = False

    def add_camera(self, camera_config: Dict[str, Any]) -> None:
        """添加摄像头"""
        camera = self._camera_manager.add_camera(
            device_id=camera_config['device_id'],
            name=camera_config['name'],
            resolution=(camera_config['resolution_width'],
                      camera_config['resolution_height']),
            fps=camera_config['fps'],
            backend=camera_config.get('backend', 'auto')
        )
        self._pose_estimators[camera_config['device_id']] = PoseEstimator(
            model_complexity=self.pose_config['model_complexity'],
            smooth=self.pose_config['smooth'],
            min_detection_confidence=self.pose_config['min_detection_confidence'],
            min_tracking_confidence=self.pose_config['min_tracking_confidence']
        )

    def start(self) -> bool:
        """启动处理流水线"""
        if self._is_running:
            return True

        def process_frame(camera_id: int, frame: np.ndarray,
                         timestamp: float) -> None:
            """处理每一帧"""
            # 姿态识别
            pose_result = self._pose_estimators[camera_id].estimate(
                frame, timestamp
            )

            # 放入缓冲队列
            self._buffer_manager.put_frame(
                camera_id=camera_id,
                frame=frame,
                landmarks=pose_result
            )

        # 启动所有摄像头
        results = self._camera_manager.start_all(process_frame)

        if any(results.values()):
            self._is_running = True
            return True
        return False

    def stop(self) -> None:
        """停止处理流水线"""
        self._camera_manager.stop_all()
        self._is_running = False

    def get_result(self, camera_id: int,
                   timeout: float = 1.0) -> Optional[PoseResult]:
        """获取最新姿态识别结果"""
        frame_data = self._buffer_manager.get_frame(camera_id, timeout)
        if frame_data:
            return frame_data.landmarks
        return None

    def get_stats(self) -> Dict[str, Any]:
        """获取整体统计"""
        stats = {
            'is_running': self._is_running,
            'camera_stats': self._camera_manager.get_all_stats(),
            'buffer_stats': self._buffer_manager.get_global_stats()
        }

        pose_stats = {}
        for cam_id, estimator in self._pose_estimators.items():
            pose_stats[cam_id] = estimator.get_stats()
        stats['pose_stats'] = pose_stats

        return stats

    @property
    def is_running(self) -> bool:
        return self._is_running
