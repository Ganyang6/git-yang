"""
感知底座配置管理
配置驱动：统一管理摄像头参数、姿态识别参数、帧缓冲参数
"""

from dataclasses import dataclass, field
from typing import List, Optional
import yaml
from pathlib import Path


@dataclass
class CameraConfig:
    """单摄像头/视频源配置"""
    device_id: int = 0
    name: str = "Camera_0"
    enabled: bool = True
    resolution_width: int = 1280
    resolution_height: int = 720
    fps: int = 30
    backend: str = "auto"  # auto, V4L2, MSMF, GSTREAMER
    video_path: Optional[str] = None  # video file path (mp4/avi/mov/mkv); overrides device_id
    station_id: str = "WS-01"  # station ID for Redis Stream publishing
    loop: bool = False  # loop video playback

    @property
    def source_type(self) -> str:
        """Return 'file' if video_path is set, otherwise 'camera'."""
        return "file" if self.video_path else "camera"

    @property
    def source(self) -> object:
        """Return the actual source for cv2.VideoCapture: file path or device_id."""
        return self.video_path if self.video_path else self.device_id


@dataclass
class PoseConfig:
    """姿态识别配置"""
    model_complexity: int = 1  # 0=Lite, 1=Full, 2=Heavy
    smooth: bool = True
    enable_segmentation: bool = False
    min_detection_confidence: float = 0.5
    min_tracking_confidence: float = 0.5
    static_image_mode: bool = False


@dataclass
class BufferConfig:
    """帧缓冲配置"""
    max_queue_size: int = 10
    drop_old_frames: bool = True  # True=丢弃旧帧保证实时性


@dataclass
class PerformanceConfig:
    """性能目标配置"""
    target_fps: int = 30
    max_latency_ms: float = 33.0
    num_landmarks: int = 33  # MediaPipe 33个关键点


@dataclass
class HandEstimationConfig:
    """手部识别配置"""
    enabled: bool = False  # 默认关闭，向后兼容
    num_hands: int = 2  # 最大检测手数 (1-2)
    min_detection_confidence: float = 0.5
    min_tracking_confidence: float = 0.5


@dataclass
class SystemConfig:
    """系统配置"""
    cameras: List[CameraConfig] = field(default_factory=list)
    pose: PoseConfig = field(default_factory=PoseConfig)
    hand_estimation: HandEstimationConfig = field(default_factory=HandEstimationConfig)
    buffer: BufferConfig = field(default_factory=BufferConfig)
    performance: PerformanceConfig = field(default_factory=PerformanceConfig)


def load_config(config_path: str = "config.yaml") -> SystemConfig:
    """从YAML文件加载配置，解析失败时返回默认配置"""
    import logging
    path = Path(config_path)
    if not path.exists():
        return SystemConfig()

    try:
        with open(path, 'r', encoding='utf-8') as f:
            data = yaml.safe_load(f)
    except yaml.YAMLError as exc:
        logging.warning("配置文件解析失败，使用默认配置: %s", exc)
        return SystemConfig()

    config = SystemConfig()

    # 解析摄像头配置
    if 'cameras' in data:
        for cam_data in data['cameras']:
            camera = CameraConfig(
                device_id=cam_data.get('device_id', 0),
                name=cam_data.get('name', 'Camera'),
                enabled=cam_data.get('enabled', True),
                resolution_width=cam_data.get('resolution_width', 1280),
                resolution_height=cam_data.get('resolution_height', 720),
                fps=cam_data.get('fps', 30),
                backend=cam_data.get('backend', 'auto'),
                video_path=cam_data.get('video_path', None),
                station_id=cam_data.get('station_id', 'WS-01'),
                loop=cam_data.get('loop', False),
            )
            config.cameras.append(camera)

    # 解析姿态配置
    if 'pose' in data:
        pose_data = data['pose']
        config.pose = PoseConfig(
            model_complexity=pose_data.get('model_complexity', 1),
            smooth=pose_data.get('smooth', True),
            enable_segmentation=pose_data.get('enable_segmentation', False),
            min_detection_confidence=pose_data.get('min_detection_confidence', 0.5),
            min_tracking_confidence=pose_data.get('min_tracking_confidence', 0.5),
            static_image_mode=pose_data.get('static_image_mode', False)
        )

    # 解析手部识别配置
    if 'hand_estimation' in data:
        hand_data = data['hand_estimation']
        num_hands = hand_data.get('num_hands', 2)
        if not 1 <= num_hands <= 2:
            logging.warning("num_hands must be 1-2, got %d, clamping to 2", num_hands)
            num_hands = 2
        config.hand_estimation = HandEstimationConfig(
            enabled=hand_data.get('enabled', False),
            num_hands=num_hands,
            min_detection_confidence=hand_data.get('min_detection_confidence', 0.5),
            min_tracking_confidence=hand_data.get('min_tracking_confidence', 0.5),
        )

    # 解析缓冲配置
    if 'buffer' in data:
        buffer_data = data['buffer']
        config.buffer = BufferConfig(
            max_queue_size=buffer_data.get('max_queue_size', 10),
            drop_old_frames=buffer_data.get('drop_old_frames', True)
        )

    # 解析性能配置
    if 'performance' in data:
        perf_data = data['performance']
        config.performance = PerformanceConfig(
            target_fps=perf_data.get('target_fps', 30),
            max_latency_ms=perf_data.get('max_latency_ms', 33.0),
            num_landmarks=perf_data.get('num_landmarks', 33)
        )

    return config


def save_config(config: SystemConfig, config_path: str = "config.yaml") -> None:
    """保存配置到YAML文件"""
    data = {
        'cameras': [
            {
                'device_id': cam.device_id,
                'name': cam.name,
                'enabled': cam.enabled,
                'resolution_width': cam.resolution_width,
                'resolution_height': cam.resolution_height,
                'fps': cam.fps,
                'backend': cam.backend,
                'video_path': cam.video_path,
                'station_id': cam.station_id,
                'loop': cam.loop,
            }
            for cam in config.cameras
        ],
        'pose': {
            'model_complexity': config.pose.model_complexity,
            'smooth': config.pose.smooth,
            'enable_segmentation': config.pose.enable_segmentation,
            'min_detection_confidence': config.pose.min_detection_confidence,
            'min_tracking_confidence': config.pose.min_tracking_confidence,
            'static_image_mode': config.pose.static_image_mode
        },
        'buffer': {
            'max_queue_size': config.buffer.max_queue_size,
            'drop_old_frames': config.buffer.drop_old_frames
        },
        'performance': {
            'target_fps': config.performance.target_fps,
            'max_latency_ms': config.performance.max_latency_ms,
            'num_landmarks': config.performance.num_landmarks
        },
        'hand_estimation': {
            'enabled': config.hand_estimation.enabled,
            'num_hands': config.hand_estimation.num_hands,
            'min_detection_confidence': config.hand_estimation.min_detection_confidence,
            'min_tracking_confidence': config.hand_estimation.min_tracking_confidence,
        }
    }

    with open(config_path, 'w', encoding='utf-8') as f:
        yaml.dump(data, f, allow_unicode=True, default_flow_style=False)
