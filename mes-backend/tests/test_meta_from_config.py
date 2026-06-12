"""验证 meta 配置来自 config.yaml 而非硬编码。

RED 阶段：MetaConfig 和 app.meta 均未实现，测试应因 AttributeError 失败。
GREEN 阶段：实现 app.meta 配置加载后测试通过。
"""
from app.core.config import load_app_config


def test_meta_values_from_config():
    """meta 的 shifts/mod_unit/thresholds 应从 config 读取"""
    cfg = load_app_config()
    assert hasattr(cfg, 'meta'), "AppConfig 应包含 meta 字段"
    assert hasattr(cfg.meta, 'mod_unit'), "MetaConfig 应包含 mod_unit"
    assert cfg.meta.mod_unit == 0.129
    assert hasattr(cfg.meta, 'shifts')
    assert len(cfg.meta.shifts) == 3
    assert cfg.meta.shifts[0]["value"] == "morning"
    assert cfg.meta.shifts[0]["label"] == "早班"
    assert hasattr(cfg.meta, 'thresholds')
    assert cfg.meta.thresholds["efficiency"]["normal_min"] == 90


def test_meta_default_allowance_rate():
    """default_allowance_rate 应从 config 读取"""
    cfg = load_app_config()
    assert cfg.meta.default_allowance_rate == 15
