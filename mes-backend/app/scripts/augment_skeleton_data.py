"""
合成骨架数据增强
对现有骨架序列做几何变换生成新样本

增强方法：
1. 时间轴拉伸/压缩 (1.5x, 0.75x)
2. 关键点抖动 (+N(0, 0.01) 噪声)
3. 水平翻转（左右关键点交换）
4. 部分关键点掩码（模拟部分遮挡，训练鲁棒性）
5. 组合增强

输出：增强后的骨架序列，存入 mes-backend/data/skeleton_augmented/
"""

import numpy as np
import os, glob, sys

# ── 路径 ──────────────────────────────────────────────────────────
_PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))  # mes-backend/
SKELETON_DIR = os.path.join(_PROJECT_ROOT, "data", "skeleton")
OUTPUT_DIR = os.path.join(_PROJECT_ROOT, "data", "skeleton_augmented")

# ── 增强函数 ─────────────────────────────────────────────────────


def time_warp(seq: np.ndarray, factor: float) -> np.ndarray:
    """时间轴拉伸/压缩，用线性插值。"""
    T = seq.shape[0]
    new_T = max(2, int(T * factor))
    indices = np.linspace(0, T - 1, new_T)
    # 对每个关键点和每个通道做插值
    warped = np.zeros((new_T, *seq.shape[1:]), dtype=seq.dtype)
    for v in range(seq.shape[1]):
        for c in range(seq.shape[2]):
            warped[:, v, c] = np.interp(indices, np.arange(T), seq[:, v, c])
    return warped


def add_noise(seq: np.ndarray, std: float = 0.02) -> np.ndarray:
    """添加高斯噪声。只在有有效值的帧上加噪声。"""
    noise = np.random.normal(0, std, seq.shape).astype(seq.dtype)
    valid = ~np.isnan(seq[:, :, 0])
    noisy = seq.copy()
    noisy[valid] += noise[valid]
    return noisy


def horizontal_flip(seq: np.ndarray) -> np.ndarray:
    """水平翻转（左右镜像）。
    
    MediaPipe 关键点映射: 左↔右对称
    0=鼻, 1=左眼内, 2=左眼, 3=左眼外, 4=右眼内, 5=右眼, 6=右眼外
    7=左耳, 8=右耳, 9=嘴左, 10=嘴右
    11=左肩, 12=右肩, 13=左肘, 14=右肘
    15=左腕, 16=右腕, 17=左小指, 18=右小指
    19=左食指, 20=右食指, 21=左拇指, 22=右拇指
    23=左髋, 24=右髋, 25=左膝, 26=右膝
    27=左踝, 28=右踝, 29=左脚跟, 30=右脚跟
    31=左脚尖, 32=右脚尖
    """
    pairs = [
        (1, 4), (2, 5), (3, 6),  # 眼
        (7, 8),                    # 耳
        (9, 10),                   # 嘴
        (11, 12),                  # 肩
        (13, 14),                  # 肘
        (15, 16),                  # 腕
        (17, 18),                  # 小指
        (19, 20),                  # 食指
        (21, 22),                  # 拇指
        (23, 24),                  # 髋
        (25, 26),                  # 膝
        (27, 28),                  # 踝
        (29, 30),                  # 脚跟
        (31, 32),                  # 脚尖
    ]
    flipped = seq.copy()
    # x 翻转: 1.0 - x (假设归一化到 0-1)
    flipped[:, :, 0] = 1.0 - seq[:, :, 0]
    for l, r in pairs:
        flipped[:, [l, r]] = flipped[:, [r, l]]
    return flipped


def temporal_mask(seq: np.ndarray, mask_ratio: float = 0.15) -> np.ndarray:
    """随机遮挡部分连续时间帧（设为 0）。"""
    T = seq.shape[0]
    masked = seq.copy()
    mask_len = max(1, int(T * mask_ratio))
    start = np.random.randint(0, max(1, T - mask_len))
    masked[start:start + mask_len, :, :2] = 0.0
    return masked


def joint_dropout(seq: np.ndarray, drop_prob: float = 0.1) -> np.ndarray:
    """随机丢弃部分关键点（设为 0），模拟部分遮挡。"""
    dropped = seq.copy()
    T, V, C = seq.shape
    # 对每一帧随机丢弃部分关键点
    drop_mask = np.random.random((T, V)) < drop_prob
    dropped[drop_mask] = 0.0
    return dropped


def augment_skeleton(skeleton_path: str, output_dir: str = OUTPUT_DIR) -> int:
    """对单个骨架文件生成增强版本，返回生成的文件数。"""
    data = np.load(skeleton_path)
    basename = os.path.splitext(os.path.basename(skeleton_path))[0]
    # 去掉可能存在的 _skeleton 后缀以便识别
    clean_name = basename.replace("_skeleton", "")
    os.makedirs(output_dir, exist_ok=True)

    variants = {}

    # 1) 原版 (保留原数据)
    variants["orig"] = data

    # 2) 速度变化
    for factor, suffix in [(1.5, "fast"), (0.75, "slow"), (1.3, "midfast"), (0.6, "vslow")]:
        variants[suffix] = time_warp(data, factor)

    # 3) 噪声 (不同级别)
    for std, suffix in [(0.01, "noise_low"), (0.03, "noise_high")]:
        variants[suffix] = add_noise(data, std)

    # 4) 翻转
    variants["flip"] = horizontal_flip(data)

    # 5) 时间掩码
    variants["tmask"] = temporal_mask(data, 0.2)

    # 6) 关键点丢弃
    variants["jdrop"] = joint_dropout(data, 0.15)

    # 7) 组合增强
    # 快+噪声
    variants["fast_noise"] = add_noise(time_warp(data, 1.4), 0.015)
    # 慢+噪声+翻转
    slow_flip = horizontal_flip(time_warp(data, 0.7))
    variants["slow_flip"] = add_noise(slow_flip, 0.01)
    # 快+掩码
    variants["fast_tmask"] = temporal_mask(time_warp(data, 1.5), 0.15)

    # 保存所有变体
    n = 0
    for suffix, arr in variants.items():
        out_path = os.path.join(output_dir, f"{clean_name}_{suffix}.npy")
        np.save(out_path, arr)
        n += 1

    print(f"  {clean_name}: {n} 个变体 (T={data.shape[0]}→{','.join(str(v.shape[0]) for _, v in variants.items())})")
    return n


# ── 主入口 ───────────────────────────────────────────────────────

if __name__ == "__main__":
    np.random.seed(42)

    files = sorted(glob.glob(os.path.join(SKELETON_DIR, "*.npy")))
    if not files:
        print(f"❌ 骨架目录为空: {SKELETON_DIR}")
        sys.exit(1)

    print(f"原始骨架文件: {len(files)} 个")
    print(f"输出目录: {OUTPUT_DIR}")
    print("─" * 50)

    total_generated = 0
    for f in files:
        total_generated += augment_skeleton(f, OUTPUT_DIR)

    # 统计输出
    out_files = sorted(glob.glob(os.path.join(OUTPUT_DIR, "*.npy")))
    print("─" * 50)
    print(f"✅ 原始: {len(files)} 个 → 增强后共 {len(out_files)} 个骨架文件")
    print(f"   每类从 1 个扩充到 {len(out_files) // len(files)} 个")
    print()

    # 显示增强目录内容摘要
    print("文件列表:")
    for f in out_files:
        sz = os.path.getsize(os.path.join(OUTPUT_DIR, f)) / 1024
        print(f"  {os.path.basename(f):60s} {sz:.1f} KB")
