"""
手部识别模块
MediaPipe Hand 21个关键点定义：
  0: WRIST - 手腕
  1-4: THUMB - 拇指 (CMC, MCP, IP, TIP)
  5-8: INDEX_FINGER - 食指 (MCP, PIP, DIP, TIP)
  9-12: MIDDLE_FINGER - 中指 (MCP, PIP, DIP, TIP)
  13-16: RING_FINGER - 无名指 (MCP, PIP, DIP, TIP)
  17-20: PINKY - 小指 (MCP, PIP, DIP, TIP)

特性：
  - 双手检测（左右手分类）
  - 关键点平滑处理
  - 角度特征计算（手指弯曲角度、抓取判断）
  - 可视化支持
"""

import cv2
import time
import numpy as np
from dataclasses import dataclass, field
from typing import List, Optional, Tuple, Dict, Any, Union
from enum import Enum
import logging
import os
import threading

logger = logging.getLogger(__name__)


class HandLandmark(Enum):
    """MediaPipe Hand 21个关键点名称"""
    WRIST = 0
    THUMB_CMC = 1
    THUMB_MCP = 2
    THUMB_IP = 3
    THUMB_TIP = 4
    INDEX_FINGER_MCP = 5
    INDEX_FINGER_PIP = 6
    INDEX_FINGER_DIP = 7
    INDEX_FINGER_TIP = 8
    MIDDLE_FINGER_MCP = 9
    MIDDLE_FINGER_PIP = 10
    MIDDLE_FINGER_DIP = 11
    MIDDLE_FINGER_TIP = 12
    RING_FINGER_MCP = 13
    RING_FINGER_PIP = 14
    RING_FINGER_DIP = 15
    RING_FINGER_TIP = 16
    PINKY_MCP = 17
    PINKY_PIP = 18
    PINKY_DIP = 19
    PINKY_TIP = 20


class HandType(Enum):
    """手型分类"""
    LEFT = "left"
    RIGHT = "right"
    UNKNOWN = "unknown"


# 手部连接定义（用于骨架可视化）
HAND_CONNECTIONS = [
    # 手腕到拇指
    (0, 1), (1, 2), (2, 3), (3, 4),
    # 手腕到食指
    (0, 5),
    (5, 6), (6, 7), (7, 8),
    # 手腕到中指
    (0, 9),
    (9, 10), (10, 11), (11, 12),
    # 手腕到无名指
    (0, 13),
    (13, 14), (14, 15), (15, 16),
    # 手腕到小指
    (0, 17),
    (17, 18), (18, 19), (19, 20),
    # 手掌连接（增加稳定性）
    (5, 9), (9, 13), (13, 17),
]

# 手指关节索引（用于角度计算）
FINGER_JOINTS = {
    'thumb': [1, 2, 3, 4],      # 拇指关节
    'index': [5, 6, 7, 8],      # 食指关节
    'middle': [9, 10, 11, 12],  # 中指关节
    'ring': [13, 14, 15, 16],   # 无名指关节
    'pinky': [17, 18, 19, 20],  # 小指关节
}

# 手指根部索引（用于判断手指是否伸展）
FINGER_BASES = {
    'thumb': 1,
    'index': 5,
    'middle': 9,
    'ring': 13,
    'pinky': 17,
}


@dataclass
class HandLandmarkData:
    """单个手部关键点数据"""
    x: float      # 归一化坐标 [0, 1]
    y: float
    z: float      # 深度
    visibility: float = 1.0  # 可见度
    name: str = ""


@dataclass
class HandResult:
    """单手识别结果"""
    landmarks: List[HandLandmarkData] = field(default_factory=list)
    world_landmarks: List[HandLandmarkData] = field(default_factory=list)
    hand_type: HandType = HandType.UNKNOWN
    timestamp: float = 0.0
    inference_time_ms: float = 0.0

    def is_valid(self, min_visibility: float = 0.5) -> bool:
        """检查手部是否有效"""
        if not self.landmarks:
            return False
        visible_count = sum(1 for lm in self.landmarks
                          if lm.visibility >= min_visibility)
        return visible_count >= 15  # 至少15个可见关键点

    def get_landmark(self, index: int) -> Optional[HandLandmarkData]:
        """获取指定索引的关键点"""
        if 0 <= index < len(self.landmarks):
            return self.landmarks[index]
        return None

    def to_dict(self) -> Dict[str, Any]:
        """转换为字典格式"""
        return {
            'hand_type': self.hand_type.value,
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
            'inference_time_ms': self.inference_time_ms
        }


@dataclass
class HandAngleFeatures:
    """手部角度特征"""
    # 各手指弯曲角度 (0-180度)
    thumb_angle: float = 180.0
    index_angle: float = 180.0
    middle_angle: float = 180.0
    ring_angle: float = 180.0
    pinky_angle: float = 180.0

    # 手掌朝向角度
    palm_pitch: float = 0.0   # 前后倾斜
    palm_yaw: float = 0.0     # 左右偏转
    palm_roll: float = 0.0     # 旋转

    # 抓取相关特征
    grip_strength: float = 0.0    # 抓取强度 0-1
    finger_spread: float = 0.0    # 手指张开程度 0-1
    pinch_distance: float = 1.0   # 拇指-食指距离

    def to_array(self) -> np.ndarray:
        """转换为特征向量"""
        return np.array([
            self.thumb_angle,
            self.index_angle,
            self.middle_angle,
            self.ring_angle,
            self.pinky_angle,
            self.palm_pitch,
            self.palm_yaw,
            self.palm_roll,
            self.grip_strength,
            self.finger_spread,
            self.pinch_distance
        ], dtype=np.float32)

    def to_dict(self) -> Dict[str, float]:
        """转换为字典"""
        return {
            'thumb_angle': self.thumb_angle,
            'index_angle': self.index_angle,
            'middle_angle': self.middle_angle,
            'ring_angle': self.ring_angle,
            'pinky_angle': self.pinky_angle,
            'palm_pitch': self.palm_pitch,
            'palm_yaw': self.palm_yaw,
            'palm_roll': self.palm_roll,
            'grip_strength': self.grip_strength,
            'finger_spread': self.finger_spread,
            'pinch_distance': self.pinch_distance
        }


@dataclass
class DualHandResult:
    """双手识别结果"""
    left_hand: Optional[HandResult] = None
    right_hand: Optional[HandResult] = None
    timestamp: float = 0.0

    def get_hand(self, hand_type: HandType) -> Optional[HandResult]:
        """获取指定手"""
        if hand_type == HandType.LEFT:
            return self.left_hand
        elif hand_type == HandType.RIGHT:
            return self.right_hand
        return None

    def is_valid(self) -> bool:
        """检查是否有有效的手"""
        return (self.left_hand is not None and self.left_hand.is_valid()) or \
               (self.right_hand is not None and self.right_hand.is_valid())


class HandEstimator:
    """
    MediaPipe 手部识别器

    封装 MediaPipe HandLandmarker，提供高效的手部检测能力
    支持 MediaPipe 0.10+ 新版 Tasks API
    """

    def __init__(self, num_hands: int = 2,
                 min_detection_confidence: float = 0.5,
                 min_tracking_confidence: float = 0.5,
                 min_hand_presence_confidence: float = 0.5):
        """
        初始化手部识别器

        Args:
            num_hands: 最大检测手数 (1-2)
            min_detection_confidence: 最小检测置信度
            min_tracking_confidence: 最小跟踪置信度
            min_hand_presence_confidence: 最小手部存在置信度
        """
        self.num_hands = num_hands
        self.min_detection_confidence = min_detection_confidence
        self.min_tracking_confidence = min_tracking_confidence
        self.min_hand_presence_confidence = min_hand_presence_confidence

        # 初始化 MediaPipe
        self._hand_landmarker = None
        self._init_mediapipe()

        # 初始化关键点名称
        self._landmark_names = {lm.value: lm.name for lm in HandLandmark}

        # 性能统计
        self._stats = {
            'total_inferences': 0,
            'successful_inferences': 0,
            'failed_inferences': 0,
            'left_hand_detected': 0,
            'right_hand_detected': 0,
            'both_hands_detected': 0,
        }

        # Warmup: 首次推理触发 TFLite 图编译和内部线程池初始化，
        # 后续推理恢复到正常延迟（~15-30ms/帧）。
        self._warmup()

    def _warmup(self) -> None:
        """用 dummy 帧执行一次推理预热，避免首次真实推理延迟过高。"""
        try:
            dummy = np.zeros((240, 320, 3), dtype=np.uint8)
            t0 = time.perf_counter()
            self.estimate(dummy, timestamp=1.0)
            elapsed = (time.perf_counter() - t0) * 1000
            logger.info("HandEstimator warmup 完成 (%.0fms)", elapsed)
        except Exception as e:
            logger.warning("HandEstimator warmup 失败（不影响运行）: %s", e)

    def _init_mediapipe(self) -> None:
        """初始化 MediaPipe HandLandmarker"""
        try:
            from mediapipe.tasks.python import vision as mp_vision
            from mediapipe.tasks.python import BaseOptions

            # 下载或获取模型文件
            model_path = self._get_or_download_model()

            if model_path and os.path.exists(model_path):
                base_options = BaseOptions(
                    model_asset_path=model_path,
                    delegate=BaseOptions.Delegate.CPU
                )
                options = mp_vision.HandLandmarkerOptions(
                    base_options=base_options,
                    running_mode=mp_vision.RunningMode.VIDEO,
                    num_hands=self.num_hands,
                    min_hand_detection_confidence=self.min_detection_confidence,
                    min_hand_presence_confidence=self.min_hand_presence_confidence,
                    min_tracking_confidence=self.min_tracking_confidence
                )
                self._hand_landmarker = mp_vision.HandLandmarker.create_from_options(options)
                logger.info("MediaPipe HandLandmarker 初始化成功")
            else:
                logger.warning("手部识别模型不存在，将尝试使用备用方案")

        except Exception as e:
            logger.error(f"MediaPipe HandLandmarker 初始化失败: {e}")
            raise RuntimeError(f"无法初始化手部识别器: {e}")

    def _get_or_download_model(self) -> Optional[str]:
        """获取或下载 Hand Landmarker 模型"""
        model_name = "hand_landmarker.task"
        model_dir = os.path.join(os.path.dirname(__file__), "models")

        model_path = os.path.join(model_dir, model_name)
        if os.path.exists(model_path):
            return model_path

        # 下载模型
        logger.info("正在下载 Hand Landmarker 模型...")
        try:
            import urllib.request
            os.makedirs(model_dir, exist_ok=True)

            # MediaPipe 官方模型 URL
            url = (
                "https://storage.googleapis.com/mediapipe-models/"
                "hand_landmarker/hand_landmarker_lite/float16/1/"
                "hand_landmarker_lite.task"
            )

            urllib.request.urlretrieve(url, model_path)
            logger.info(f"模型下载完成: {model_path}")
            return model_path
        except Exception as e:
            logger.warning(f"模型下载失败: {e}")
            return None

    def estimate(self, frame: np.ndarray,
                 timestamp: float = None) -> DualHandResult:
        """
        对单帧图像进行手部识别

        Args:
            frame: BGR格式图像 (numpy array)
            timestamp: 时间戳（可选）

        Returns:
            DualHandResult: 双手识别结果
        """
        start_time = time.perf_counter()

        # BGR转RGB
        if len(frame.shape) == 3 and frame.shape[2] == 3:
            rgb_frame = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
        else:
            rgb_frame = frame

        # 转换为 MediaPipe Image
        from mediapipe import Image, ImageFormat
        mp_image = Image(
            image_format=ImageFormat.SRGB,
            data=rgb_frame
        )

        # 处理
        timestamp_ms = int((timestamp or time.time()) * 1000)
        detection_result = self._hand_landmarker.detect_for_video(
            mp_image, timestamp_ms
        )

        # 解析结果
        dual_result = DualHandResult(
            timestamp=timestamp or time.perf_counter()
        )

        # HandLandmarkerResult 有 hand_landmarks 和 handedness 属性
        if detection_result and \
           hasattr(detection_result, 'hand_landmarks') and \
           detection_result.hand_landmarks and \
           len(detection_result.hand_landmarks) > 0:

            # 获取手型分类
            handedness_list = []
            if hasattr(detection_result, 'handedness') and \
               detection_result.handedness:
                handedness_list = detection_result.handedness

            # 处理每只手的检测结果
            for idx, hand_landmarks in enumerate(detection_result.hand_landmarks):
                if hand_landmarks:
                    hand_result = HandResult(
                        timestamp=dual_result.timestamp
                    )

                    # 从 handedness 获取手型
                    if idx < len(handedness_list):
                        hand_type_str = str(handedness_list[idx])
                        if 'Left' in hand_type_str or 'left' in hand_type_str:
                            hand_result.hand_type = HandType.LEFT
                        elif 'Right' in hand_type_str or 'right' in hand_type_str:
                            hand_result.hand_type = HandType.RIGHT
                        else:
                            hand_result.hand_type = HandType.UNKNOWN
                    else:
                        hand_result.hand_type = self._infer_hand_type(hand_landmarks)

                    # 解析关键点
                    for landmark in hand_landmarks:
                        hand_result.landmarks.append(HandLandmarkData(
                            x=float(landmark.x),
                            y=float(landmark.y),
                            z=float(landmark.z),
                            visibility=1.0,  # Tasks API 不返回 visibility
                            name=self._landmark_names.get(
                                len(hand_result.landmarks), ""
                            )
                        ))

                    # 分配到左右手
                    if hand_result.hand_type == HandType.LEFT:
                        dual_result.left_hand = hand_result
                        self._stats['left_hand_detected'] += 1
                    elif hand_result.hand_type == HandType.RIGHT:
                        dual_result.right_hand = hand_result
                        self._stats['right_hand_detected'] += 1

                    # 更新统计
                    self._update_stats(True)

            if dual_result.left_hand and dual_result.right_hand:
                self._stats['both_hands_detected'] += 1
        else:
            self._update_stats(False)

        inference_time = (time.perf_counter() - start_time) * 1000.0
        for hand_result in [dual_result.left_hand, dual_result.right_hand]:
            if hand_result:
                hand_result.inference_time_ms = inference_time

        return dual_result

    def _infer_hand_type(self, landmarks) -> HandType:
        """
        从关键点推断手型（左手/右手）

        基于手掌朝向和关键点分布判断
        """
        if len(landmarks) < 21:
            return HandType.UNKNOWN

        # 获取手腕和手掌关键点
        wrist = landmarks[0]
        thumb = landmarks[4]
        pinky = landmarks[20]

        # 计算手掌宽度方向
        # 左手：拇指在右侧，小指在左侧
        # 右手：拇指在左侧，小指在右侧
        thumb_x = thumb.x
        pinky_x = pinky.x

        if thumb_x < pinky_x:
            return HandType.LEFT
        else:
            return HandType.RIGHT

    def _update_stats(self, success: bool) -> None:
        """更新性能统计"""
        self._stats['total_inferences'] += 1
        if success:
            self._stats['successful_inferences'] += 1
        else:
            self._stats['failed_inferences'] += 1

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
            'left_hand_detected': 0,
            'right_hand_detected': 0,
            'both_hands_detected': 0,
        }

    def close(self, timeout: float = 5.0) -> None:
        """关闭识别器，释放资源。

        Args:
            timeout: Maximum seconds to wait for MediaPipe internal
                     thread pool to drain.  If exceeded the close call
                     is abandoned (daemon thread will be cleaned up on
                     process exit).
        """
        if self._hand_landmarker:
            try:
                close_thread = threading.Thread(
                    target=self._hand_landmarker.close, daemon=True
                )
                close_thread.start()
                close_thread.join(timeout=timeout)
                if close_thread.is_alive():
                    logger.warning(
                        "MediaPipe HandLandmarker close() did not complete "
                        "within %.1fs, abandoning (daemon thread)", timeout
                    )
            except Exception as e:
                logger.warning("关闭 MediaPipe HandLandmarker 时出错: %s", e)
            finally:
                self._hand_landmarker = None


class HandAngleCalculator:
    """手部角度特征计算器"""

    @staticmethod
    def calculate_angle(p1: Tuple[float, float, float],
                        p2: Tuple[float, float, float],
                        p3: Tuple[float, float, float]) -> float:
        """
        计算三个点形成的角度（以p2为顶点）

        Args:
            p1, p2, p3: 三维坐标点

        Returns:
            角度（度，0-180）
        """
        # 向量
        v1 = np.array([p1[0] - p2[0], p1[1] - p2[1], p1[2] - p2[2]])
        v2 = np.array([p3[0] - p2[0], p3[1] - p2[1], p3[2] - p2[2]])

        # 计算夹角
        cos_angle = np.dot(v1, v2) / (np.linalg.norm(v1) * np.linalg.norm(v2) + 1e-6)
        cos_angle = np.clip(cos_angle, -1.0, 1.0)
        angle = np.arccos(cos_angle) * 180.0 / np.pi

        return float(angle)

    @staticmethod
    def calculate_finger_angle(landmarks: List[HandLandmarkData],
                               finger_name: str) -> float:
        """
        计算手指弯曲角度

        基于相邻关节计算弯曲程度
        """
        joints = FINGER_JOINTS.get(finger_name, [])
        if len(joints) < 3:
            return 180.0

        if finger_name == 'thumb':
            # 拇指使用不同关节组合
            base_idx = joints[0]
            mid_idx = joints[1]
            tip_idx = joints[2]
        else:
            # 其他手指：MCP -> PIP -> DIP -> TIP
            base_idx = joints[0]
            mid_idx = joints[1]
            tip_idx = joints[2]

        if max(base_idx, mid_idx, tip_idx) >= len(landmarks):
            return 180.0

        p1 = (landmarks[base_idx].x, landmarks[base_idx].y, landmarks[base_idx].z)
        p2 = (landmarks[mid_idx].x, landmarks[mid_idx].y, landmarks[mid_idx].z)
        p3 = (landmarks[tip_idx].x, landmarks[tip_idx].y, landmarks[tip_idx].z)

        return HandAngleCalculator.calculate_angle(p1, p2, p3)

    @staticmethod
    def calculate_palm_orientation(landmarks: List[HandLandmarkData]) -> Tuple[float, float, float]:
        """
        计算手掌朝向

        Returns:
            (pitch, yaw, roll) - 前后倾斜、左右偏转、旋转角度
        """
        if len(landmarks) < 21:
            return (0.0, 0.0, 0.0)

        # 使用手腕和手掌关键点计算
        wrist = landmarks[0]
        index_mcp = landmarks[5]
        pinky_mcp = landmarks[17]

        # 计算手掌法向量（近似）
        # 使用手腕到中指方向作为手掌朝向
        middle_mcp = landmarks[9]

        # Pitch（前后倾斜）- 基于 y 坐标变化
        pitch = np.arctan2(middle_mcp.y - wrist.y, 1.0 - wrist.z) * 180.0 / np.pi

        # Yaw（左右偏转）- 基于 x 坐标
        yaw = np.arctan2(middle_mcp.x - wrist.x, 1.0 - wrist.z) * 180.0 / np.pi

        # Roll（旋转）- 基于手掌宽度方向
        dx = pinky_mcp.x - index_mcp.x
        dy = pinky_mcp.y - index_mcp.y
        roll = np.arctan2(dy, dx) * 180.0 / np.pi

        return (float(pitch), float(yaw), float(roll))

    @staticmethod
    def calculate_grip_strength(hand_result: HandResult) -> float:
        """
        计算抓取强度

        基于手指弯曲程度综合判断
        """
        if not hand_result.landmarks or len(hand_result.landmarks) < 21:
            return 0.0

        fingers = ['index', 'middle', 'ring', 'pinky']
        angles = []

        for finger in fingers:
            angle = HandAngleCalculator.calculate_finger_angle(
                hand_result.landmarks, finger
            )
            # 角度越小，弯曲程度越大，抓取强度越高
            grip_contribution = 1.0 - (angle / 180.0)
            angles.append(grip_contribution)

        # 平均抓取强度
        return float(np.mean(angles))

    @staticmethod
    def calculate_finger_spread(hand_result: HandResult) -> float:
        """
        计算手指张开程度

        基于指尖到手腕的距离判断
        """
        if not hand_result.landmarks or len(hand_result.landmarks) < 21:
            return 0.0

        wrist = hand_result.landmarks[0]
        wrist_pos = np.array([wrist.x, wrist.y])

        # 计算各指尖到手腕的距离
        finger_tips = [
            hand_result.landmarks[4],   # 拇指尖
            hand_result.landmarks[8],  # 食指尖
            hand_result.landmarks[12], # 中指尖
            hand_result.landmarks[16], # 无名指尖
            hand_result.landmarks[20], # 小指尖
        ]

        distances = []
        max_dist = 0.0

        for tip in finger_tips:
            if tip:
                tip_pos = np.array([tip.x, tip.y])
                dist = np.linalg.norm(tip_pos - wrist_pos)
                distances.append(dist)
                max_dist = max(max_dist, dist)

        if max_dist > 0:
            # 归一化
            spread = np.mean([d / max_dist for d in distances])
            return float(spread)

        return 0.0

    @staticmethod
    def calculate_pinch_distance(hand_result: HandResult) -> float:
        """
        计算拇指-食指捏取距离

        Returns:
            归一化距离（0-1），越小表示捏取越紧
        """
        if not hand_result.landmarks or len(hand_result.landmarks) < 21:
            return 1.0

        thumb_tip = hand_result.landmarks[4]
        index_tip = hand_result.landmarks[8]

        if thumb_tip and index_tip:
            dist = np.sqrt(
                (thumb_tip.x - index_tip.x) ** 2 +
                (thumb_tip.y - index_tip.y) ** 2 +
                (thumb_tip.z - index_tip.z) ** 2
            )
            return float(np.clip(dist, 0.0, 1.0))

        return 1.0

    @staticmethod
    def extract_features(hand_result: HandResult) -> HandAngleFeatures:
        """
        提取完整的手部角度特征

        Args:
            hand_result: 手部识别结果

        Returns:
            HandAngleFeatures: 角度特征
        """
        if not hand_result.landmarks or len(hand_result.landmarks) < 21:
            return HandAngleFeatures()

        features = HandAngleFeatures()

        # 手指弯曲角度
        fingers = ['thumb', 'index', 'middle', 'ring', 'pinky']
        for finger in fingers:
            angle = HandAngleCalculator.calculate_finger_angle(
                hand_result.landmarks, finger
            )
            if finger == 'thumb':
                features.thumb_angle = angle
            elif finger == 'index':
                features.index_angle = angle
            elif finger == 'middle':
                features.middle_angle = angle
            elif finger == 'ring':
                features.ring_angle = angle
            elif finger == 'pinky':
                features.pinky_angle = angle

        # 手掌朝向
        pitch, yaw, roll = HandAngleCalculator.calculate_palm_orientation(
            hand_result.landmarks
        )
        features.palm_pitch = pitch
        features.palm_yaw = yaw
        features.palm_roll = roll

        # 抓取特征
        features.grip_strength = HandAngleCalculator.calculate_grip_strength(hand_result)
        features.finger_spread = HandAngleCalculator.calculate_finger_spread(hand_result)
        features.pinch_distance = HandAngleCalculator.calculate_pinch_distance(hand_result)

        return features


def draw_hand_landmarks(frame: np.ndarray,
                        hand_result: HandResult,
                        color: Tuple[int, int, int] = (0, 255, 0),
                        thickness: int = 2,
                        circle_radius: int = 3) -> np.ndarray:
    """
    在图像上绘制手部关键点和骨架

    Args:
        frame: 原始图像
        hand_result: 手部识别结果
        color: 绘制颜色
        thickness: 线段粗细
        circle_radius: 关键点圆圈半径

    Returns:
        np.ndarray: 绘制后的图像
    """
    if not hand_result.landmarks or len(hand_result.landmarks) < 21:
        return frame

    h, w = frame.shape[:2]

    # 绘制连接线
    for connection in HAND_CONNECTIONS:
        start_idx, end_idx = connection
        if start_idx < len(hand_result.landmarks) and \
           end_idx < len(hand_result.landmarks):

            start = hand_result.landmarks[start_idx]
            end = hand_result.landmarks[end_idx]

            start_pt = (int(start.x * w), int(start.y * h))
            end_pt = (int(end.x * w), int(end.y * h))

            cv2.line(frame, start_pt, end_pt, color, thickness)

    # 绘制关键点
    for idx, landmark in enumerate(hand_result.landmarks):
        px = int(landmark.x * w)
        py = int(landmark.y * h)

        # 手腕用特殊颜色
        if idx == 0:
            cv2.circle(frame, (px, py), circle_radius + 1, (0, 0, 255), -1)
        # 指尖用另一种颜色
        elif idx in [4, 8, 12, 16, 20]:
            cv2.circle(frame, (px, py), circle_radius + 1, (255, 0, 0), -1)
        else:
            cv2.circle(frame, (px, py), circle_radius, color, -1)

    # 标注手型
    hand_label = hand_result.hand_type.value.upper()
    if hand_result.landmarks:
        wrist = hand_result.landmarks[0]
        label_pt = (int(wrist.x * w), int(wrist.y * h) - 20)
        cv2.putText(frame, hand_label, label_pt,
                   cv2.FONT_HERSHEY_SIMPLEX, 0.7, color, 2)

    return frame


def draw_hand_features(frame: np.ndarray,
                      features: HandAngleFeatures,
                      position: Tuple[int, int] = (10, 30),
                      color: Tuple[int, int, int] = (255, 255, 255)) -> np.ndarray:
    """
    在图像上绘制手部角度特征信息

    Args:
        frame: 原始图像
        features: 角度特征
        position: 文本起始位置
        color: 文本颜色

    Returns:
        np.ndarray: 绘制后的图像
    """
    h, w = frame.shape[:2]

    lines = [
        f"Hand Features:",
        f"  Thumb: {features.thumb_angle:.1f}deg",
        f"  Index: {features.index_angle:.1f}deg",
        f"  Middle: {features.middle_angle:.1f}deg",
        f"  Ring: {features.ring_angle:.1f}deg",
        f"  Pinky: {features.pinky_angle:.1f}deg",
        f"  Grip: {features.grip_strength:.2f}",
        f"  Spread: {features.finger_spread:.2f}",
    ]

    y_offset = position[1]
    for line in lines:
        cv2.putText(frame, line, (position[0], y_offset),
                   cv2.FONT_HERSHEY_SIMPLEX, 0.5, color, 1)
        y_offset += 20

    return frame


# 导出所有类和常量
__all__ = [
    'HandLandmark',
    'HandLandmarkData',
    'HandResult',
    'HandAngleFeatures',
    'DualHandResult',
    'HandType',
    'HandEstimator',
    'HandAngleCalculator',
    'HAND_CONNECTIONS',
    'FINGER_JOINTS',
    'draw_hand_landmarks',
    'draw_hand_features',
]
