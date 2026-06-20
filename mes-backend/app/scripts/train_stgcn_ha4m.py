"""
Train ST-GCN model using synthetic HA4M dataset (.npz format).

This bypasses the DB-dependent training pipeline and trains directly
on the synthetic skeleton data for evaluation purposes.

Usage:
    cd mes-backend && python app/scripts/train_stgcn_ha4m.py
"""

from __future__ import annotations

import logging
import os
import sys

import numpy as np
import torch
import torch.nn as nn
import torch.optim as optim
from torch.utils.data import Dataset, DataLoader

_project_root = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
if _project_root not in sys.path:
    sys.path.insert(0, _project_root)

from app.ml.stgcn_model import LightweightSTGCN, MODEL_PATH, LABEL_NAMES, NUM_CLASSES

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger(__name__)

# ─── Config ────────────────────────────────────────────────────────────

NPZ_PATH = os.path.join(_project_root, "data", "ha4m_converted.npz")
BATCH_SIZE = 8
EPOCHS = 200
LEARNING_RATE = 1e-3
WEIGHT_DECAY = 1e-4
TRAIN_SPLIT = 0.7
VAL_SPLIT = 0.15
TEST_SPLIT = 0.15
MODEL_DIR = os.path.dirname(MODEL_PATH)

os.makedirs(MODEL_DIR, exist_ok=True)


# ─── Dataset ────────────────────────────────────────────────────────────

class NPZDataset(Dataset):
    """Dataset loading skeleton data from .npz file."""

    def __init__(self, data: np.ndarray, labels: np.ndarray):
        self.data = data  # (N, C, T, V, M)
        self.labels = labels  # (N,)

    def __len__(self) -> int:
        return len(self.data)

    def __getitem__(self, idx: int) -> tuple[torch.Tensor, torch.Tensor]:
        x = torch.from_numpy(self.data[idx]).float()
        y = torch.tensor(self.labels[idx], dtype=torch.long)
        return x, y


# ─── Training ───────────────────────────────────────────────────────────

def train_epoch(model, loader, criterion, optimizer, device):
    model.train()
    total_loss = 0.0
    for batch_x, batch_y in loader:
        batch_x, batch_y = batch_x.to(device), batch_y.to(device)
        optimizer.zero_grad()
        logits = model(batch_x)
        loss = criterion(logits, batch_y)
        loss.backward()
        optimizer.step()
        total_loss += loss.item()
    return total_loss / len(loader)


@torch.no_grad()
def evaluate(model, loader, criterion, device):
    model.eval()
    total_loss, correct, total = 0.0, 0, 0
    all_preds, all_labels = [], []
    for batch_x, batch_y in loader:
        batch_x, batch_y = batch_x.to(device), batch_y.to(device)
        logits = model(batch_x)
        loss = criterion(logits, batch_y)
        total_loss += loss.item()
        preds = logits.argmax(dim=1)
        correct += (preds == batch_y).sum().item()
        total += batch_y.size(0)
        all_preds.extend(preds.cpu().numpy().tolist())
        all_labels.extend(batch_y.cpu().numpy().tolist())
    acc = correct / total if total > 0 else 0.0
    return total_loss / len(loader), acc, all_preds, all_labels


def main():
    logger.info("=" * 60)
    logger.info("ST-GCN Training: Synthetic HA4M Dataset")
    logger.info("=" * 60)

    # ── Load data ──
    if not os.path.isfile(NPZ_PATH):
        logger.error("NPZ file not found: %s", NPZ_PATH)
        logger.error("Run `generate_ha4m_synthetic.py` first.")
        sys.exit(1)

    data_npz = np.load(NPZ_PATH, allow_pickle=True)
    data = data_npz["data"]       # (N, C, T, V, M)
    labels = data_npz["labels"]   # (N,)
    action_names = data_npz["action_names"]
    data_npz.close()

    logger.info("Loaded %d samples, shape=%s", len(data), data.shape)
    logger.info("Actions: %s", list(action_names))

    # Balance check
    from collections import Counter
    dist = Counter(labels.tolist())
    for label, count in sorted(dist.items()):
        logger.info("  Label %d (%s): %d", label, action_names[label], count)

    # ── Split ──
    n = len(data)
    n_train = int(n * TRAIN_SPLIT)
    n_val = int(n * VAL_SPLIT)
    n_test = n - n_train - n_val

    indices = np.random.RandomState(42).permutation(n)
    train_idx = indices[:n_train]
    val_idx = indices[n_train:n_train + n_val]
    test_idx = indices[n_train + n_val:]

    train_set = NPZDataset(data[train_idx], labels[train_idx])
    val_set = NPZDataset(data[val_idx], labels[val_idx])
    test_set = NPZDataset(data[test_idx], labels[test_idx])

    logger.info("Split: train=%d val=%d test=%d", len(train_set), len(val_set), len(test_set))

    train_loader = DataLoader(train_set, batch_size=BATCH_SIZE, shuffle=True)
    val_loader = DataLoader(val_set, batch_size=BATCH_SIZE)
    test_loader = DataLoader(test_set, batch_size=BATCH_SIZE)

    # ── Model ──
    device = "cuda" if torch.cuda.is_available() else "cpu"
    model = LightweightSTGCN(num_classes=NUM_CLASSES).to(device)
    params = sum(p.numel() for p in model.parameters() if p.requires_grad)
    logger.info("Model on %s | params=%d", device, params)

    criterion = nn.CrossEntropyLoss()
    optimizer = optim.AdamW(model.parameters(), lr=LEARNING_RATE, weight_decay=WEIGHT_DECAY)
    scheduler = optim.lr_scheduler.ReduceLROnPlateau(
        optimizer, mode="min", patience=10, factor=0.5,
    )

    # ── Train ──
    best_val_loss = float("inf")
    best_val_acc = 0.0
    best_epoch = 0
    patience = 30
    trigger = 0

    logger.info("Training %d epochs...", EPOCHS)
    for epoch in range(1, EPOCHS + 1):
        train_loss = train_epoch(model, train_loader, criterion, optimizer, device)

        if len(val_set) > 0:
            val_loss, val_acc, _, _ = evaluate(model, val_loader, criterion, device)
            scheduler.step(val_loss)
        else:
            val_loss = train_loss
            val_acc = 0.0

        if val_loss < best_val_loss:
            best_val_loss = val_loss
            best_val_acc = val_acc
            best_epoch = epoch
            trigger = 0
            torch.save(model.state_dict(), MODEL_PATH)
            logger.info(
                "  Epoch %3d: train_loss=%.4f val_loss=%.4f val_acc=%.2f%% [SAVED]",
                epoch, train_loss, val_loss, val_acc * 100,
            )
        else:
            trigger += 1
            if epoch % 10 == 0 or trigger == 1:
                logger.info(
                    "  Epoch %3d: train_loss=%.4f val_loss=%.4f val_acc=%.2f%%",
                    epoch, train_loss, val_loss, val_acc * 100,
                )

        if trigger >= patience:
            logger.info("Early stopping at epoch %d", epoch)
            break

    # ── Final evaluation ──
    logger.info("Best epoch: %d (val_loss=%.4f, val_acc=%.2f%%)", best_epoch, best_val_loss, best_val_acc * 100)

    if os.path.isfile(MODEL_PATH):
        model.load_state_dict(torch.load(MODEL_PATH, map_location=device))

    if len(test_set) > 0:
        test_loss, test_acc, test_preds, test_labels = evaluate(
            model, test_loader, criterion, device
        )
        logger.info("Test set: loss=%.4f accuracy=%.2f%%", test_loss, test_acc * 100)

        # Per-class metrics
        from sklearn.metrics import classification_report, confusion_matrix
        try:
            report = classification_report(
                test_labels, test_preds,
                target_names=list(action_names),
                digits=3,
            )
            logger.info("Per-class classification report:\n%s", report)

            cm = confusion_matrix(test_labels, test_preds)
            logger.info("Confusion matrix:\n%s", cm)
        except ImportError:
            logger.warning("sklearn not available, skipping per-class metrics")

    logger.info("Model saved to: %s (%d KB)", MODEL_PATH,
                os.path.getsize(MODEL_PATH) / 1024 if os.path.isfile(MODEL_PATH) else 0)
    logger.info("=" * 60)


if __name__ == "__main__":
    main()
