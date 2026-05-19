"""
手部识别测试脚本
演示手部特征点和角度特征功能
"""

import cv2
import numpy as np
import time
from hand_estimator import (
    HandEstimator,
    HandAngleCalculator,
    HandAngleFeatures,
    DualHandResult,
    draw_hand_landmarks,
    draw_hand_features
)


def create_test_hand_frame():
    """创建模拟手部帧用于测试"""
    frame = np.full((480, 640, 3), 255, dtype=np.uint8)
    cv2.putText(frame, "Hand Detection Test", (200, 50),
               cv2.FONT_HERSHEY_SIMPLEX, 1, (0, 0, 0), 2)
    cv2.putText(frame, "No hand detected (blank frame)",
               (180, 240), cv2.FONT_HERSHEY_SIMPLEX, 0.8, (128, 128, 128), 1)
    return frame


def test_hand_estimator():
    """测试手部识别器"""
    print("=" * 60)
    print("手部识别模块测试")
    print("=" * 60)

    # 初始化手部识别器
    print("\n[1] 初始化 HandEstimator...")
    estimator = HandEstimator(num_hands=2)
    print("    HandEstimator 初始化成功")

    # 测试空帧
    print("\n[2] 测试空帧（无手检测）...")
    blank_frame = np.zeros((480, 640, 3), dtype=np.uint8)
    result = estimator.estimate(blank_frame)
    print(f"    检测结果: 左手={result.left_hand is not None}, "
          f"右手={result.right_hand is not None}")

    # 获取统计
    stats = estimator.get_stats()
    print(f"    总推理次数: {stats['total_inferences']}")
    print(f"    成功率: {stats['success_rate']:.1f}%")

    # 测试角度计算
    print("\n[3] 测试角度特征计算...")
    test_features = test_angle_calculation()
    print(f"    拇指角度: {test_features.thumb_angle:.1f}度")
    print(f"    食指角度: {test_features.index_angle:.1f}度")
    print(f"    抓取强度: {test_features.grip_strength:.2f}")

    # 清理
    estimator.close()
    print("\n[4] 资源清理完成")

    print("\n" + "=" * 60)
    print("测试完成!")
    print("=" * 60)


def test_angle_calculation():
    """测试角度计算功能"""
    from dataclasses import dataclass, field
    from typing import List

    @dataclass
    class MockLandmark:
        x: float
        y: float
        z: float

    @dataclass
    class MockHandResult:
        landmarks: List = field(default_factory=list)

    # 创建张开手掌的模拟数据
    mock_result = MockHandResult()

    # 手腕
    wrist = MockLandmark(0.5, 0.5, 0.0)
    # 拇指
    thumb = [
        MockLandmark(0.45, 0.48, 0.0),   # CMC
        MockLandmark(0.42, 0.45, 0.0),   # MCP
        MockLandmark(0.40, 0.42, 0.0),   # IP
        MockLandmark(0.38, 0.40, 0.0),   # TIP
    ]
    # 食指
    index = [
        MockLandmark(0.42, 0.35, 0.0),   # MCP
        MockLandmark(0.42, 0.28, 0.0),   # PIP
        MockLandmark(0.42, 0.22, 0.0),   # DIP
        MockLandmark(0.42, 0.15, 0.0),   # TIP
    ]
    # 中指
    middle = [
        MockLandmark(0.50, 0.33, 0.0),   # MCP
        MockLandmark(0.50, 0.26, 0.0),   # PIP
        MockLandmark(0.50, 0.20, 0.0),   # DIP
        MockLandmark(0.50, 0.14, 0.0),   # TIP
    ]
    # 无名指
    ring = [
        MockLandmark(0.58, 0.35, 0.0),   # MCP
        MockLandmark(0.58, 0.28, 0.0),   # PIP
        MockLandmark(0.58, 0.22, 0.0),   # DIP
        MockLandmark(0.58, 0.16, 0.0),   # TIP
    ]
    # 小指
    pinky = [
        MockLandmark(0.65, 0.38, 0.0),   # MCP
        MockLandmark(0.65, 0.32, 0.0),   # PIP
        MockLandmark(0.65, 0.28, 0.0),   # DIP
        MockLandmark(0.65, 0.24, 0.0),   # TIP
    ]

    # 组装关键点
    landmarks = [wrist] + thumb + index + middle + ring + pinky

    # 转换为 HandAngleCalculator 期望的格式
    from hand_estimator import HandLandmarkData

    class SimpleHandResult:
        def __init__(self, lms):
            self.landmarks = [
                HandLandmarkData(x=lm.x, y=lm.y, z=lm.z)
                for lm in lms
            ]

    simple_result = SimpleHandResult(landmarks)
    features = HandAngleCalculator.extract_features(simple_result)

    return features


def print_hand_features(features: HandAngleFeatures):
    """打印手部角度特征"""
    print("\n手部角度特征:")
    print("-" * 40)
    print(f"  手指弯曲角度:")
    print(f"    拇指: {features.thumb_angle:.1f}度")
    print(f"    食指: {features.index_angle:.1f}度")
    print(f"    中指: {features.middle_angle:.1f}度")
    print(f"    无名指: {features.ring_angle:.1f}度")
    print(f"    小指: {features.pinky_angle:.1f}度")
    print(f"  手掌朝向:")
    print(f"    Pitch: {features.palm_pitch:.1f}度")
    print(f"    Yaw: {features.palm_yaw:.1f}度")
    print(f"    Roll: {features.palm_roll:.1f}度")
    print(f"  抓取特征:")
    print(f"    抓取强度: {features.grip_strength:.2f}")
    print(f"    手指张开: {features.finger_spread:.2f}")
    print(f"    捏取距离: {features.pinch_distance:.3f}")
    print("-" * 40)


if __name__ == "__main__":
    test_hand_estimator()
