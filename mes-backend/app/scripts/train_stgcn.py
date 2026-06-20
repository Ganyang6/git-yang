"""
Train ST-GCN model on skeleton sequences from database labels.

Usage:
    cd mes-backend && python app/scripts/train_stgcn.py

Steps:
  1. Load skeleton .npy files and fetch action labels from process_segments
  2. Build training dataset with fixed temporal length
  3. Train LightweightSTGCN (~350K params)
  4. Save weights to data/models/stgcn.pth
"""

from __future__ import annotations

import logging
import os
import sys
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, List, Optional, Tuple

import numpy as np
import torch
import torch.nn as nn
import torch.optim as optim
from torch.utils.data import Dataset, DataLoader

# Ensure project root is on path
_project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _project_root not in sys.path:
    sys.path.insert(0, _project_root)

from app.ml.stgcn_model import LightweightSTGCN, MODEL_PATH, LABEL_NAMES, NUM_CLASSES
from app.models.database import get_session, ProcessSegment

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
)
logger = logging.getLogger(__name__)

# ─── Constants ──────────────────────────────────────────────────────

SKELETON_DIR = os.path.join(os.path.dirname(_project_root), "data", "skeleton")
VIDEO_DIR = os.path.join(
    os.path.dirname(os.path.dirname(_project_root)), "data", "videos"
)
if not os.path.isdir(VIDEO_DIR):
    VIDEO_DIR = os.path.join(os.path.dirname(_project_root), "data", "videos")
MODEL_DIR = os.path.dirname(MODEL_PATH)
FIXED_T = 64  # Pad/truncate all sequences to 64 frames
BATCH_SIZE = 4
EPOCHS = 100
LEARNING_RATE = 1e-3
WEIGHT_DECAY = 1e-4
TRAIN_SPLIT = 0.8
VALIDATION_SPLIT = 0.1  # Rest is test

LABEL_TO_IDX = {name: i for i, name in enumerate(LABEL_NAMES)}

os.makedirs(MODEL_DIR, exist_ok=True)


# ─── Dataset ─────────────────────────────────────────────────────────


def _normalize_skeleton(skeleton: np.ndarray) -> np.ndarray:
    """Normalize coordinates relative to hip center and shoulder width."""
    skel = skeleton.copy()
    # P1.4: Replace NaN values to prevent propagation through normalization
    nan_mask = np.isnan(skel[:, :, 0])  # (T, V) — NaN in x-channel
    skel[nan_mask] = 0.0

    # Hip center (use nanmax/nanmin to survive partial missing landmarks)
    hip_left = skel[:, 23, :2]   # (T, 2)
    hip_right = skel[:, 24, :2]  # (T, 2)
    hip_center = (hip_left + hip_right) / 2  # (T, 2)
    skel[:, :, :2] -= hip_center[:, np.newaxis, :]

    # Scale by shoulder width
    shoulder_left = skel[:, 11, :2]   # (T, 2)
    shoulder_right = skel[:, 12, :2]  # (T, 2)
    shoulder_width = np.linalg.norm(
        shoulder_right - shoulder_left, axis=1, keepdims=True
    )  # (T, 1)
    # Fallback: if shoulder landmarks are missing or width is 0/NaN, use 1.0
    shoulder_width = np.nan_to_num(shoulder_width, nan=1.0, posinf=1.0, neginf=1.0)
    shoulder_width = np.clip(shoulder_width, 0.01, None)
    skel[:, :, :2] /= shoulder_width[:, np.newaxis, :]

    return skel


def _to_fixed_length(skeleton: np.ndarray, target_t: int) -> np.ndarray:
    """Pad or uniformly sample to target_t frames."""
    T = skeleton.shape[0]
    if T >= target_t:
        indices = np.linspace(0, T - 1, target_t, dtype=int)
        return skeleton[indices]
    else:
        pad = np.tile(skeleton[-1:], (target_t - T, 1, 1))
        return np.concatenate([skeleton, pad], axis=0)


def _to_stgcn_format(skeleton: np.ndarray) -> np.ndarray:
    """Convert (T, V, C) to (C, T, V, 1)."""
    return np.transpose(skeleton, (2, 0, 1))[:, :, :, np.newaxis]


class SkeletonActionDataset(Dataset):
    """Dataset loading skeleton .npy files with labels from process_segments."""

    def __init__(
        self,
        skeleton_dir: str = SKELETON_DIR,
        db_url: str | None = None,
        label_map: Optional[Dict[str, int]] = None,
    ):
        self.label_map = label_map or LABEL_TO_IDX
        self.samples: List[Tuple[np.ndarray, int]] = []
        self._load(skeleton_dir, db_url)

    def _load(self, skeleton_dir: str, db_url: str | None) -> None:
        """Load skeleton files and match with DB labels."""
        # Fetch all labeled process segments
        session = get_session(db_url)
        try:
            segments = (
                session.query(ProcessSegment)
                .filter(
                    ProcessSegment.action.isnot(None),
                    ProcessSegment.action != "",
                )
                .all()
            )
            logger.info("Found %d labeled process segments", len(segments))
        finally:
            session.close()

        if not segments:
            logger.warning("No labeled segments found in database!")
            return

        # Count how many per action
        action_counts: Dict[str, int] = Counter()
        for seg in segments:
            action_counts[seg.action] += 1
        for action, count in sorted(action_counts.items()):
            logger.info("  %s: %d", action, count)

        # Index segments by camera_id for fast lookup
        segments_by_camera: Dict[str, List] = defaultdict(list)
        for seg in segments:
            segments_by_camera[seg.camera_id].append(seg)

        # P1.3: Match skeleton files to segment labels via video recording time
        # The skeleton filename (without _skeleton.npy) should match a video
        # file basename. Use the video file's modification time to find
        # overlapping process segments.
        skeleton_files = sorted([
            f for f in os.listdir(skeleton_dir) if f.endswith("_skeleton.npy")
        ])
        logger.info("Found %d skeleton files", len(skeleton_files))

        loaded = 0
        skipped = 0
        for fname in skeleton_files:
            fpath = os.path.join(skeleton_dir, fname)
            skeleton = np.load(fpath)  # (T, V, 3)

            # Extract video basename (e.g., "4e22ace7-..." from "4e22ace7-..._skeleton.npy")
            video_basename = fname.replace("_skeleton.npy", "")

            # Look for a matching video file to determine recording time
            video_path = self._find_video(video_basename)
            if video_path is None:
                # Fallback: try camera_id as skeleton basename
                matched_seg = self._match_by_camera_id(
                    video_basename, segments_by_camera
                )
                if matched_seg is None:
                    logger.warning(
                        "No video found for '%s' and no segment matched by camera_id. Skipping.",
                        video_basename,
                    )
                    skipped += 1
                    continue
                action = matched_seg.action
            else:
                # Match via video recording time
                matched_seg = self._match_by_timestamp(
                    video_path, segments
                )
                if matched_seg is None:
                    # Fallback: try matching video basename as camera_id
                    matched_seg = self._match_by_camera_id(
                        video_basename, segments_by_camera
                    )
                if matched_seg is None:
                    logger.warning(
                        "No matching segment for video '%s'. Skipping.",
                        video_basename,
                    )
                    skipped += 1
                    continue
                action = matched_seg.action

            label = self.label_map.get(action)
            if label is None:
                logger.warning("Unknown action label '%s' for '%s'", action, video_basename)
                skipped += 1
                continue

            # Preprocess
            skeleton = _normalize_skeleton(skeleton)
            skeleton = _to_fixed_length(skeleton, FIXED_T)
            skeleton = _to_stgcn_format(skeleton)  # (C, T, V, 1)
            self.samples.append((skeleton, label))
            loaded += 1

        logger.info(
            "Dataset loaded: %d samples (%d skipped)",
            loaded, skipped,
        )

    @staticmethod
    def _find_video(basename: str) -> Optional[str]:
        """Find a video file by basename (without extension) in VIDEO_DIR."""
        for ext in (".mp4", ".avi", ".mov", ".mkv"):
            candidate = os.path.join(VIDEO_DIR, f"{basename}{ext}")
            if os.path.isfile(candidate):
                return candidate
            # Some video files may have the basename directly as the filename
            # without extension matching
            candidate_no_ext = os.path.join(VIDEO_DIR, basename)
            if os.path.isfile(candidate_no_ext):
                return candidate_no_ext
        return None

    @staticmethod
    def _match_by_timestamp(
        video_path: str,
        segments: List,
    ) -> Optional:
        """
        Match a video file to process segments by file modification time.

        Uses the video file mtime as approximate recording time and finds
        the segment with the longest time overlap.
        """
        try:
            video_mtime = os.path.getmtime(video_path)
            video_dt = datetime.fromtimestamp(video_mtime, tz=timezone.utc)
        except OSError:
            return None

        best_seg = None
        best_overlap = 0.0

        for seg in segments:
            seg_start = seg.start_time
            seg_end = seg.end_time
            if seg_start.tzinfo is None:
                seg_start = seg_start.replace(tzinfo=timezone.utc)
            if seg_end.tzinfo is None:
                seg_end = seg_end.replace(tzinfo=timezone.utc)

            # The video recording time must fall within the segment range
            if seg_start <= video_dt <= seg_end:
                overlap = (seg_end - seg_start).total_seconds()
                if overlap > best_overlap:
                    best_overlap = overlap
                    best_seg = seg

        return best_seg

    @staticmethod
    def _match_by_camera_id(
        identifier: str,
        segments_by_camera: Dict[str, List],
    ) -> Optional:
        """
        Match a skeleton/video identifier to process segments by camera_id.

        The identifier (UUID from video file basename) is checked against
        camera_ids of stored segments. Returns the first matching segment.
        """
        for camera_id, segs in segments_by_camera.items():
            if identifier in camera_id or camera_id in identifier:
                return segs[0]
        return None

    def __len__(self) -> int:
        return len(self.samples)

    def __getitem__(self, idx: int) -> Tuple[torch.Tensor, torch.Tensor]:
        x, y = self.samples[idx]
        return torch.from_numpy(x).float(), torch.tensor(y, dtype=torch.long)


# ─── Training ───────────────────────────────────────────────────────


def train_epoch(
    model: nn.Module,
    loader: DataLoader,
    criterion: nn.Module,
    optimizer: optim.Optimizer,
    device: str,
) -> float:
    """Train for one epoch, return average loss."""
    model.train()
    total_loss = 0.0
    for batch_x, batch_y in loader:
        batch_x = batch_x.to(device)
        batch_y = batch_y.to(device)

        optimizer.zero_grad()
        logits = model(batch_x)
        loss = criterion(logits, batch_y)
        loss.backward()
        optimizer.step()
        total_loss += loss.item()

    return total_loss / len(loader)


@torch.no_grad()
def evaluate(
    model: nn.Module,
    loader: DataLoader,
    criterion: nn.Module,
    device: str,
) -> Tuple[float, float]:
    """Evaluate model, return (avg_loss, accuracy)."""
    model.eval()
    total_loss = 0.0
    correct = 0
    total = 0
    for batch_x, batch_y in loader:
        batch_x = batch_x.to(device)
        batch_y = batch_y.to(device)
        logits = model(batch_x)
        loss = criterion(logits, batch_y)
        total_loss += loss.item()
        preds = logits.argmax(dim=1)
        correct += (preds == batch_y).sum().item()
        total += batch_y.size(0)

    accuracy = correct / total if total > 0 else 0.0
    return total_loss / len(loader), accuracy


def main():
    logger.info("=" * 60)
    logger.info("ST-GCN Training")
    logger.info("=" * 60)

    # ── Dataset ──
    db_url = os.environ.get("MES_DB_URL", "sqlite:///data/mes.db")
    logger.info("Database: %s", db_url)
    logger.info("Skeleton dir: %s", SKELETON_DIR)

    full_dataset = SkeletonActionDataset(
        skeleton_dir=SKELETON_DIR,
        db_url=db_url,
    )

    if len(full_dataset) == 0:
        logger.error("No training samples. Exiting.")
        sys.exit(1)

    # ── Train/Val/Test split ──
    n = len(full_dataset)
    n_train = int(n * TRAIN_SPLIT)
    n_val = int(n * VALIDATION_SPLIT)
    n_test = n - n_train - n_val

    train_set, val_set, test_set = torch.utils.data.random_split(
        full_dataset,
        [n_train, n_val, n_test],
        generator=torch.Generator().manual_seed(42),
    )
    logger.info(
        "Split: train=%d val=%d test=%d",
        len(train_set), len(val_set), len(test_set),
    )

    train_loader = DataLoader(train_set, batch_size=BATCH_SIZE, shuffle=True)
    val_loader = DataLoader(val_set, batch_size=BATCH_SIZE) if len(val_set) > 0 else None
    test_loader = DataLoader(test_set, batch_size=BATCH_SIZE) if len(test_set) > 0 else None

    # ── Model ──
    device = "cuda" if torch.cuda.is_available() else "cpu"
    model = LightweightSTGCN(num_classes=NUM_CLASSES).to(device)
    params = sum(p.numel() for p in model.parameters() if p.requires_grad)
    logger.info("Model: %s | params=%d", device, params)

    criterion = nn.CrossEntropyLoss()
    optimizer = optim.AdamW(model.parameters(), lr=LEARNING_RATE, weight_decay=WEIGHT_DECAY)
    scheduler = optim.lr_scheduler.ReduceLROnPlateau(
        optimizer, mode="min", patience=10, factor=0.5,
    )

    # ── Training Loop ──
    best_val_loss = float("inf")
    best_epoch = 0
    patience = 20
    trigger = 0
    use_validation = val_loader is not None

    logger.info("Training %d epochs... (use_validation=%s)", EPOCHS, use_validation)
    for epoch in range(1, EPOCHS + 1):
        train_loss = train_epoch(model, train_loader, criterion, optimizer, device)

        if use_validation:
            val_loss, val_acc = evaluate(model, val_loader, criterion, device)
            scheduler.step(val_loss)
        else:
            val_loss = train_loss  # fallback: use train loss
            val_acc = 0.0
            scheduler.step(train_loss)

        if val_loss < best_val_loss:
            best_val_loss = val_loss
            best_epoch = epoch
            trigger = 0
            torch.save(model.state_dict(), MODEL_PATH)
            logger.info(
                "  Epoch %3d: train_loss=%.4f val_loss=%.4f val_acc=%.2f%% [SAVED]",
                epoch, train_loss, val_loss, val_acc * 100,
            )
        else:
            trigger += 1
            logger.info(
                "  Epoch %3d: train_loss=%.4f val_loss=%.4f val_acc=%.2f%%",
                epoch, train_loss, val_loss, val_acc * 100,
            )

        if trigger >= patience:
            logger.info("Early stopping at epoch %d", epoch)
            break

    # ── Final Evaluation ──
    logger.info("Best epoch: %d (val_loss=%.4f)", best_epoch, best_val_loss)
    if os.path.isfile(MODEL_PATH):
        model.load_state_dict(torch.load(MODEL_PATH))
    else:
        logger.warning("No saved model found, using current weights")
    model.eval()

    # Test set evaluation
    if test_loader is not None:
        test_loss, test_acc = evaluate(model, test_loader, criterion, device)
        logger.info("Test  set: loss=%.4f accuracy=%.2f%%", test_loss, test_acc * 100)

        # Per-class metrics
        all_preds = []
        all_labels = []
        with torch.no_grad():
            for batch_x, batch_y in test_loader:
                batch_x = batch_x.to(device)
                logits = model(batch_x)
                preds = logits.argmax(dim=1).cpu().numpy()
                all_preds.extend(preds.tolist())
                all_labels.extend(batch_y.numpy().tolist())
    else:
        logger.warning("No test set available")

    logger.info("Model saved to: %s", MODEL_PATH)
    logger.info("=" * 60)


if __name__ == "__main__":
    main()
