"""
从 NTU-120 预训练 ST-GCN 微调到我们的 9 类动作

策略:
  MMAction2 ST-GCN (17 joints, 10 blocks, PA-based graph conv)
    → 我们的 LightweightSTGCN (33 joints, 3 blocks, simple GraphConv)

  架构不匹配的处理:
    1. PA-based conv [out*3, in, 1, 1] → 3 partitions 均值 → [out, in, 1, 1]
    2. TCN kernel (9,1) → 中心裁剪 → (3,1)
    3. 分类头 120→9 随机初始化（通过 fine-tune 学习）
    4. 33 关节的邻接矩阵重新计算（不依赖预训练）

  预训练→我们的block映射:
    backbone.gcn.0    → input_conv (3→64)
    backbone.gcn.1    → block1 (64→64)
    backbone.gcn.4    → block2 (64→128)
    backbone.gcn.7    → block3 (128→256)
"""

import torch
import torch.nn as nn
import torch.optim as optim
import numpy as np
import os, sys, json

# ─── Pretrained mapping ──────────────────────────────────────────────

# Maps: (our_layer_key, pretrain_prefix, needs_partition_avg, needs_tcn_crop)
# needs_partition_avg=True  → reshape [out*3, in] → mean partitions → [out, in]
# needs_tcn_crop=True       → center crop temporal kernel 9→3

BLOCK_MAP = [
    # (our_block_idx, pretrain_block_idx, out_channels)
    (1, 1, 64),   # block1 ← gcn.1 (64→64)
    (2, 4, 128),  # block2 ← gcn.4 (64→128)
    (3, 7, 256),  # block3 ← gcn.7 (128→256)
]


def _avg_partitions(w: torch.Tensor, out_c: int) -> torch.Tensor:
    """Average 3 PA partitions: [out*3, in, ...] → [out, in, ...]
    Also handles 1D bias: [out*3] → [out]
    """
    if w.ndim == 1:
        # Bias: shape [out*3]
        return w.reshape(3, out_c).mean(dim=0)
    # Weight: shape [out*3, in, kH, kW]
    in_c = w.shape[1]
    kH, kW = w.shape[2], w.shape[3]
    w = w.reshape(3, out_c, in_c, kH, kW).mean(dim=0)
    return w


def _center_crop_tcn(w: torch.Tensor, target_k: int = 3) -> torch.Tensor:
    """Center crop temporal kernel: [out, in, 9, 1] → [out, in, target_k, 1]"""
    assert w.shape[2] >= target_k, f"Kernel too small: {w.shape[2]} < {target_k}"
    start = (w.shape[2] - target_k) // 2
    return w[:, :, start:start + target_k, :]


def load_pretrained(path: str, num_classes: int = 9):
    """Load MMAction2 pretrained weights into our LightweightSTGCN"""
    from app.ml.stgcn_model import LightweightSTGCN

    checkpoint = torch.load(path, map_location='cpu')
    state_dict = checkpoint['state_dict'] if 'state_dict' in checkpoint else checkpoint

    # Create new model
    model = LightweightSTGCN(num_classes=num_classes)

    # Build mapped state_dict
    mapped = {}
    skipped = []
    used = []

    # ── Input conv (gcn.0 → input_conv) ──
    p_w = state_dict.get('backbone.gcn.0.gcn.conv.weight')
    p_b = state_dict.get('backbone.gcn.0.gcn.conv.bias')
    if p_w is not None:
        w_avg = _avg_partitions(p_w, 64)  # [3, 64, 3, 1, 1] mean → [64, 3, 1, 1]
        mapped['input_conv.weight'] = w_avg
        mapped['input_conv.bias'] = _avg_partitions(p_b, 64)
        used.append('input_conv ← backbone.gcn.0')
    else:
        skipped.append('input_conv (gcn.0 not found)')

    # ── Block GCN conv + BN ──
    for our_idx, pt_idx, out_c in BLOCK_MAP:
        prefix = f'backbone.gcn.{pt_idx}'

        # GCN conv
        p_w = state_dict.get(f'{prefix}.gcn.conv.weight')
        p_b = state_dict.get(f'{prefix}.gcn.conv.bias')
        if p_w is not None:
            mapped[f'block{our_idx}.gcn.conv.weight'] = _avg_partitions(p_w, out_c)
            mapped[f'block{our_idx}.gcn.conv.bias'] = _avg_partitions(p_b, out_c)
            used.append(f'block{our_idx}.gcn.conv ← gcn.{pt_idx}')

        # GCN BN
        for bn_key in ['weight', 'bias', 'running_mean', 'running_var', 'num_batches_tracked']:
            k = f'{prefix}.gcn.bn.{bn_key}'
            if k in state_dict:
                mapped[f'block{our_idx}.gcn.bn.{bn_key}'] = state_dict[k].clone()
                used.append(f'block{our_idx}.gcn.bn.{bn_key}')

        # TCN conv (crop 9→3)
        p_w = state_dict.get(f'{prefix}.tcn.conv.weight')
        p_b = state_dict.get(f'{prefix}.tcn.conv.bias')
        if p_w is not None:
            mapped[f'block{our_idx}.tcn.0.weight'] = _center_crop_tcn(p_w, 3)
            mapped[f'block{our_idx}.tcn.0.bias'] = p_b.clone()
            used.append(f'block{our_idx}.tcn.0 ← gcn.{pt_idx} (crop 9→3)')

        # TCN BN
        for bn_key in ['weight', 'bias', 'running_mean', 'running_var', 'num_batches_tracked']:
            k = f'{prefix}.tcn.bn.{bn_key}'
            if k in state_dict:
                mapped[f'block{our_idx}.tcn.1.{bn_key}'] = state_dict[k].clone()

        # Residual conv + BN (only for blocks with channel change: block2, block3)
        res_k = f'{prefix}.residual.conv.weight'
        res_b = f'{prefix}.residual.conv.bias'
        if res_k in state_dict:
            mapped[f'block{our_idx}.res_conv.weight'] = state_dict[res_k].clone()
            mapped[f'block{our_idx}.res_conv.bias'] = state_dict[res_b].clone()
            used.append(f'block{our_idx}.res_conv ← gcn.{pt_idx}.residual')
            for bn_key in ['weight', 'bias', 'running_mean', 'running_var', 'num_batches_tracked']:
                k = f'{prefix}.residual.bn.{bn_key}'
                if k in state_dict:
                    mapped[f'block{our_idx}.res_bn.{bn_key}'] = state_dict[k].clone()

    # ── FC layer: 随机初始化（不加载预训练，120→9 无法直接映射）──
    skipped.append('fc (120→9, 随机初始化)')

    # Load weights
    missing, unexpected = model.load_state_dict(mapped, strict=False)

    print(f"加载预训练权重: {path}")
    print(f"  已映射: {len(mapped)}/{len(model.state_dict())} 个参数")
    for u in used:
        print(f"  ✅ {u}")
    print(f"  未使用:")
    for s in skipped:
        print(f"  ⏭️  {s}")
    if missing:
        print(f"  缺失(已随机初始化):")
        for m in missing:
            if m not in mapped:
                # Skip the adjacency buffer (it's computed, not loaded)
                if m != 'adjacency':
                    print(f"    {m}")
    if unexpected:
        print(f"  ⚠️ 多余(未使用): {len(unexpected)}个参数")

    return model


# ─── Training ────────────────────────────────────────────────────────

def train(model, train_data, train_labels, val_data, val_labels,
          epochs=50, lr=0.001, weight_decay=1e-4):
    """Fine-tune the model"""
    criterion = nn.CrossEntropyLoss()
    optimizer = optim.AdamW(model.parameters(), lr=lr, weight_decay=weight_decay)
    scheduler = optim.lr_scheduler.CosineAnnealingLR(optimizer, T_max=epochs)

    device = torch.device('cuda' if torch.cuda.is_available() else 'cpu')
    print(f"  设备: {device}")
    model = model.to(device)

    train_data = torch.FloatTensor(train_data).to(device)
    train_labels = torch.LongTensor(train_labels).to(device)
    val_data = torch.FloatTensor(val_data).to(device)
    val_labels = torch.LongTensor(val_labels).to(device)

    best_acc = 0
    best_epoch = 0

    for epoch in range(epochs):
        model.train()
        optimizer.zero_grad()
        outputs = model(train_data)
        loss = criterion(outputs, train_labels)
        loss.backward()
        optimizer.step()

        # Validation
        model.eval()
        with torch.no_grad():
            val_outputs = model(val_data)
            val_loss = criterion(val_outputs, val_labels)
            _, predicted = torch.max(val_outputs, 1)
            val_acc = (predicted == val_labels).float().mean().item()

        scheduler.step()

        if (epoch + 1) % 5 == 0 or val_acc > best_acc:
            lr_now = optimizer.param_groups[0]['lr']
            print(f"  Epoch {epoch+1:3d}/{epochs}: "
                  f"loss={loss.item():.4f}, val_loss={val_loss.item():.4f}, "
                  f"val_acc={val_acc:.4f}, lr={lr_now:.6f}")

        if val_acc > best_acc:
            best_acc = val_acc
            best_epoch = epoch + 1
            save_dir = os.path.join(os.path.dirname(__file__), '..', '..', 'data', 'models')
            os.makedirs(save_dir, exist_ok=True)
            torch.save(model.state_dict(), os.path.join(save_dir, 'stgcn_finetuned.pth'))

    print(f"\n✅ 最佳验证准确率: {best_acc:.4f} (Epoch {best_epoch})")
    return model


# ─── Main ────────────────────────────────────────────────────────────

if __name__ == '__main__':
    import time
    t0 = time.time()

    # 加载数据
    _script_dir = os.path.dirname(os.path.abspath(__file__))
    _project_root = os.path.join(_script_dir, '..', '..')  # mes-backend/
    npz_path = os.path.join(_project_root, 'data', 'ha4m_converted.npz')
    print(f"加载数据: {npz_path}")
    data = np.load(npz_path)
    X = data['data']    # (N, C, T, V, M)
    y = data['labels']  # (N,)
    print(f"  样本数: {len(X)}, 特征形状: {X.shape}, 类别: {len(np.unique(y))}")
    print(f"  类别分布: {dict(zip(*np.unique(y, return_counts=True)))}")

    # 划分 train/val/test
    from sklearn.model_selection import train_test_split
    X_train, X_test, y_train, y_test = train_test_split(
        X, y, test_size=0.15, random_state=42, stratify=y)
    X_train, X_val, y_train, y_val = train_test_split(
        X_train, y_train, test_size=0.15, random_state=42, stratify=y_train)

    print(f"\n数据集划分:")
    print(f"  训练: {len(X_train)}")
    print(f"  验证: {len(X_val)}")
    print(f"  测试: {len(X_test)}")

    # 加载预训练模型
    pt_path = os.path.join(_project_root, 'data', 'models', 'pretrained_stgcn_ntu120.pth')
    print(f"\n加载预训练权重: {pt_path}")
    model = load_pretrained(pt_path)

    # 参数量
    total_params = sum(p.numel() for p in model.parameters() if p.requires_grad)
    print(f"  可训练参数量: {total_params:,}")

    # Fine-tune on CPU with more epochs since small dataset
    print(f"\n开始 Fine-tune (50 epochs)...")
    model = train(model, X_train, y_train, X_val, y_val, epochs=50)

    # 最终测试
    device = next(model.parameters()).device
    model.eval()
    X_test_t = torch.FloatTensor(X_test).to(device)
    y_test_t = torch.LongTensor(y_test).to(device)

    with torch.no_grad():
        outputs = model(X_test_t)
        _, predicted = torch.max(outputs, 1)
        test_acc = (predicted == y_test_t).float().mean().item()

        # Per-class accuracy
        from sklearn.metrics import classification_report
        y_pred = predicted.cpu().numpy()
        y_true = y_test
        from app.ml.stgcn_model import LABEL_NAMES
        target_names = [f"{i}:{LABEL_NAMES[i]}" for i in range(len(LABEL_NAMES))]
        report = classification_report(y_true, y_pred, target_names=target_names,
                                       zero_division=0, digits=4)

    elapsed = time.time() - t0
    print(f"\n{'='*50}")
    print(f"✅ 测试准确率: {test_acc:.4f} ({test_acc*100:.2f}%)")
    print(f"耗时: {elapsed:.1f}s")
    print(f"\n分类报告:")
    print(report)

    # 保存模型信息
    info = {
        "model": "stgcn_finetuned.pth",
        "pretrained_from": "NTU-120 (MMAction2)",
        "test_accuracy": round(test_acc, 4),
        "test_accuracy_pct": round(test_acc * 100, 2),
        "num_params": total_params,
        "epochs": 50,
        "training_samples": len(X_train),
        "val_samples": len(X_val),
        "test_samples": len(X_test),
    }
    info_path = os.path.join(_project_root, 'data', 'models', 'stgcn_finetuned_info.json')
    with open(info_path, 'w') as f:
        json.dump(info, f, indent=2)
    print(f"模型信息已保存: {info_path}")
