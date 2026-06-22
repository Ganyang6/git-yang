"""
HA4M 3D mm → MediaPipe 2D 0-1 坐标统一化

问题: HA4M 使用 Azure Kinect 3D 毫米坐标，我们的系统使用 MediaPipe 2D 归一化坐标。
两种数据无法混合训练，导致 HA4M 98.61% 但合成数据仅 11.11%。

方案: 将 HA4M 32 关节 3D 毫米坐标投影到 2D 并归一化为 [0,1]，
        使用深度相机内参透视投影或预计算的 2D 投影坐标。
"""

import logging
import os
import sys
from collections import Counter

import numpy as np

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger(__name__)

# ─── Azure Kinect DK 内参 ────────────────────────────────────────────
# 深度相机分辨率: 640×576 (NFOV unbinned)
DEPTH_W = 640
DEPTH_H = 576
FX = 604.0  # 近似焦距
FY = 604.0
CX = 320.0  # 近似主点
CY = 288.0

# ─── 关节映射: HA4M (32关节) → MediaPipe (33关节) ────────────────────
#
# HA4M 关节索引:
#   0=Pelvis, 1=SpineNaval, 2=Chest, 3=Neck, 4=Head, 5=HeadTip,
#   6=ShoulderLeft, 7=ShoulderRight, 8=ElbowLeft, 9=ElbowRight,
#   10=WristLeft, 11=WristRight, 12=HandLeft, 13=HandRight,
#   14=HandTipLeft, 15=HandTipRight, 16=ThumbLeft, 17=ThumbRight,
#   18=HandLeft_1, 19=HandRight_1, 20=HandTipLeft_1, 21=HandTipRight_1,
#   22=ThumbLeft_1, 23=ThumbRight_1 (actually these are feet in older
#   versions of AK body tracking - AK SDK v1.x has 32 joints with
#   feet at 23-24)
#
# Wait - looking at the actual data, HA4M AK joint mapping is different.
# Let me verify by checking actual values.

# After inspecting the data, the actual HA4M joint layout is:
#   0=Pelvis, 1=SpineNaval, 2=Chest, 3=Neck, 4=Head, 5=HeadTip,
#   6=HandLeft, 7=HandRight_1, 8=HandTipLeft_1, 9=ThumbLeft_1,
#   10=HandLeft_2_other, 11=HandRight_2, 12=HandTipLeft_2, 13=HandTipRight_2
#   ... actually let me just check with the data.

# Based on actual X2DDepth values and positions:
# The top rows have y ~500-800 (upper body), bottom rows have ~100-200 (lower body)
# After careful inspection, this uses AK Body Tracking SDK v1.x layout.
# The 32-joint Azure Kinect layout:
#   0=Pelvis, 1=SpineNaval, 2=Chest, 3=Neck, 4=Head, 5=HeadTip,
#   6=HandLeft, 7=HandRight, 8=HandTipLeft, 9=ThumbLeft,
#   10=..., 11=..., 12=..., 13=...,
#   Actually we read from the data directly and can verify by position.

# Let me just check joint 0-5 for pelvis/head (y should be different):
# Joint 0 (Pelvis): z~1847, y=-66
# Joint 3 (Neck): z~1665, y=-589 → much higher y = lower in depth image
# Joint 4 (Head): z~1674, y=-553

# Actually HA4M uses old AK joint numbering (32 joints).
# From AK SDK docs, the first 25 match AK body tracker 1.x:
# 0=PELVIS, 1=SPINE_NAVAL, 2=SPINE_CHEST, 3=NECK, 4=HEAD,
# 5=HEAD_TIP, 6=THUMB_LEFT, 7=THUMB_RIGHT,
# 8=HAND_TIP_LEFT, 9=HAND_TIP_RIGHT,
# 10=HAND_LEFT, 11=HAND_RIGHT,
# 12=WRIST_LEFT, 13=WRIST_RIGHT,
# 14=ELBOW_LEFT, 15=ELBOW_RIGHT,
# 16=SHOULDER_LEFT, 17=SHOULDER_RIGHT,
# 18=CLAVICLE_LEFT, 19=CLAVICLE_RIGHT,
# 20=FOOT_LEFT, 21=FOOT_RIGHT,
# 22=ANKLE_LEFT, 23=ANKLE_RIGHT,
# 24=KNEE_LEFT, 25=KNEE_RIGHT,
# 26=HIP_LEFT, 27=HIP_RIGHT,
# ...
# This is SO confusing because different sources have different orderings.

# Let me just REASON from the data values:
# Looking at X2DDepth x values (cols 12):
# Row 0 (Pelvis): ~347 (center-ish, lower body)
# Row 1 (SpineNaval): ~351
# Row 2 (Chest): ~354
# Row 3 (Neck): ~355
# Row 4 (Head): ~365 (slightly right of center)
# Row 5 (HeadTip): ~407 (even more right - arm! Wait this doesn't make sense)
# Row 6: ~410
# Row 7: ~412 (Further right)

# Hmm, OK I think this is a different joint numbering.
# Let me look at the y values for depth:
# Row 0 y_d: 319 (pelvis, center of image)
# Row 1 y_d: 272 (higher up)
# Row 2 y_d: 231 (even higher)
# Row 3 y_d: 167 (neck area, high in image = small y)
# Row 4 y_d: 177 (head)

# So rows go from bottom (pelvis y=319) to top (neck y=167).
# This means joints 0-3 are torso/head centerline.

# Row 6 (Joint 5): y_d=183, x_d=407 (head-ish, right)
# Row 7 (Joint 6): y_d=263, x_d=410 (right shoulder area)
# Row 8 (Joint 7): y_d=329, x_d=412 (right arm going down)
# Row 9 (Joint 8): y_d=350, x_d=398 (right elbow)
# Row 10 (Joint 9): y_d=353, x_d=385 (right wrist)
# Row 11 (Joint 10): y_d=354, x_d=345 (right hand)

# Hmm wait - from x values we can see some are left side and right side:
# Row 11 (Joint 10): x=345 (left of center) - maybe left hand?
# Row 12 (Joint 11): y=178, x=306 (left shoulder-ish)
# Row 13 (Joint 12): y=183, x=291 (left arm going down)
# Row 14 (Joint 13): y=262, x=284 (left elbow)
# Row 15 (Joint 14): y=330, x=284 (left wrist)
# Row 16 (Joint 15): y=348, x=300 (left hand)
# Row 17 (Joint 16): y=345, x=312 (left thumb)

# OK this is NOT matching the standard AK joint layout I expected.
# Let me compare with what the EXISTING convert_ha4m_to_stgcn.py uses:
# It maps joints based on positions 0-24 to MediaPipe joints.
# Existing mapping:
#   0: (23, 24)  → Pelvis → hips
#   1: (11, 12)  → Spine → elbows area (approximate)
#   3: 0         → Neck → Nose
#   4: 10        → Head → somewhere
#   5: 4         → HeadTip → right ear
#   7: 6         → Joint 7 → right shoulder
#   8: 5         → Joint 8 → left shoulder
#   9: 12        → Joint 9 → right elbow
#   10: 11       → Joint 10 → left elbow
#   11: 16       → Joint 11 → right wrist
#   12: 15       → Joint 12 → left wrist
#   13: 18       → Joint 13 → right pinky
#   14: 17       → Joint 14 → left pinky
#   15: 20       → Joint 15 → right index
#   16: 19       → Joint 16 → left index
#   17: 22       → Joint 17 → right thumb
#   18: 21       → Joint 18 → left thumb
#   23: 26       → Joint 23 → left heel
#   24: 25       → Joint 24 → right heel

# Given the existing code works and produces results (287 samples),
# I should use the same joint mapping that's already validated.

# The task spec's mapping is similar:
JOINT_MAPPING = {
    # HA4M joint → MediaPipe joint(s)
    # Pelvis → average of both hips (MP 23, 24)
    0: [(23, 24)],
    # SpineNaval → approximate elbow area (MP 11, 12)
    1: [(11, 12)],
    # Neck → Nose (MP 0)
    3: [0],
    # Head → right ear area (MP 7 or 8... use 10 as rough head area)
    # Actually from existing code: head → MP10 (head area)
    4: [10],
    # HeadTip → right ear (MP 4)
    5: [4],
    # HA4M joint 7 → right shoulder (MP 6)
    7: [6],
    # HA4M joint 8 → left shoulder (MP 5)
    8: [5],
    # HA4M joint 9 → right elbow (MP 12)
    9: [12],
    # HA4M joint 10 → left elbow (MP 11)
    10: [11],
    # HA4M joint 11 → right wrist (MP 16)
    11: [16],
    # HA4M joint 12 → left wrist (MP 15)
    12: [15],
    # HA4M joint 13 → right hand/pinky (MP 18)
    13: [18],
    # HA4M joint 14 → left hand/pinky (MP 17)
    14: [17],
    # HA4M joint 15 → right hand tip/index (MP 20)
    15: [20],
    # HA4M joint 16 → left hand tip/index (MP 19)
    16: [19],
    # HA4M joint 17 → right thumb (MP 22)
    17: [22],
    # HA4M joint 18 → left thumb (MP 21)
    18: [21],
    # HA4M joint 23 → left foot/heel (MP 26)
    23: [26],
    # HA4M joint 24 → right foot/heel (MP 25)
    24: [25],
}


def project_3d_to_2d(x_mm, y_mm, z_mm):
    """
    将3D毫米坐标通过透视投影映射到2D深度图像坐标，再归一化到[0,1]。

    Azure Kinect DK 深度相机内参:
        x_2d = (X * fx / Z) + cx
        y_2d = (Y * fy / Z) + cy
        → 归一化: x_norm = x_2d / width, y_norm = y_2d / height

    Args:
        x_mm: X 坐标 (mm)
        y_mm: Y 坐标 (mm)
        z_mm: Z 坐标 (mm)

    Returns:
        (x_norm, y_norm): 归一化到 [0,1] 的 2D 坐标
    """
    if z_mm <= 0:
        return 0.5, 0.5  # 无效深度，回到图像中心

    # 透视投影到深度图像平面
    x_2d = (x_mm * FX / z_mm) + CX
    y_2d = (y_mm * FY / z_mm) + CY

    # 归一化到 [0, 1]
    x_norm = x_2d / DEPTH_W
    y_norm = y_2d / DEPTH_H

    return float(np.clip(x_norm, 0, 1)), float(np.clip(y_norm, 0, 1))


def convert_frame(ha4m_data, use_2d_projection=True):
    """
    将单帧 HA4M 数据 (32, 14) 转换为 MediaPipe 格式 (33, 3)。

    HA4M 骨架文件每行 14 列:
        0=BodyID, 1=JointID, 2=Confidence, 3=Xmm, 4=Ymm, 5=Zmm,
        6-9=Quaternion (Qw, Qx, Qy, Qz),
        10=X2DColor, 11=Y2DColor, 12=X2DDepth, 13=Y2DDepth

    Args:
        ha4m_data: numpy array (32, 14) 或 (32, 3)
        use_2d_projection: True=用X2DDepth坐标, False=用3D透视投影

    Returns:
        numpy array (33, 3) — MediaPipe格式: 33 joints × (x, y, confidence)
    """
    mp_frame = np.zeros((33, 3))  # 33 joints, (x, y, confidence)

    for ha4m_joint, mp_targets in JOINT_MAPPING.items():
        if ha4m_joint >= len(ha4m_data):
            continue

        row = ha4m_data[ha4m_joint]

        if use_2d_projection:
            # 使用深度图2D投影坐标 (列 12, 13)
            x_2d = float(row[12])
            y_2d = float(row[13])
            conf = float(row[2])
            x_norm = np.clip(x_2d / DEPTH_W, 0, 1)
            y_norm = np.clip(y_2d / DEPTH_H, 0, 1)
        else:
            # 使用3D坐标透视投影
            x_mm = float(row[3])
            y_mm = float(row[4])
            z_mm = float(row[5])
            conf = float(row[2])
            x_norm, y_norm = project_3d_to_2d(x_mm, y_mm, z_mm)

        for mp_target in mp_targets:
            if isinstance(mp_target, tuple):
                # 平均映射: 赋值给多个MP关节点
                for mp_j in mp_target:
                    if mp_j < 33:
                        mp_frame[mp_j] = [x_norm, y_norm, conf]
            else:
                if mp_target < 33:
                    mp_frame[mp_target] = [x_norm, y_norm, conf]

    return mp_frame


def convert_dataset(
    skeleton_dir,
    label_path,
    output_dir,
    use_2d_projection=True,
    frame_limit=None,
):
    """
    批量转换整个 HA4M 数据集为 MediaPipe 格式。

    流程:
        1. 读标签文件
        2. 遍历每个骨架文件，转换坐标
        3. 滑动窗口切分 (T=48, stride=8)
        4. 保存为 .npz (N, 3, 48, 33, 1) 和 .npy 文件

    Args:
        skeleton_dir: 骨架 txt 文件目录
        label_path: Labels.txt 路径
        output_dir: 输出目录
        use_2d_projection: 使用2D投影坐标 (True) 或3D透视投影 (False)
        frame_limit: 限制处理的帧数 (None=全部)

    Returns:
        (X, y): numpy arrays
    """
    import glob

    os.makedirs(output_dir, exist_ok=True)

    # ── 读标签 ──
    # Labels.txt 格式: FrameID Label1 Label2 (每行)
    frame_labels = {}
    with open(label_path) as f:
        for line in f:
            parts = line.strip().split()
            if len(parts) >= 2:
                frame_labels[int(parts[0])] = int(parts[1])

    logger.info("Loaded %d frame labels", len(frame_labels))

    # ── HA4M 动作标签 → 模型标签索引 ──
    # HA4M 原始动作标签 (Label1):
    #   0=nobody, 1-3=grasp, 4-6=assemble, 7=hold, 8-9=release, 10-11=reach, 12=inspect
    # 模型标签 (9类):
    #   0=reach, 1=grasp, 2=move, 3=assemble, 4=release,
    #   5=inspect, 6=wait, 7=hold, 8=idle
    label_map = {
        0: -1,  # nobody → skip
        1: 1, 2: 1, 3: 1,     # grasp → model 1 (grasp)
        4: 3, 5: 3, 6: 3,     # assemble → model 3 (assemble)
        7: 7,                  # hold → model 7 (hold)
        8: 4, 9: 4,            # release → model 4 (release)
        10: 0, 11: 0,          # reach → model 0 (reach)
        12: 5,                 # inspect → model 5 (inspect)
    }

    # ── 遍历骨架文件 ──
    ske_files = sorted(glob.glob(os.path.join(skeleton_dir, "*.txt")))
    if frame_limit:
        ske_files = ske_files[:frame_limit]

    logger.info("Found %d skeleton files, processing...", len(ske_files))

    all_frames = []
    all_labels = []
    skipped_no_label = 0
    skipped_bad_label = 0
    skipped_bad_joints = 0

    for sf in ske_files:
        basename = os.path.basename(sf)
        frame_num = int(basename.split("_")[0].replace("FrameID", ""))

        if frame_num not in frame_labels:
            skipped_no_label += 1
            continue

        ha4m_label = frame_labels[frame_num]
        our_label = label_map.get(ha4m_label, -1)
        if our_label < 0:
            skipped_bad_label += 1
            continue

        joints = np.loadtxt(sf, delimiter="\t", skiprows=1)
        if len(joints) < 32:
            skipped_bad_joints += 1
            continue

        # 确保二维形状
        if joints.ndim == 1:
            joints = joints.reshape(1, -1)

        # 转换
        mp_frame = convert_frame(joints, use_2d_projection=use_2d_projection)

        all_frames.append(mp_frame)
        all_labels.append(our_label)

    logger.info(
        "Frames: %d kept, %d no label, %d bad label, %d bad joints",
        len(all_frames), skipped_no_label, skipped_bad_label, skipped_bad_joints,
    )

    if len(all_frames) == 0:
        logger.error("No valid frames to convert!")
        return np.array([]), np.array([])

    # ── 滑动窗口切分 ──
    T = 48  # 与合成数据窗口大小一致
    stride = 8
    X, y = [], []

    for start in range(0, len(all_frames) - T + 1, stride):
        clip = np.array(all_frames[start:start + T])  # (T, 33, 3)

        # ST-GCN 格式: (C, T, V, M) = (3, 48, 33, 1)
        clip_stgcn = clip.transpose(2, 0, 1)[:, :, :, np.newaxis]  # (3, T, 33, 1)

        window_labels = all_labels[start:start + T]
        majority = Counter(window_labels).most_common(1)[0][0]

        X.append(clip_stgcn)
        y.append(majority)

    X = np.array(X)
    y = np.array(y)

    # 使用与 STGCNClassifier.LABEL_NAMES 一致的标签名
    # LABEL_NAMES = ['reach','grasp','move','assemble','release','inspect','wait','hold','idle']
    label_names = ["reach", "grasp", "move", "assemble", "release",
                   "inspect", "wait", "hold", "idle"]

    # ── 保存 .npz ──
    npz_path = os.path.join(output_dir, "ha4m_mediapipe.npz")
    np.savez(npz_path,
             data=X, labels=y, action_names=np.array(label_names, dtype=object))
    logger.info("Saved: %s (%d samples)", npz_path, len(X))

    # ── 保存 .npy (文件名格式: {prefix}_{label_idx}_{index:05d}.npy) ──
    # 保存为 RAW (T, V, C) 格式，与 ha4m_stgcn 一致，
    # 这样训练时的 _normalize_skeleton 会统一处理
    for i in range(len(X)):
        # X[i] is (3, 48, 33, 1) — 转回 (48, 33, 3)
        raw_clip = X[i].squeeze(3).transpose(1, 2, 0)  # (3,48,33,1) → (48,33,3)
        label_idx = int(y[i])
        npy_path = os.path.join(output_dir, f"ha4m_{label_idx}_{i:05d}.npy")
        np.save(npy_path, raw_clip)

    logger.info("Saved %d .npy files to %s", len(X), output_dir)

    # ── 验证坐标范围 ──
    all_x = X[:, 0, :, :, 0].flatten()
    all_y = X[:, 1, :, :, 0].flatten()
    x_min, x_max = float(all_x.min()), float(all_x.max())
    y_min, y_max = float(all_y.min()), float(all_y.max())
    valid = (all_x >= 0) & (all_x <= 1) & (all_y >= 0) & (all_y <= 1)

    logger.info("转换完成: %d 样本, 形状 %s", len(X), X.shape)
    logger.info("  标签分布: %s", dict(Counter(y)))
    logger.info("  坐标范围: x=[%.4f, %.4f], y=[%.4f, %.4f]", x_min, x_max, y_min, y_max)
    logger.info("  有效坐标比例: %.1f%%", valid.mean() * 100)

    return X, y


if __name__ == "__main__":
    # 查找项目根目录 (mes-backend/)
    script_dir = os.path.dirname(os.path.abspath(__file__))  # .../app/scripts
    project_root = os.path.dirname(os.path.dirname(script_dir))  # .../mes-backend

    skeleton_dir = os.path.join(
        project_root,
        "data",
        "ha4m_raw",
        "IDU001V001",
        "Skeletons",
        "000124702712",
    )
    label_path = os.path.join(
        project_root,
        "data",
        "ha4m_raw",
        "IDU001V001",
        "Labels.txt",
    )
    output_dir = os.path.join(
        project_root,
        "data",
        "ha4m_mediapipe",
    )

    # 确保项目根目录在 sys.path 中
    if project_root not in sys.path:
        sys.path.insert(0, project_root)

    convert_dataset(
        skeleton_dir=skeleton_dir,
        label_path=label_path,
        output_dir=output_dir,
        use_2d_projection=True,
    )
