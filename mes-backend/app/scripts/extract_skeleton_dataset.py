"""
ST-GCN 骨架数据集提取脚本

从 ProcessSegment 数据库记录 + 视频文件 提取骨架序列数据集。
目标格式: (N, C, T, V, M) 适配 ST-GCN
  N: 样本数
  C: 特征维度 (x, y, confidence) = 3
  T: 时序长度 (padding/truncate 到固定长度)
  V: 关键点数 (MediaPipe 33)
  M: 人数 (1)

使用方式:
  python app/scripts/extract_skeleton_dataset.py
"""

from __future__ import annotations

import json
import logging
import os
import sqlite3
from collections import Counter, defaultdict
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Tuple

import numpy as np

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
)
logger = logging.getLogger(__name__)

# ─── 常量 ───────────────────────────────────────────────────────────

PROJECT_ROOT = os.path.dirname(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
)

# 确保 MediaPipe C++ 共享库的依赖可解析
_USER_LIB_DIR = os.path.expanduser("~/.local/lib")
if os.path.isdir(_USER_LIB_DIR):
    _current_ld = os.environ.get("LD_LIBRARY_PATH", "")
    if _USER_LIB_DIR not in _current_ld:
        os.environ["LD_LIBRARY_PATH"] = f"{_USER_LIB_DIR}:{_current_ld}" if _current_ld else _USER_LIB_DIR

# DB 路径（按优先顺序）
DB_CANDIDATES = [
    os.path.join(PROJECT_ROOT, "data", "mes.db"),
    os.path.join(PROJECT_ROOT, "app", "data", "mes.db"),
]

# 视频目录（项目级，非 mes-backend 级）
# 主视频库: PROJECT_ROOT/data/videos/  (存放实际采集的视频)
# mes-backend 测试视频: PROJECT_ROOT/mes-backend/data/videos/  (存放 test_e2e.mp4 等)
VIDEO_DIR = os.path.join(os.path.dirname(PROJECT_ROOT), "data", "videos")
if not os.path.isdir(VIDEO_DIR):
    VIDEO_DIR = os.path.join(PROJECT_ROOT, "data", "videos")
logger.info("视频目录: %s", VIDEO_DIR)

# ST-GCN 参数
ST_GCN_FIXED_T = 64        # 时序长度（padding/truncate）
ST_GCN_NUM_JOINTS = 33     # MediaPipe Pose landmarks
ST_GCN_CHANNELS = 3        # x, y, confidence
ST_GCN_MAX_PEOPLE = 1      # 单人场景

MEDIAPIPE_LANDMARK_NAMES = [
    "nose", "left_eye_inner", "left_eye", "left_eye_outer",
    "right_eye_inner", "right_eye", "right_eye_outer",
    "left_ear", "right_ear", "mouth_left", "mouth_right",
    "left_shoulder", "right_shoulder", "left_elbow", "right_elbow",
    "left_wrist", "right_wrist", "left_pinky", "right_pinky",
    "left_index", "right_index", "left_thumb", "right_thumb",
    "left_hip", "right_hip", "left_knee", "right_knee",
    "left_ankle", "right_ankle", "left_heel", "right_heel",
    "left_foot_index", "right_foot_index",
]

# ST-GCN 骨架边定义（MediaPipe 拓扑）
# 每条边 (from, to) 使用 landmark index
ST_GCN_EDGES = [
    # 躯干
    (11, 12),  # 左右肩膀
    (11, 23),  # 左肩 → 左髋
    (12, 24),  # 右肩 → 右髋
    (23, 24),  # 左右髋
    # 左臂
    (11, 13), (13, 15),  # shoulder → elbow → wrist
    (15, 17), (15, 19), (15, 21),  # wrist → pinky/index/thumb
    # 右臂
    (12, 14), (14, 16),
    (16, 18), (16, 20), (16, 22),
    # 左腿
    (23, 25), (25, 27),  # hip → knee → ankle
    (27, 29), (27, 31),  # ankle → heel/foot_index
    # 右腿
    (24, 26), (26, 28),
    (28, 30), (28, 32),
    # 面部
    (0, 1), (1, 2), (2, 3), (3, 7),     # nose → left eye chain
    (0, 4), (4, 5), (5, 6), (6, 8),     # nose → right eye chain
    (9, 10),                              # mouth corners
    (0, 9), (0, 10),                      # nose → mouth
]

NUM_EDGES = len(ST_GCN_EDGES)

# ─── 数据库连接 ──────────────────────────────────────────────────────


def find_db() -> Optional[str]:
    """查找可用的 mes.db 文件。"""
    for path in DB_CANDIDATES:
        if os.path.isfile(path):
            return path
    return None


# ─── Step 1: 分析 ProcessSegment ────────────────────────────────────


def analyze_process_segments(db_path: str) -> dict:
    """分析 process_segments 表结构及数据分布。"""
    conn = sqlite3.connect(db_path)
    c = conn.cursor()

    # 表结构
    c.execute("PRAGMA table_info(process_segments)")
    columns = [r[1] for r in c.fetchall()]
    logger.info("ProcessSegment 字段 (%d): %s", len(columns), columns)

    # 总行数
    c.execute("SELECT COUNT(*) FROM process_segments")
    total = c.fetchone()[0]
    logger.info("总行数: %d", total)

    # 动作分布
    c.execute("""
        SELECT action, COUNT(*) as cnt
        FROM process_segments
        WHERE action IS NOT NULL AND action != ''
        GROUP BY action
        ORDER BY cnt DESC
    """)
    action_dist = {row[0]: row[1] for row in c.fetchall()}
    logger.info("动作类别分布 (%d 种):", len(action_dist))
    for action, cnt in sorted(action_dist.items(), key=lambda x: -x[1]):
        logger.info("  %s: %d 条", action, cnt)

    # Therblig 符号分布
    c.execute("""
        SELECT therblig_symbol, COUNT(*) as cnt
        FROM process_segments
        WHERE therblig_symbol IS NOT NULL AND therblig_symbol != ''
        GROUP BY therblig_symbol
        ORDER BY cnt DESC
    """)
    therblig_dist = {row[0]: row[1] for row in c.fetchall()}
    logger.info("Therblig 符号分布 (%d 种):", len(therblig_dist))
    for sym, cnt in sorted(therblig_dist.items(), key=lambda x: -x[1]):
        logger.info("  %s: %d 条", sym, cnt)

    # 是否有动作但无符号
    c.execute("""
        SELECT COUNT(*) FROM process_segments
        WHERE action IS NOT NULL AND action != ''
          AND (therblig_symbol IS NULL OR therblig_symbol = '')
    """)
    no_symbol = c.fetchone()[0]
    if no_symbol > 0:
        logger.info("%d 条有动作但无 Therblig 符号", no_symbol)

    # 工站分布
    c.execute("""
        SELECT station_id, COUNT(*) as cnt
        FROM process_segments
        GROUP BY station_id
        ORDER BY cnt DESC
    """)
    station_dist = {row[0]: row[1] for row in c.fetchall()}
    if station_dist:
        logger.info("工站分布: %s", station_dist)

    conn.close()

    return {
        "total": total,
        "columns": columns,
        "action_distribution": action_dist,
        "therblig_distribution": therblig_dist,
        "stations": station_dist,
    }


# ─── Step 2: 从视频提取骨架序列 ──────────────────────────────────────


def _get_pose_model_path() -> str:
    """Return local pose landmarker model path, downloading if necessary."""
    model_name = "pose_landmarker_lite.task"
    model_dir = os.path.join(PROJECT_ROOT, "models")
    os.makedirs(model_dir, exist_ok=True)
    model_path = os.path.join(model_dir, model_name)
    if not os.path.exists(model_path):
        model_url = (
            "https://storage.googleapis.com/mediapipe-models/"
            "pose_landmarker/pose_landmarker_lite/float16/latest/"
            "pose_landmarker_lite.task"
        )
        logger.info("下载 Pose Landmarker 模型从 %s ...", model_url)
        import urllib.request
        urllib.request.urlretrieve(model_url, model_path)
        logger.info("模型下载至 %s", model_path)
    return model_path


def extract_skeleton_from_video(
    video_path: str,
    max_frames: int = 300,
) -> Optional[np.ndarray]:
    """
    从视频文件提取骨架序列。

    使用 OpenCV + MediaPipe PoseLandmarker (Tasks API) 逐帧提取 Landmarks，
    输出形状 (T, V, C) 其中:
      T: 帧数
      V: 33 (MediaPipe landmarks)
      C: 3 (x, y, visibility)

    Args:
        video_path: 视频文件路径
        max_frames: 最大提取帧数

    Returns:
        (T, V, C) numpy 数组，若失败则返回 None
    """
    try:
        import cv2
        from mediapipe.tasks.python import BaseOptions
        from mediapipe.tasks.python import vision as mp_vision
        from mediapipe import Image as MpImage, ImageFormat
    except ImportError:
        logger.error("需要安装 opencv-python 和 mediapipe")
        return None

    logger.info("处理视频: %s", os.path.basename(video_path))

    cap = cv2.VideoCapture(video_path)
    if not cap.isOpened():
        logger.error("无法打开视频: %s", video_path)
        return None

    total_frames = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
    fps = cap.get(cv2.CAP_PROP_FPS)
    logger.info("  总帧数: %d, FPS: %.1f", total_frames, fps)

    # MediaPipe Pose Landmarker (Tasks API)
    model_path = _get_pose_model_path()
    options = mp_vision.PoseLandmarkerOptions(
        base_options=BaseOptions(model_asset_path=model_path),
        running_mode=mp_vision.RunningMode.VIDEO,
        min_pose_detection_confidence=0.5,
        min_tracking_confidence=0.5,
        num_poses=1,
    )
    landmarker = mp_vision.PoseLandmarker.create_from_options(options)

    # 采样策略：如果视频过长，均匀采样 max_frames 帧
    if total_frames > max_frames:
        sample_indices = set(
            np.linspace(0, total_frames - 1, max_frames, dtype=int)
        )
    else:
        sample_indices = None

    frames: List[np.ndarray] = []
    frame_count = 0
    timestamp_ms = 0

    # 采样策略：如果视频过长，均匀采样 max_frames 帧
    if total_frames > max_frames:
        sample_indices = set(
            np.linspace(0, total_frames - 1, max_frames, dtype=int)
        )
    else:
        sample_indices = None

    while True:
        ret, frame_bgr = cap.read()
        if not ret:
            break

        # 采样
        if sample_indices is not None and frame_count not in sample_indices:
            frame_count += 1
            timestamp_ms += int(1000 / fps)
            continue

        frame_rgb = cv2.cvtColor(frame_bgr, cv2.COLOR_BGR2RGB)
        mp_image = MpImage(image_format=ImageFormat.SRGB, data=frame_rgb)
        results = landmarker.detect_for_video(mp_image, timestamp_ms)

        if results.pose_landmarks:
            # 提取 (V, 3): x, y, visibility
            frame_data = np.zeros((33, 3), dtype=np.float32)
            landmarks = results.pose_landmarks[0]  # 取第一个 (也是唯一) 人体
            for i, lm in enumerate(landmarks):
                frame_data[i, 0] = lm.x
                frame_data[i, 1] = lm.y
                frame_data[i, 2] = lm.visibility  # 旧版 visibility 不可用，用 presence_score
            frames.append(frame_data)
        else:
            # 填充零
            frames.append(np.zeros((33, 3), dtype=np.float32))

        frame_count += 1
        timestamp_ms += int(1000 / fps)

        if len(frames) >= max_frames:
            break

    cap.release()
    landmarker.close()

    if not frames:
        logger.warning("  未检测到任何骨架")
        return None

    skeleton = np.stack(frames, axis=0)  # (T, V, C)
    logger.info("  提取完成: %d 帧骨架", skeleton.shape[0])
    return skeleton


def process_all_videos(
    video_dir: str = VIDEO_DIR,
    output_dir: str = "data/skeleton",
    max_frames_per_video: int = 300,
) -> Dict[str, np.ndarray]:
    """
    批量处理 videos/ 目录下的所有视频，提取骨架序列。

    Args:
        video_dir: 视频目录
        output_dir: 骨架输出目录
        max_frames_per_video: 每个视频最大帧数

    Returns:
        {filename: skeleton_array} 字典
    """
    supported_exts = {".mp4", ".avi", ".mov", ".mkv"}
    video_files = [
        f for f in os.listdir(video_dir)
        if os.path.splitext(f)[1].lower() in supported_exts
    ]

    if not video_files:
        logger.warning("视频目录下没有视频文件: %s", video_dir)
        return {}

    logger.info("找到 %d 个视频文件", len(video_files))

    output_path = os.path.join(PROJECT_ROOT, output_dir)
    os.makedirs(output_path, exist_ok=True)

    results = {}
    for vf in sorted(video_files):
        vpath = os.path.join(video_dir, vf)
        skeleton = extract_skeleton_from_video(vpath, max_frames_per_video)
        if skeleton is not None:
            basename = os.path.splitext(vf)[0]
            npy_path = os.path.join(output_path, f"{basename}_skeleton.npy")
            np.save(npy_path, skeleton)
            logger.info("  保存骨架: %s (%s)", npy_path, skeleton.shape)
            results[vf] = skeleton

    logger.info("共处理 %d/%d 个视频", len(results), len(video_files))
    return results


# ─── Step 3: 骨架序列 → ST-GCN 格式 ─────────────────────────────────


def skeleton_to_stgcn(
    skeleton: np.ndarray,
    target_t: int = ST_GCN_FIXED_T,
    normalize: bool = True,
) -> np.ndarray:
    """
    将 (T, V, C) 骨架序列转换为 (C, T, V, 1) ST-GCN 格式。

    ST-GCN 期望输入: (N, C, T, V, M)
      单样本: (1, C, T, V, 1) → squeeze → (C, T, V, 1)

    Args:
        skeleton: (T, V, C) 源骨架序列
        target_t: 目标时序长度
        normalize: 是否归一化坐标

    Returns:
        (C, T, V, 1) ndarray
    """
    T, V, C = skeleton.shape

    # 归一化: 将 x, y 缩放到 [0, 1]
    if normalize:
        skel = skeleton.copy()
        # x: 相对躯干中心偏移
        hip_center = (skel[:, 23, :2] + skel[:, 24, :2]) / 2  # (T, 2)
        skel[:, :, :2] -= hip_center[:, np.newaxis, :]
        # 用肩宽做尺度归一化
        shoulder_width = np.linalg.norm(
            skel[:, 11, :2] - skel[:, 12, :2], axis=1, keepdims=True
        )  # (T, 1)
        shoulder_width = np.clip(shoulder_width, 0.01, None)
        skel[:, :, :2] /= shoulder_width[:, np.newaxis, :]
    else:
        skel = skeleton

    # 时序 padding / truncate
    if T >= target_t:
        # 均匀采样 target_t 帧
        indices = np.linspace(0, T - 1, target_t, dtype=int)
        skel = skel[indices]
    else:
        # padding: 复制最后一帧
        pad_len = target_t - T
        pad = np.tile(skel[-1:], (pad_len, 1, 1))
        skel = np.concatenate([skel, pad], axis=0)

    # 转置: (T, V, C) → (C, T, V)
    stgcn = np.transpose(skel, (2, 0, 1))  # (3, 64, 33)

    # 添加人数维度
    stgcn = stgcn[:, :, :, np.newaxis]  # (C, T, V, 1)

    return stgcn


def build_stgcn_dataset(
    skeleton_files: List[str],
    labels: Dict[str, str],
    output_npz: str = "data/skeleton/stgcn_dataset.npz",
) -> Optional[Tuple[np.ndarray, np.ndarray, Dict[int, str]]]:
    """
    从骨架文件构建完整 ST-GCN 数据集。

    Args:
        skeleton_files: .npy 骨架文件路径列表
        labels: {filename: action_label} 映射
        output_npz: 输出 .npz 路径

    Returns:
        (X, y, class_mapping) 元组
    """
    X_list = []
    y_list = []
    classes = set()

    for npy_path in skeleton_files:
        basename = os.path.splitext(os.path.basename(npy_path))[0]
        # 去掉 _skeleton 后缀
        video_name = basename.replace("_skeleton", "")
        label = labels.get(video_name)
        if label is None:
            logger.warning("跳过 %s: 无标签", video_name)
            continue

        skeleton = np.load(npy_path)
        stgcn_sample = skeleton_to_stgcn(skeleton)
        X_list.append(stgcn_sample)
        classes.add(label)

    if not X_list:
        logger.error("无有效样本")
        return None

    # 类别编码
    sorted_classes = sorted(classes)
    class_to_idx = {c: i for i, c in enumerate(sorted_classes)}
    idx_to_class = {i: c for i, c in enumerate(sorted_classes)}

    X = np.stack(X_list, axis=0)  # (N, C, T, V, 1)
    y = np.array([class_to_idx[labels[os.path.splitext(os.path.basename(p))[0].replace("_skeleton", "")]] for p in skeleton_files if os.path.splitext(os.path.basename(p))[0].replace("_skeleton", "") in labels], dtype=np.int64)

    # 修正：对齐 X 和 y
    y_list_clean = []
    for i, npy_path in enumerate(skeleton_files):
        basename = os.path.splitext(os.path.basename(npy_path))[0]
        video_name = basename.replace("_skeleton", "")
        label = labels.get(video_name)
        if label is not None:
            y_list_clean.append(class_to_idx[label])

    X = np.stack(X_list, axis=0)
    y = np.array(y_list_clean, dtype=np.int64)

    # 保存
    abs_output = os.path.join(PROJECT_ROOT, output_npz)
    os.makedirs(os.path.dirname(abs_output), exist_ok=True)
    np.savez_compressed(abs_output, X=X, y=y)

    logger.info("数据集保存至: %s", abs_output)
    logger.info("  样本数: %d", X.shape[0])
    logger.info("  格式: %s", X.shape)
    logger.info("  类别数: %d", len(sorted_classes))
    for c, idx in class_to_idx.items():
        count = int((y == idx).sum())
        logger.info("    [%d] %s: %d 样本", idx, c, count)

    return X, y, idx_to_class


# ─── 主入口 ──────────────────────────────────────────────────────────


def main():
    """主流程：分析现有数据 + 处理视频 + 生成 ST-GCN 数据集。"""
    logger.info("=" * 60)
    logger.info("ST-GCN 骨架数据集提取")
    logger.info("=" * 60)

    # ── A. 数据库分析 ──
    logger.info("\n[Step A] 分析 ProcessSegment 数据库")
    db_path = find_db()
    if db_path:
        logger.info("数据库: %s", db_path)
        stats = analyze_process_segments(db_path)

        # 若数据库有数据，输出各动作段的时间跨度
        if stats["total"] > 0:
            conn = sqlite3.connect(db_path)
            c = conn.cursor()
            c.execute("""
                SELECT id, action, start_time, end_time, duration_ms, confidence
                FROM process_segments
                WHERE action IS NOT NULL AND action != ''
                ORDER BY start_time
                LIMIT 10
            """)
            logger.info("前 10 个动作段:")
            for row in c.fetchall():
                logger.info("  #%d %s | %.1fs-%.1fs | dur=%.0fms | conf=%.2f",
                           row[0], row[1], row[2], row[3], row[4], row[5])
            conn.close()
        else:
            logger.warning("数据库为空 — 没有已标注的动作段可用于训练")
    else:
        logger.warning("未找到 mes.db 文件")
        stats = {"total": 0, "action_distribution": {}}

    # ── B. 视频骨架提取 ──
    logger.info("\n[Step B] 从视频提取骨架序列")
    skeleton_results = process_all_videos()

    # ── C. 统计与下一步规划 ──
    logger.info("\n" + "=" * 60)
    logger.info("阶段 1 总结")
    logger.info("=" * 60)

    logger.info("数据库状态:")
    logger.info("  ProcessSegment 行数: %d", stats.get("total", 0))
    if stats.get("action_distribution"):
        for action, cnt in sorted(stats["action_distribution"].items(),
                                  key=lambda x: -x[1]):
            logger.info("    %s: %d", action, cnt)

    logger.info("视频骨架:")
    logger.info("  视频文件数: %d",
                len([f for f in os.listdir(VIDEO_DIR)
                     if os.path.isfile(os.path.join(VIDEO_DIR, f))
                     and not f.startswith(".")]))
    logger.info("  成功提取: %d 个视频", len(skeleton_results))

    if skeleton_results:
        total_frames = sum(s.shape[0] for s in skeleton_results.values())
        logger.info("  总骨架帧数: %d", total_frames)

    logger.info("\n下一步计划:")
    logger.info("  1. 如果数据库为空，需要先通过摄像头或视频回放录入动作数据")
    logger.info("  2. 安装 ST-GCN: pip install torch torchvision")
    logger.info("  3. 下载 ST-GCN 预训练权重 (NTU RGB+D)")
    logger.info("  4. 训练/微调 ST-GCN 模型")
    logger.info("  5. 替换/扩展现有 ONNX 分类器")


if __name__ == "__main__":
    main()
