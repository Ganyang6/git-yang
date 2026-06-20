"""
Direct ST-GCN training using all skeletons with sliding window augmentation.

Bypasses the database matching issue - loads all skeletons and their labels
directly from the camera_id→action mapping, creates many training samples
via overlapping windows, and trains the model.
"""
import sys, os, logging
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
)
logger = logging.getLogger(__name__)

import numpy as np
from collections import Counter
from pathlib import Path

import torch
import torch.nn as nn
import torch.optim as optim
from torch.utils.data import Dataset, DataLoader

from app.ml.stgcn_model import LightweightSTGCN, MODEL_PATH, LABEL_NAMES, NUM_CLASSES

# ─── Configuration ──────────────────────────────────────────────────
SKELETON_DIR = "mes-backend/data/skeleton"
FIXED_T = 64
WINDOW_STRIDE = 16   # frame stride for sliding window
BATCH_SIZE = 16
EPOCHS = 100
LEARNING_RATE = 1e-3
WEIGHT_DECAY = 1e-4
TRAIN_SPLIT = 0.7
VALIDATION_SPLIT = 0.15

LABEL_TO_IDX = {name: i for i, name in enumerate(LABEL_NAMES)}

# Ground truth by camera_id (skeleton basename)
SKELETON_LABELS = {
    "4e22ace7-06db-48d7-ab1d-2ec5e56d2456": "assemble",
    "58b10756-46a4-4162-b27f-e09cd0f603bb": "move",
    "5e87909e-0acc-460e-9f2e-fae339bf599a": "inspect",
    "944b5c0b-45d4-4a7f-b8d0-1bce78dece9a": "reach",
    "9a69e082-db39-40bc-a0f2-7ebaf189c799": "grasp",
    "VCG42683051850": "inspect",
    "ffa4683a-ecad-4578-99a8-b6d45a157daa": "wait",
    "屏幕录制 2026-03-26 224304": "idle",
    "控制传送带上产品": "release",
}


def normalize_skeleton(skeleton):
    """Normalize coordinates relative to hip center and shoulder width."""
    skel = skeleton.copy()
    nan_mask = np.isnan(skel[:, :, 0])
    skel[nan_mask] = 0.0

    hip_left = skel[:, 23, :2]
    hip_right = skel[:, 24, :2]
    hip_center = (hip_left + hip_right) / 2
    skel[:, :, :2] -= hip_center[:, np.newaxis, :]

    shoulder_left = skel[:, 11, :2]
    shoulder_right = skel[:, 12, :2]
    shoulder_width = np.linalg.norm(shoulder_right - shoulder_left, axis=1, keepdims=True)
    shoulder_width = np.nan_to_num(shoulder_width, nan=1.0, posinf=1.0, neginf=1.0)
    shoulder_width = np.clip(shoulder_width, 0.01, None)
    skel[:, :, :2] /= shoulder_width[:, np.newaxis, :]

    return skel


def to_stgcn_format(skeleton):
    """Convert (T, V, C) to (C, T, V, 1)."""
    return np.transpose(skeleton, (2, 0, 1))[:, :, :, np.newaxis]


# ─── Dataset ────────────────────────────────────────────────────────
class SlidingWindowDataset(Dataset):
    """Creates multiple training samples from each skeleton via sliding windows."""

    def __init__(self, label_map=None):
        self.label_map = label_map or LABEL_TO_IDX
        self.samples = []
        self._build()

    def _build(self):
        skeleton_files = sorted([
            f for f in os.listdir(SKELETON_DIR) if f.endswith("_skeleton.npy")
        ])

        action_counts = Counter()
        for fname in skeleton_files:
            basename = fname.replace("_skeleton.npy", "")
            action = SKELETON_LABELS.get(basename)
            if action is None:
                logger.warning("No label for %s, skipping", basename)
                continue
            label = self.label_map.get(action)
            if label is None:
                logger.warning("Unknown action '%s' for %s", action, basename)
                continue

            fpath = os.path.join(SKELETON_DIR, fname)
            skeleton = np.load(fpath)  # (T, V, 3)
            T = skeleton.shape[0]

            # Sliding windows
            n_windows = max(1, (T - FIXED_T) // WINDOW_STRIDE + 1)
            for i in range(n_windows):
                start = i * WINDOW_STRIDE
                end = start + FIXED_T
                window = skeleton[start:end].copy()
                window = normalize_skeleton(window)
                window = to_stgcn_format(window).astype(np.float32)
                self.samples.append((window, label))
                action_counts[action] += 1

        logger.info("Built dataset: %d samples from %d skeletons", len(self.samples), len(skeleton_files))
        for action, count in sorted(action_counts.items()):
            logger.info("  %s: %d", action, count)

    def __len__(self):
        return len(self.samples)

    def __getitem__(self, idx):
        x, y = self.samples[idx]
        return torch.from_numpy(x).float(), torch.tensor(y, dtype=torch.long)


# ─── Training ───────────────────────────────────────────────────────
def train_epoch(model, loader, criterion, optimizer, device):
    model.train()
    total_loss = 0.0
    for bx, by in loader:
        bx, by = bx.to(device), by.to(device)
        optimizer.zero_grad()
        loss = criterion(model(bx), by)
        loss.backward()
        optimizer.step()
        total_loss += loss.item()
    return total_loss / len(loader)


@torch.no_grad()
def evaluate(model, loader, criterion, device):
    model.eval()
    total_loss = 0.0
    correct = 0
    total = 0
    for bx, by in loader:
        bx, by = bx.to(device), by.to(device)
        logits = model(bx)
        loss = criterion(logits, by)
        total_loss += loss.item()
        correct += (logits.argmax(dim=1) == by).sum().item()
        total += by.size(0)
    return total_loss / len(loader), correct / total if total > 0 else 0.0


def main():
    logger.info("=" * 60)
    logger.info("ST-GCN Training (Sliding Window Augmentation)")
    logger.info("=" * 60)

    # Dataset
    full_dataset = SlidingWindowDataset()
    n = len(full_dataset)
    if n == 0:
        logger.error("No training samples. Exiting.")
        sys.exit(1)

    # Split
    n_train = int(n * TRAIN_SPLIT)
    n_val = int(n * VALIDATION_SPLIT)
    n_test = n - n_train - n_val

    train_set, val_set, test_set = torch.utils.data.random_split(
        full_dataset, [n_train, n_val, n_test],
        generator=torch.Generator().manual_seed(42),
    )
    logger.info("Split: train=%d val=%d test=%d", len(train_set), len(val_set), len(test_set))

    train_loader = DataLoader(train_set, batch_size=BATCH_SIZE, shuffle=True)
    val_loader = DataLoader(val_set, batch_size=BATCH_SIZE) if len(val_set) > 0 else None
    test_loader = DataLoader(test_set, batch_size=BATCH_SIZE) if len(test_set) > 0 else None

    # Model
    device = "cuda" if torch.cuda.is_available() else "cpu"
    model = LightweightSTGCN(num_classes=NUM_CLASSES).to(device)
    params = sum(p.numel() for p in model.parameters() if p.requires_grad)
    logger.info("Model: %s | params=%d", device, params)

    criterion = nn.CrossEntropyLoss()
    optimizer = optim.AdamW(model.parameters(), lr=LEARNING_RATE, weight_decay=WEIGHT_DECAY)
    scheduler = optim.lr_scheduler.ReduceLROnPlateau(optimizer, mode="min", patience=10, factor=0.5)

    # Training
    os.makedirs(os.path.dirname(MODEL_PATH), exist_ok=True)
    best_val_loss = float("inf")
    best_epoch = 0
    patience = 20
    trigger = 0

    for epoch in range(1, EPOCHS + 1):
        train_loss = train_epoch(model, train_loader, criterion, optimizer, device)

        if val_loader:
            val_loss, val_acc = evaluate(model, val_loader, criterion, device)
            scheduler.step(val_loss)
        else:
            val_loss, val_acc = train_loss, 0.0
            scheduler.step(train_loss)

        if val_loss < best_val_loss:
            best_val_loss = val_loss
            best_epoch = epoch
            trigger = 0
            torch.save(model.state_dict(), MODEL_PATH)
            logger.info("  Epoch %3d: train_loss=%.4f val_loss=%.4f val_acc=%.2f%% [SAVED]",
                        epoch, train_loss, val_loss, val_acc * 100)
        else:
            trigger += 1
            logger.info("  Epoch %3d: train_loss=%.4f val_loss=%.4f val_acc=%.2f%%",
                        epoch, train_loss, val_loss, val_acc * 100)

        if trigger >= patience:
            logger.info("Early stopping at epoch %d", epoch)
            break

    logger.info("Best epoch: %d (val_loss=%.4f)", best_epoch, best_val_loss)

    # Final test
    if test_loader:
        test_loss, test_acc = evaluate(model, test_loader, criterion, device)
        logger.info("Test set: loss=%.4f accuracy=%.2f%%", test_loss, test_acc * 100)
    else:
        logger.warning("No test set available")

    # Save
    if os.path.isfile(MODEL_PATH):
        model.load_state_dict(torch.load(MODEL_PATH))
    model.eval()
    torch.save(model.state_dict(), MODEL_PATH)
    logger.info("Model saved to: %s (%d params)", MODEL_PATH, params)
    logger.info("=" * 60)


if __name__ == "__main__":
    main()
