"""
SystemConfig 单元测试
覆盖：默认值、YAML 加载、缺失文件降级、字段类型验证
"""

import pytest
from pathlib import Path


class TestSystemConfigDefaults:
    """默认配置值验证"""

    def test_num_landmarks_is_33(self, system_config):
        """MediaPipe 标准关键点数量必须是 33"""
        assert system_config.performance.num_landmarks == 33

    def test_target_fps_is_30(self, system_config):
        """默认目标帧率应为 30"""
        assert system_config.performance.target_fps == 30

    def test_max_latency_ms_positive(self, system_config):
        """最大延迟阈值必须大于 0"""
        assert system_config.performance.max_latency_ms > 0

    def test_pose_model_complexity_valid_range(self, system_config):
        """model_complexity 只能是 0、1、2"""
        assert system_config.pose.model_complexity in (0, 1, 2)

    def test_pose_confidence_range(self, system_config):
        """置信度阈值必须在 0~1 之间"""
        assert 0.0 <= system_config.pose.min_detection_confidence <= 1.0
        assert 0.0 <= system_config.pose.min_tracking_confidence <= 1.0

    def test_buffer_max_queue_size_positive(self, system_config):
        """缓冲队列最大容量必须大于 0"""
        assert system_config.buffer.max_queue_size > 0

    def test_cameras_list_type(self, system_config):
        """cameras 字段必须是列表"""
        assert isinstance(system_config.cameras, list)


class TestLoadConfig:
    """load_config() 函数行为"""

    def test_load_nonexistent_returns_default(self):
        """加载不存在的文件应返回默认配置而非抛出异常"""
        from config import load_config
        config = load_config('totally_nonexistent_file_xyz.yaml')
        assert config is not None
        assert config.performance.num_landmarks == 33

    def test_load_existing_config(self, tmp_path):
        """加载合法 YAML 文件应正确覆盖默认值"""
        from config import load_config
        yaml_content = """
pose:
  model_complexity: 2
  min_detection_confidence: 0.7
"""
        config_file = tmp_path / 'test_config.yaml'
        config_file.write_text(yaml_content, encoding='utf-8')

        config = load_config(str(config_file))
        assert config.pose.model_complexity == 2
        assert config.pose.min_detection_confidence == pytest.approx(0.7)

    def test_load_partial_config_keeps_defaults(self, tmp_path):
        """只覆盖部分字段时，未覆盖字段应保持默认值"""
        from config import load_config
        yaml_content = """
pose:
  model_complexity: 0
"""
        config_file = tmp_path / 'partial.yaml'
        config_file.write_text(yaml_content, encoding='utf-8')

        config = load_config(str(config_file))
        assert config.pose.model_complexity == 0
        # 未覆盖的字段保持默认
        assert config.performance.num_landmarks == 33

    def test_load_invalid_yaml_returns_default(self, tmp_path):
        """加载格式错误的 YAML 应降级返回默认配置"""
        from config import load_config
        config_file = tmp_path / 'bad.yaml'
        config_file.write_text(': invalid: yaml: content: [', encoding='utf-8')

        config = load_config(str(config_file))
        assert config is not None


class TestCameraConfig:
    """CameraConfig 数据类"""

    def test_camera_config_defaults(self):
        """CameraConfig 默认值应合理"""
        from config import CameraConfig
        cam = CameraConfig(device_id=0)
        assert cam.device_id == 0
        assert cam.enabled is True
        assert cam.fps > 0
        assert cam.resolution_width > 0
        assert cam.resolution_height > 0

    def test_camera_config_name_fallback(self):
        """未指定 name 时应自动生成"""
        from config import CameraConfig
        cam = CameraConfig(device_id=2)
        assert cam.name  # 不能为空字符串


class TestPoseConfig:
    """PoseConfig 数据类"""

    def test_pose_config_smooth_default(self):
        """smooth 默认应为 True"""
        from config import PoseConfig
        pose = PoseConfig()
        assert pose.smooth is True

    def test_pose_config_complexity_default(self):
        """默认 model_complexity 应为 1（平衡精度与速度）"""
        from config import PoseConfig
        pose = PoseConfig()
        assert pose.model_complexity == 1


class TestHandEstimationConfig:
    """HandEstimationConfig 数据类"""

    def test_hand_estimation_config_defaults(self):
        """HandEstimationConfig 默认值：enabled=False, num_hands=2"""
        from config import HandEstimationConfig
        hand_cfg = HandEstimationConfig()
        assert hand_cfg.enabled is False
        assert hand_cfg.num_hands == 2
        assert hand_cfg.min_detection_confidence == pytest.approx(0.5)
        assert hand_cfg.min_tracking_confidence == pytest.approx(0.5)

    def test_hand_estimation_config_custom(self):
        """HandEstimationConfig 支持自定义参数"""
        from config import HandEstimationConfig
        hand_cfg = HandEstimationConfig(
            enabled=True,
            num_hands=1,
            min_detection_confidence=0.7,
            min_tracking_confidence=0.6,
        )
        assert hand_cfg.enabled is True
        assert hand_cfg.num_hands == 1
        assert hand_cfg.min_detection_confidence == pytest.approx(0.7)
        assert hand_cfg.min_tracking_confidence == pytest.approx(0.6)


class TestLoadConfigHandEstimation:
    """load_config() 解析 hand_estimation 配置段"""

    def test_hand_estimation_default_disabled(self, system_config):
        """默认配置 hand_estimation.enabled 应为 False（向后兼容）"""
        assert system_config.hand_estimation.enabled is False

    def test_load_hand_estimation_enabled(self, tmp_path):
        """YAML 中设置 hand_estimation.enabled=true 应正确解析"""
        from config import load_config
        yaml_content = """
hand_estimation:
  enabled: true
  num_hands: 1
  min_detection_confidence: 0.6
  min_tracking_confidence: 0.4
"""
        config_file = tmp_path / 'test_hand.yaml'
        config_file.write_text(yaml_content, encoding='utf-8')
        config = load_config(str(config_file))
        assert config.hand_estimation.enabled is True
        assert config.hand_estimation.num_hands == 1
        assert config.hand_estimation.min_detection_confidence == pytest.approx(0.6)
        assert config.hand_estimation.min_tracking_confidence == pytest.approx(0.4)

    def test_load_hand_estimation_partial_keeps_defaults(self, tmp_path):
        """只设置 enabled=true 时，其余字段保持默认值"""
        from config import load_config
        yaml_content = """
hand_estimation:
  enabled: true
"""
        config_file = tmp_path / 'partial_hand.yaml'
        config_file.write_text(yaml_content, encoding='utf-8')
        config = load_config(str(config_file))
        assert config.hand_estimation.enabled is True
        assert config.hand_estimation.num_hands == 2
        assert config.hand_estimation.min_detection_confidence == pytest.approx(0.5)
