"""
Generate synthetic HA4M-style skeleton data for manufacturing assembly actions.

Since the real HA4M dataset (ScienceDB) requires login authentication,
this script generates realistic synthetic skeleton sequences mimicking
the 9 action classes used in our system.

Output:
  - mes-backend/data/ha4m_converted.npz   — Full dataset in (C, T, V, M) format
  - mes-backend/data/ha4m_converted/      — Individual .npy files per sample
"""

from __future__ import annotations

import logging
import os
import sys
from pathlib import Path

import numpy as np

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger(__name__)

# ─── Configuration ────────────────────────────────────────────────────

ACTIONS = ["reach", "grasp", "move", "assemble", "release", "inspect", "wait", "hold", "idle"]
N_PER_CLASS = 30  # 30 samples per class = 270 total
T = 64           # Fixed temporal length to match training pipeline
V = 33           # MediaPipe landmarks
C = 3            # x, y, confidence
M = 1            # Single person

OUTPUT_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))), "data")


# ─── Motion generators per action type ────────────────────────────────

def _gen_reach(T: int, V: int, speed: float, rng: np.random.Generator) -> np.ndarray:
    """Reaching for an object: right arm extends forward."""
    skel = _base_pose(T, V, rng)
    target_x = 0.3 + rng.random() * 0.4
    target_y = 0.3 + rng.random() * 0.3
    target_z = 0.7 - rng.random() * 0.2
    for t in range(T):
        p = min(1.0, t / (T * 0.6 * speed))
        # Right wrist (landmark 16) moves toward target
        skel[t, 16] = [0.3 + p * (target_x - 0.3), 0.6 + p * (target_y - 0.6), 0.85 + p * (target_z - 0.85)]
        # Right elbow (15) follows partially
        skel[t, 15] = [0.7, 0.6 + p * (target_y - 0.6) * 0.3, 0.9]
    return skel


def _gen_grasp(T: int, V: int, speed: float, rng: np.random.Generator) -> np.ndarray:
    """Grasping: reach → close hand → retract."""
    skel = _base_pose(T, V, rng)
    for t in range(T):
        phase = t / T
        p_extend = min(1.0, phase / 0.3 * speed)
        p_retract = max(0.0, min(1.0, (phase - 0.6) / 0.4 * speed))
        extend = 0.3 + p_extend * (0.6 - 0.3)
        retract = 0.6 - p_retract * (0.6 - 0.3)
        pos = extend if phase < 0.6 * speed else retract
        skel[t, 16] = [pos, 0.6 - p_extend * 0.1, 0.9]
        skel[t, 15] = [0.7, 0.6, 0.9]
    return skel


def _gen_move(T: int, V: int, speed: float, rng: np.random.Generator) -> np.ndarray:
    """Moving an object: translate both hands."""
    skel = _base_pose(T, V, rng)
    dx = (rng.random() - 0.5) * 0.4
    dy = (rng.random() - 0.5) * 0.3
    for t in range(T):
        p = min(1.0, t / (T * 0.5 * speed))
        skel[t, 16] = [0.5 + p * dx, 0.5 + p * dy, 0.9]
        skel[t, 15] = [0.5 + p * dx * 0.5, 0.5 + p * dy * 0.5, 0.9]
        skel[t, 12] = [0.5 + p * dx * 0.3, 0.35 + p * dy * 0.2, 0.9]
    return skel


def _gen_assemble(T: int, V: int, speed: float, rng: np.random.Generator) -> np.ndarray:
    """Assembly: bring hands together with fine tremor."""
    skel = _base_pose(T, V, rng)
    for t in range(T):
        p = min(1.0, t / (T * 0.7 * speed))
        # Both hands move toward center
        skel[t, 16] = [0.5 - p * 0.1, 0.5 - p * 0.15, 0.85]
        skel[t, 15] = [0.7 + p * 0.05, 0.5 - p * 0.1, 0.9]
        skel[t, 20] = [0.5 + p * 0.1, 0.5 - p * 0.15, 0.85]
        skel[t, 19] = [0.3 - p * 0.05, 0.5 - p * 0.1, 0.9]
        # Fine tremor during assembly phase
        if t > T * 0.5:
            skel[t, 16, :2] += rng.normal(0, 0.005, 2)
            skel[t, 20, :2] += rng.normal(0, 0.005, 2)
    return skel


def _gen_release(T: int, V: int, speed: float, rng: np.random.Generator) -> np.ndarray:
    """Release: open hand and move away."""
    skel = _base_pose(T, V, rng)
    for t in range(T):
        p = min(1.0, t / (T * 0.4 * speed))
        skel[t, 16] = [0.5 + p * 0.2, 0.5 - p * 0.1, 0.9]
        skel[t, 15] = [0.7, 0.5, 0.9]
        # Fingers spread (approximate by moving fingertip landmarks)
        skel[t, 18] = [0.5 + p * 0.15, 0.45 - p * 0.1, 0.85]
        skel[t, 22] = [0.5 + p * 0.2, 0.55 - p * 0.05, 0.85]
    return skel


def _gen_inspect(T: int, V: int, speed: float, rng: np.random.Generator) -> np.ndarray:
    """Inspect: lean forward, tilt head, small hand adjustments."""
    skel = _base_pose(T, V, rng)
    for t in range(T):
        p = min(1.0, t / (T * 0.3 * speed))
        # Lean forward
        skel[t, 0] = [0.5, 0.1 + p * 0.05, 0.9]
        skel[t, 11] = [0.35, 0.25 + p * 0.03, 0.9]
        skel[t, 12] = [0.65, 0.25 + p * 0.03, 0.9]
        # Hand held up near face
        skel[t, 16] = [0.55 + np.sin(t * 0.05) * 0.02, 0.3, 0.85]
        skel[t, 15] = [0.65, 0.35, 0.9]
    return skel


def _gen_wait(T: int, V: int, speed: float, rng: np.random.Generator) -> np.ndarray:
    """Wait: minimal movement, slight sway."""
    skel = _base_pose(T, V, rng)
    for t in range(T):
        sway_x = np.sin(t * 0.03) * 0.01 * speed
        sway_y = np.cos(t * 0.04) * 0.005 * speed
        skel[t, :, 0] += sway_x
        skel[t, :, 1] += sway_y
    return skel


def _gen_hold(T: int, V: int, speed: float, rng: np.random.Generator) -> np.ndarray:
    """Hold: arms extended forward, static."""
    skel = _base_pose(T, V, rng)
    for t in range(T):
        skel[t, 16] = [0.55, 0.55, 0.85]
        skel[t, 15] = [0.7, 0.55, 0.9]
        skel[t, 20] = [0.45, 0.55, 0.85]
        skel[t, 19] = [0.3, 0.55, 0.9]
        # Small drift
        if t > T * 0.3:
            skel[t, 16, :2] += rng.normal(0, 0.003)
            skel[t, 20, :2] += rng.normal(0, 0.003)
    return skel


def _gen_idle(T: int, V: int, speed: float, rng: np.random.Generator) -> np.ndarray:
    """Idle: upright posture, natural breathing motion."""
    skel = _base_pose(T, V, rng)
    for t in range(T):
        breath = np.sin(t * 0.1) * 0.005 * speed
        skel[t, :, 1] += breath
    return skel


# ─── Base pose ─────────────────────────────────────────────────────────

def _base_pose(T: int, V: int, rng: np.random.Generator) -> np.ndarray:
    """Create upright standing pose with slight random variations."""
    skel = np.zeros((T, V, C), dtype=np.float32)

    # Torso
    skel[:, 0] = [0.5, 0.1, 0.95]     # nose
    skel[:, 1] = [0.48, 0.08, 0.9]    # left eye inner
    skel[:, 2] = [0.47, 0.08, 0.9]    # left eye
    skel[:, 3] = [0.46, 0.09, 0.9]    # left eye outer
    skel[:, 4] = [0.52, 0.08, 0.9]    # right eye inner
    skel[:, 5] = [0.53, 0.08, 0.9]    # right eye
    skel[:, 6] = [0.54, 0.09, 0.9]    # right eye outer
    skel[:, 7] = [0.47, 0.12, 0.85]   # left ear
    skel[:, 8] = [0.53, 0.12, 0.85]   # right ear
    skel[:, 9] = [0.48, 0.12, 0.85]   # mouth left
    skel[:, 10] = [0.52, 0.12, 0.85]  # mouth right
    skel[:, 11] = [0.35, 0.25, 0.9]   # left shoulder
    skel[:, 12] = [0.65, 0.25, 0.9]   # right shoulder
    skel[:, 13] = [0.3, 0.35, 0.9]    # left elbow
    skel[:, 14] = [0.7, 0.35, 0.9]    # right elbow
    skel[:, 15] = [0.25, 0.5, 0.85]   # left wrist
    skel[:, 16] = [0.75, 0.5, 0.85]   # right wrist
    skel[:, 17] = [0.28, 0.45, 0.85]  # left pinky
    skel[:, 18] = [0.28, 0.55, 0.85]  # left index
    skel[:, 19] = [0.22, 0.48, 0.85]  # left thumb
    skel[:, 20] = [0.72, 0.45, 0.85]  # right pinky
    skel[:, 21] = [0.72, 0.55, 0.85]  # right index
    skel[:, 22] = [0.78, 0.48, 0.85]  # right thumb
    skel[:, 23] = [0.4, 0.55, 0.9]    # left hip
    skel[:, 24] = [0.6, 0.55, 0.9]    # right hip
    skel[:, 25] = [0.4, 0.7, 0.9]     # left knee
    skel[:, 26] = [0.6, 0.7, 0.9]     # right knee
    skel[:, 27] = [0.4, 0.85, 0.8]    # left ankle
    skel[:, 28] = [0.6, 0.85, 0.8]    # right ankle
    skel[:, 29] = [0.38, 0.9, 0.75]   # left heel
    skel[:, 30] = [0.62, 0.9, 0.75]   # right heel
    skel[:, 31] = [0.42, 0.92, 0.75]  # left foot index
    skel[:, 32] = [0.58, 0.92, 0.75]  # right foot index

    # Add slight random offset per sample
    offset_x = rng.uniform(-0.02, 0.02)
    offset_y = rng.uniform(-0.02, 0.02)
    skel[:, :, 0] += offset_x
    skel[:, :, 1] += offset_y

    return skel


# ─── Generator lookup ─────────────────────────────────────────────────

ACTION_GENERATORS = {
    "reach": _gen_reach,
    "grasp": _gen_grasp,
    "move": _gen_move,
    "assemble": _gen_assemble,
    "release": _gen_release,
    "inspect": _gen_inspect,
    "wait": _gen_wait,
    "hold": _gen_hold,
    "idle": _gen_idle,
}


def generate_dataset(
    actions: list[str] = ACTIONS,
    n_per_class: int = N_PER_CLASS,
    t_len: int = T,
    seed: int = 42,
) -> tuple[np.ndarray, np.ndarray]:
    """Generate synthetic skeleton dataset.

    Returns:
        dataset: (N, C, T, V, M) — ST-GCN format
        labels:  (N,) — integer labels
    """
    rng = np.random.default_rng(seed)
    dataset = []
    labels = []

    for action_idx, action in enumerate(actions):
        gen_fn = ACTION_GENERATORS[action]
        for var_idx in range(n_per_class):
            speed = 0.7 + rng.random() * 0.6  # 0.7~1.3
            skeleton_tvc = gen_fn(t_len, V, speed, rng)  # (T, V, C)

            # Add noise
            noise_level = 0.003 + rng.random() * 0.005
            skeleton_tvc += rng.normal(0, noise_level, skeleton_tvc.shape).astype(np.float32)

            # Ensure confidence values are in valid range
            skeleton_tvc[:, :, 2] = np.clip(skeleton_tvc[:, :, 2], 0.7, 1.0)

            # Convert (T, V, C) → (C, T, V, M)
            stgcn_data = skeleton_tvc.transpose(2, 0, 1)[:, :, :, np.newaxis]  # (C, T, V, 1)
            dataset.append(stgcn_data)
            labels.append(action_idx)

    dataset_arr = np.array(dataset, dtype=np.float32)
    labels_arr = np.array(labels, dtype=np.int64)

    logger.info(f"Generated {len(dataset)} samples")
    logger.info(f"  Dataset shape: {dataset_arr.shape}")
    logger.info(f"  Labels shape: {labels_arr.shape}")
    for i, action in enumerate(actions):
        count = int(np.sum(labels_arr == i))
        logger.info(f"  {action:<12s}: {count} samples")

    return dataset_arr, labels_arr


def save_individual_npy(
    dataset: np.ndarray, labels: np.ndarray, actions: list[str],
    output_dir: str, prefix: str = "ha4m_synthetic",
) -> str:
    """Save each sample as individual .npy file for use with existing training pipeline."""
    npy_dir = os.path.join(output_dir, f"{prefix}_individual")
    Path(npy_dir).mkdir(parents=True, exist_ok=True)

    from collections import Counter
    label_counter = Counter()

    for i in range(len(dataset)):
        action = actions[labels[i]]
        sample = dataset[i]  # (C, T, V, M)
        # Convert back to (T, V, C) for compatibility with existing pipeline
        sample_tvc = sample.squeeze(-1).transpose(1, 2, 0)  # (T, V, C)
        fname = f"{prefix}_{action}_{i:04d}.npy"
        np.save(os.path.join(npy_dir, fname), sample_tvc)
        label_counter[action] += 1

    logger.info(f"Individual .npy files saved to: {npy_dir}")
    for action, count in sorted(label_counter.items()):
        logger.info(f"  {action:<12s}: {count}")
    return npy_dir


def main():
    logger.info("=" * 60)
    logger.info("HA4M Synthetic Dataset Generator")
    logger.info("=" * 60)

    logger.info("Generating synthetic skeleton data for %d action classes...", len(ACTIONS))
    dataset, labels = generate_dataset(actions=ACTIONS, n_per_class=N_PER_CLASS, t_len=T)

    # ── Save as .npz ──
    npz_path = os.path.join(OUTPUT_DIR, "ha4m_converted.npz")
    np.savez_compressed(npz_path, data=dataset, labels=labels, action_names=ACTIONS)
    file_size_mb = os.path.getsize(npz_path) / 1024 / 1024
    logger.info(f"Saved .npz to: {npz_path} ({file_size_mb:.1f} MB)")

    # ── Verify ──
    verify = np.load(npz_path, allow_pickle=True)
    logger.info(f"Verification: data={verify['data'].shape}, labels={verify['labels'].shape}")
    logger.info(f"  Action names: {verify['action_names']}")
    verify.close()

    # ── Save individual .npy files ──
    save_individual_npy(dataset, labels, ACTIONS, OUTPUT_DIR)

    logger.info("Done! Ready for training.")
    logger.info("=" * 60)


if __name__ == "__main__":
    main()
