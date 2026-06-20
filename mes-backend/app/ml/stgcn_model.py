"""
Lightweight ST-GCN (Spatial Temporal Graph Convolution) for action recognition.

Architecture (CPU-friendly, ~590K params):
  - 3 ST-GCN blocks with residual connections
  - Global average pooling over spatial & temporal dims
  - Fully connected classifier head (9 output classes)

Input shape:  (C, T, V, M) = (3, T, 33, 1)
  C: joint coordinates (x, y, confidence)
  T: temporal frames (variable, model handles via pool)
  V: 33 MediaPipe landmarks
  M: 1 person

Output: dict with 'action' (str) and 'confidence' (float)
"""

from __future__ import annotations

import logging
import os
from typing import Dict, List, Optional

import numpy as np
import torch
import torch.nn as nn
import torch.nn.functional as F

logger = logging.getLogger(__name__)

# ─── Constants ──────────────────────────────────────────────────────

NUM_JOINTS = 33
NUM_FEATURES = 3  # x, y, confidence
NUM_CLASSES = 9   # ActionLabel values: reach/grasp/move/assemble/release/inspect/wait/hold/idle
NUM_PEOPLE = 1

# MediaPipe skeleton adjacency for graph convolution (undirected)
# Each tuple (i, j) is a bone connection
LANDMARK_EDGES = [
    (0, 1), (1, 2), (2, 3), (3, 7),       # face left
    (0, 4), (4, 5), (5, 6), (6, 8),       # face right
    (9, 10),                                # mouth
    (11, 12),                               # shoulders
    (11, 13), (13, 15), (15, 17), (15, 19), (15, 21),  # left arm
    (12, 14), (14, 16), (16, 18), (16, 20), (16, 22),  # right arm
    (11, 23), (12, 24),                     # shoulders → hips
    (23, 24),                               # hips
    (23, 25), (25, 27), (27, 29), (27, 31),  # left leg
    (24, 26), (26, 28), (28, 30), (28, 32),  # right leg
]

LABEL_NAMES = [
    "reach", "grasp", "move", "assemble", "release",
    "inspect", "wait", "hold", "idle",
]


# ─── Graph Utilities ─────────────────────────────────────────────────

def _build_adjacency(edges: List[tuple], num_nodes: int) -> np.ndarray:
    """Build normalized adjacency matrix from edge list (undirected)."""
    adj = np.eye(num_nodes, dtype=np.float32)
    for i, j in edges:
        adj[i, j] = 1.0
        adj[j, i] = 1.0
    # Symmetric normalization: D^{-1/2} A D^{-1/2}
    d = np.sum(adj, axis=1)
    with np.errstate(divide='ignore', invalid='ignore'):
        d_inv_sqrt = np.power(d, -0.5, where=d > 0, out=np.zeros_like(d))
    adj_norm = d_inv_sqrt[:, None] * adj * d_inv_sqrt[None, :]
    return adj_norm


# Pre-compute adjacency matrix
ADJACENCY = _build_adjacency(LANDMARK_EDGES, NUM_JOINTS)


# ─── Graph Convolution Layer ─────────────────────────────────────────

class GraphConv(nn.Module):
    """Spatial graph convolution: aggregates neighbor features."""

    def __init__(self, in_channels: int, out_channels: int):
        super().__init__()
        self.conv = nn.Conv2d(in_channels, out_channels, kernel_size=1)
        self.bn = nn.BatchNorm2d(out_channels)

    def forward(self, x: torch.Tensor, adj: torch.Tensor) -> torch.Tensor:
        """
        x:   (N, C, T, V)  - batch, channels, time, vertices
        adj: (V, V)        - normalized adjacency matrix
        """
        N, C, T, V = x.shape
        # Reshape for graph convolution: (N*T, C, V)
        x = x.permute(0, 2, 3, 1)  # (N, T, V, C)
        x = x.reshape(N * T, V, C)
        # Graph conv: A @ X  — adjacency (V, V) @ features (V, C) = (V, C)
        adj = adj.to(x.device)
        x = torch.matmul(adj, x)  # (V, V) @ (N*T, V, C) → (N*T, V, C)
        x = x.reshape(N, T, V, -1).permute(0, 3, 1, 2)  # (N, C', T, V)
        x = self.conv(x)
        x = self.bn(x)
        return x


# ─── ST-GCN Block ────────────────────────────────────────────────────

class STGCNBlock(nn.Module):
    """Spatial-Temporal Graph Convolution block."""

    def __init__(self, in_channels: int, out_channels: int, residual: bool = True):
        super().__init__()
        self.gcn = GraphConv(in_channels, out_channels)
        self.tcn = nn.Sequential(
            nn.Conv2d(out_channels, out_channels, kernel_size=(3, 1),
                      padding=(1, 0)),
            nn.BatchNorm2d(out_channels),
            nn.ReLU(inplace=True),
        )
        self.residual = residual
        if residual and in_channels != out_channels:
            self.res_conv = nn.Conv2d(in_channels, out_channels, kernel_size=1)
            self.res_bn = nn.BatchNorm2d(out_channels)
        else:
            self.res_conv = None

    def forward(self, x: torch.Tensor, adj: torch.Tensor) -> torch.Tensor:
        res = x
        x = self.gcn(x, adj)
        x = F.relu(x)
        x = self.tcn(x)
        if self.residual:
            if self.res_conv is not None:
                res = self.res_conv(res)
                res = self.res_bn(res)
            x = x + res
        return x


# ─── Lightweight ST-GCN ─────────────────────────────────────────────

class LightweightSTGCN(nn.Module):
    """
    Lightweight ST-GCN for CPU inference.

    Architecture:
      - Input conv: 3 → 64
      - Block 1: 64 → 64 (residual)
      - Block 2: 64 → 128 (residual, stride=2 on temporal)
      - Block 3: 128 → 256 (residual, stride=2 on temporal)
      - GAP: global average pooling
      - FC: 256 → NUM_CLASSES
    """

    def __init__(self, num_classes: int = NUM_CLASSES, num_joints: int = NUM_JOINTS):
        super().__init__()
        self.register_buffer("adjacency", torch.from_numpy(ADJACENCY))

        # Initial feature embedding
        self.input_conv = nn.Conv2d(NUM_FEATURES, 64, kernel_size=1)
        self.input_bn = nn.BatchNorm2d(64)

        # ST-GCN blocks
        self.block1 = STGCNBlock(64, 64)
        self.block2 = STGCNBlock(64, 128)
        self.block3 = STGCNBlock(128, 256)

        # Temporal downsampling between blocks
        self.pool = nn.MaxPool2d(kernel_size=(2, 1))

        # Global pooling + classifier
        self.gap = nn.AdaptiveAvgPool2d((1, 1))
        self.fc = nn.Linear(256, num_classes)

    def forward(self, x: torch.Tensor) -> torch.Tensor:
        """
        x: (N, C, T, V, M) — standard ST-GCN input format
        Returns: (N, num_classes) logits
        """
        # Merge M dimension: (N, C, T, V, M) → (N, C, T, V)
        N, C, T, V, M = x.shape
        if M == 1:
            x = x.squeeze(-1)
        else:
            # Average over people dimension
            x = x.mean(dim=-1)

        adj = self.adjacency

        # Input embedding
        x = self.input_conv(x)
        x = self.input_bn(x)
        x = F.relu(x)

        # ST-GCN blocks with temporal downsampling
        x = self.block1(x, adj)
        x = self.pool(x)

        x = self.block2(x, adj)
        x = self.pool(x)

        x = self.block3(x, adj)

        # Global pooling + classify
        x = self.gap(x)  # (N, 256, 1, 1)
        x = x.view(N, -1)
        x = self.fc(x)   # (N, num_classes)

        return x


# ─── STGCNClassifier ────────────────────────────────────────────────

MODEL_DIR = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
    "data", "models",
)
MODEL_PATH = os.path.join(MODEL_DIR, "stgcn.pth")


class STGCNClassifier:
    """
    High-level classifier wrapping the ST-GCN model.

    Handles:
      - Model loading (pretrained or untrained)
      - Preprocessing (NCHW → graph format)
      - Inference
    """

    def __init__(self, model_path: str = MODEL_PATH, device: str = "auto"):
        self.device = self._resolve_device(device)
        self.model = LightweightSTGCN(num_classes=NUM_CLASSES).to(self.device)
        self.model.eval()
        self._load_weights(model_path)
        self._label_names = LABEL_NAMES

    @staticmethod
    def _resolve_device(device: str) -> str:
        if device == "auto":
            return "cuda" if torch.cuda.is_available() else "cpu"
        return device

    def _load_weights(self, model_path: str) -> None:
        """Load pretrained weights if available; otherwise use untrained model."""
        if os.path.isfile(model_path):
            try:
                state = torch.load(model_path, map_location=self.device)
                self.model.load_state_dict(state)
                logger.info("Loaded ST-GCN weights from %s", model_path)
            except Exception as e:
                logger.warning(
                    "Failed to load ST-GCN weights from %s: %s. Using untrained model.",
                    model_path, e,
                )
        else:
            logger.info(
                "No pretrained weights at %s. Using untrained model "
                "(predictions will be random). Train with train_stgcn.py.",
                model_path,
            )

    def count_params(self) -> int:
        """Return total trainable parameters."""
        return sum(p.numel() for p in self.model.parameters() if p.requires_grad)

    def predict(self, skeleton: np.ndarray) -> Dict[str, object]:
        """
        Classify a single skeleton sequence.

        Args:
            skeleton: (C, T, V, M) float32 numpy array

        Returns:
            dict with keys:
              - 'action': predicted action label (str)
              - 'confidence': softmax confidence (float)
              - 'logits': raw class logits (list[float])
        """
        # Validate input shape
        if skeleton.ndim != 4:
            raise ValueError(
                f"Expected 4D input (C,T,V,M), got shape {skeleton.shape}"
            )
        if skeleton.shape[0] != NUM_FEATURES:
            raise ValueError(
                f"Expected {NUM_FEATURES} channels, got {skeleton.shape[0]}"
            )
        if skeleton.shape[2] != NUM_JOINTS:
            raise ValueError(
                f"Expected {NUM_JOINTS} joints, got {skeleton.shape[2]}"
            )

        # P1.1: Guard against short sequences (T < 4 causes MaxPool2d(2,1) ×3 to
        # produce 0-dim temporal output, crashing the forward pass)
        T = skeleton.shape[1]
        if T < 4:
            logger.warning(
                "Sequence too short (T=%d < 4), returning default low-confidence result",
                T,
            )
            return {
                "action": "unknown",
                "confidence": 0.0,
                "logits": None,
            }

        with torch.no_grad():
            tensor = torch.from_numpy(skeleton).unsqueeze(0).to(self.device)
            logits = self.model(tensor)  # (1, num_classes)
            probs = F.softmax(logits, dim=1)  # (1, num_classes)

        confidence, pred_idx = torch.max(probs, dim=1)
        action = self._label_names[pred_idx.item()]

        return {
            "action": action,
            "confidence": float(confidence.item()),
            "logits": logits.squeeze(0).cpu().numpy().tolist(),
        }

    def predict_batch(self, skeletons: np.ndarray) -> List[Dict[str, object]]:
        """
        Classify a batch of skeleton sequences.

        Args:
            skeletons: (N, C, T, V, M) float32 numpy array

        Returns:
            List of result dicts

        Raises:
            ValueError: If input is not 5D (B, C, T, V, M)
        """
        # P1.2: Validate input is 5D; 4D input would crash during model forward
        if skeletons.ndim != 5:
            raise ValueError(
                f"Expected 5D input (B,C,T,V,M), got {skeletons.ndim}D with shape {skeletons.shape}"
            )

        with torch.no_grad():
            tensor = torch.from_numpy(skeletons).to(self.device)
            logits = self.model(tensor)  # (N, num_classes)
            probs = F.softmax(logits, dim=1)
            confidences, pred_indices = torch.max(probs, dim=1)
            labels = [self._label_names[i] for i in pred_indices.cpu().tolist()]

        return [
            {
                "action": labels[i],
                "confidence": float(confidences[i].item()),
                "logits": logits[i].cpu().numpy().tolist(),
            }
            for i in range(len(labels))
        ]
