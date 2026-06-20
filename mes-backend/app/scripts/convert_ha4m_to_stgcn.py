"""
将HA4M (Azure Kinect 32关节点) 转换为 ST-GCN 训练格式
1. 读取骨架txt + labels.txt
2. 关节映射 32→33 (对齐MediaPipe)
3. 归一化坐标 3Dmm→2D归一化
4. 滑动窗口切片 (T=48)
5. 保存为 .npz 和 .npy
"""

import numpy as np
import os, sys, glob
from collections import Counter

# Get model label ordering (must match STGCNClassifier.LABEL_NAMES)
_project_root = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
if _project_root not in sys.path:
    sys.path.insert(0, _project_root)
try:
    from app.ml.stgcn_model import LABEL_NAMES
except ImportError:
    # Fallback if module not available
    LABEL_NAMES = ['reach', 'grasp', 'move', 'assemble', 'release', 'inspect', 'wait', 'hold', 'idle']

# Azure Kinect 32 关节 → 近似映射到 MediaPipe 33 关节
# 对于 ST-GCN，我们只需要保持33维，用0填充无对应关节
def convert_joints(ak_data):
    """Convert Azure Kinect 32-joint to 33-joint MediaPipe-like format
    
    AK file columns (0-indexed):
      0=BodyID, 1=JointID, 2=Confidence, 3=Xmm, 4=Ymm, 5=Zmm,
      6-9=Quaternion, 10=X2DColor, 11=Y2DColor, 12=X2DDepth, 13=Y2DDepth
    
    Strategy: use 2D depth coordinates (cols 12,13) normalized to [0,1]
    to match MediaPipe's image-normalized coordinate space.
    """
    mp_data = np.zeros((33, 3))  # 33 joints, (x, y, confidence)
    
    # Azure Kinect depth image resolution
    DEPTH_W = 640.0
    DEPTH_H = 576.0
    
    # Joint mapping (AK → MP approximate)
    # AK 0=Pelvis, 1=SpineNaval, 2=Chest, 3=Neck, 4=Head, 5=HeadTip
    # MediaPipe 0=Nose, 5-6=Shoulders, 11-12=Elbows, 15-16=Wrists
    mapping = {
        0: (23, 24),  # Pelvis → hips (average)
        1: (11, 12),  # SpineNaval → approximate to elbows area
        3: 0,         # Neck → Nose (best approximation)
        4: 10,        # Head → somewhere on head
        5: 4,         # HeadTip → right ear area
        7: 6,         # ShoulderRight → right shoulder
        8: 5,         # ShoulderLeft → left shoulder
        9: 12,        # ElbowRight → right elbow  
        10: 11,       # ElbowLeft → left elbow
        11: 16,       # WristRight → right wrist
        12: 15,       # WristLeft → left wrist
        13: 18,       # HandRight → right pinky
        14: 17,       # HandLeft → left pinky
        15: 20,       # HandTipRight → right index
        16: 19,       # HandTipLeft → left index
        17: 22,       # ThumbRight → right thumb
        18: 21,       # ThumbLeft → left thumb
        23: 26,       # FootLeft → left heel
        24: 25,       # FootRight → right heel
    }
    
    for ak_j, mp_j in mapping.items():
        if isinstance(mp_j, tuple):  # 取平均
            val = ak_data[ak_j] if ak_j < len(ak_data) else np.zeros(14)
            # Use 2D depth pixel coordinates normalized to [0, 1]
            x = val[12] / DEPTH_W
            y = val[13] / DEPTH_H
            conf = val[2]
            for mj in mp_j:
                if mj < 33:
                    mp_data[mj] = [x, y, conf]
        else:
            if ak_j < len(ak_data):
                val = ak_data[ak_j]
                x = val[12] / DEPTH_W
                y = val[13] / DEPTH_H
                mp_data[mp_j] = [x, y, val[2]]
    
    return mp_data

def convert_ha4m(skeleton_dir, label_path, output_dir, frame_step=1):
    """Convert HA4M dataset to ST-GCN format"""
    os.makedirs(output_dir, exist_ok=True)
    
    # 读标签
    frame_labels = {}
    with open(label_path) as f:
        for line in f:
            parts = line.strip().split()
            if len(parts) >= 2:
                frame_labels[int(parts[0])] = int(parts[1])
    
    # HA4M action IDs → model label indices
    # Preserve the original action mapping but align indices to LABEL_NAMES ordering
    # Original: ha4m→our_actions index mapping:
    #   {0:-1, 1:0, 2:0, 3:0, 4:1, 5:1, 6:1, 7:6, 8:2, 9:2, 10:3, 11:3, 12:4}
    #   our_actions = ['grasp','assemble','release','reach','inspect','move','hold','wait','idle']
    # Model: LABEL_NAMES = ['reach','grasp','move','assemble','release','inspect','wait','hold','idle']
    # Conversion: our_actions[i] → LABEL_NAMES[j]: {0:1, 1:3, 2:4, 3:0, 4:5, 5:2, 6:7, 7:6, 8:8}
    _ha4m_to_model = {
        0: -1,   # nobody → skip
        1: 1, 2: 1, 3: 1,    # grasp (our=0→model=1)
        4: 3, 5: 3, 6: 3,    # assemble (our=1→model=3)
        7: 7,                 # hold (our=6→model=7)
        8: 4, 9: 4,           # release (our=2→model=4)
        10: 0, 11: 0,         # reach (our=3→model=0)
        12: 5,                # inspect (our=4→model=5)
    }
    
    # 读所有骨架文件
    ske_files = sorted(glob.glob(os.path.join(skeleton_dir, '*.txt')))
    
    all_sequences = []
    all_labels = []
    
    # 提取每帧骨架
    for si, sf in enumerate(ske_files):
        frame_num = int(os.path.basename(sf).split('_')[0].replace('FrameID', ''))
        
        if frame_num not in frame_labels:
            continue
        
        ha4m_action_id = frame_labels[frame_num]
        model_label = _ha4m_to_model.get(ha4m_action_id, -1)
        
        if model_label < 0:
            continue  # skip 'nobody'
        
        # 读取骨架
        joints = np.loadtxt(sf, delimiter='\t', skiprows=1)
        if len(joints) < 32:
            continue
        
        # 转换
        mp_frame = convert_joints(joints)
        all_sequences.append(mp_frame)
        all_labels.append(model_label)
    
    sequences = np.array(all_sequences)  # (N, 33, 3)
    labels = np.array(all_labels)
    
    print(f"总有效帧: {len(sequences)}")
    print(f"标签分布:")
    for i, name in enumerate(LABEL_NAMES):
        count = (labels == i).sum()
        if count > 0:
            print(f"  {name:10s}: {count}")
    
    # 滑动窗口切分
    T = 48
    stride = 8
    X_stgcn, y = [], []  # X_stgcn: (C, T, V, 1) for npz
    X_raw, _ = [], []     # X_raw: (T, V, C) for .npy training files
    for start in range(0, len(sequences) - T + 1, stride):
        clip = sequences[start:start+T]  # (T, 33, 3) - raw (T, V, C)
        
        # 多数投票标签
        window_labels = labels[start:start+T]
        majority = Counter(window_labels).most_common(1)[0][0]
        
        # ST-GCN format for npz (verification)
        clip_stgcn = clip.transpose(2, 0, 1)[:, :, :, np.newaxis]  # (3, T, 33, 1)
        X_stgcn.append(clip_stgcn)
        
        # Raw (T, V, C) for training (pipeline applies normalization)
        X_raw.append(clip)
        y.append(majority)
    
    X_stgcn = np.array(X_stgcn)
    X_raw = np.array(X_raw)
    y = np.array(y)
    
    # Apply same normalization as training pipeline for npz
    FIXED_T = 64
    from app.scripts.train_stgcn import _normalize_skeleton, _to_fixed_length, _to_stgcn_format
    X_norm = []
    for i in range(len(X_raw)):
        skel = _normalize_skeleton(X_raw[i])
        skel = _to_fixed_length(skel, FIXED_T)
        skel = _to_stgcn_format(skel)
        X_norm.append(skel)
    X_norm = np.array(X_norm)
    
    # 保存npz (normalized, same as training)
    np.savez(os.path.join(output_dir, 'ha4m_stgcn.npz'),
             data=X_norm, labels=y, action_names=np.array(LABEL_NAMES, dtype=object))
    print(f"\n✅ 转换完成: {len(X_stgcn)}样本")
    print(f"   原始ST-GCN格式: {X_stgcn.shape}")
    print(f"   归一化格式: {X_norm.shape}")
    print(f"   训练格式: {X_raw.shape}")
    print(f"   标签分布: {Counter(y)}")
    
    # 保存单独的.npy (T, V, C)格式用于训练时归一化
    for i in range(len(X_raw)):
        np.save(os.path.join(output_dir, f'ha4m_{y[i]:d}_{i:05d}.npy'), X_raw[i])
    
    print(f"   已保存到 {output_dir}")

if __name__ == '__main__':
    convert_ha4m(
        skeleton_dir='mes-backend/data/ha4m_raw/IDU001V001/Skeletons/000124702712',
        label_path='mes-backend/data/ha4m_raw/IDU001V001/Labels.txt',
        output_dir='mes-backend/data/ha4m_stgcn'
    )
