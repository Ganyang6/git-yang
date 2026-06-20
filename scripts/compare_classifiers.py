"""
Compare rule-based classifier vs ST-GCN on 9 skeleton sequences.

Usage:
    cd /home/yang/projects
    python3 scripts/compare_classifiers.py
"""
import sys, os, json
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "mes-backend"))

import numpy as np
from collections import Counter

# --- Rule-based classifier imports ---
from app.services.action_classifier import (
    extract_features,
    compute_window_stats,
    classify_action,
    FrameFeatures,
)
from app.models.schemas import ActionLabel

# --- ST-GCN imports ---
from app.ml.stgcn_model import STGCNClassifier, LABEL_NAMES

# --- Ground truth labels ---
SKELETON_ACTIONS = {
    "4e22ace7-06db-48d7-ab1d-2ec5e56d2456": ("assemble", ActionLabel.ASSEMBLE),
    "58b10756-46a4-4162-b27f-e09cd0f603bb": ("move", ActionLabel.MOVE),
    "5e87909e-0acc-460e-9f2e-fae339bf599a": ("inspect", ActionLabel.INSPECT),
    "944b5c0b-45d4-4a7f-b8d0-1bce78dece9a": ("reach", ActionLabel.REACH),
    "9a69e082-db39-40bc-a0f2-7ebaf189c799": ("grasp", ActionLabel.GRASP),
    "VCG42683051850": ("inspect", ActionLabel.INSPECT),
    "ffa4683a-ecad-4578-99a8-b6d45a157daa": ("wait", ActionLabel.WAIT),
    "屏幕录制 2026-03-26 224304": ("idle", ActionLabel.IDLE),
    "控制传送带上产品": ("release", ActionLabel.RELEASE),
}

LABEL_NAMES_LIST = LABEL_NAMES
LABEL_TO_ENUM = {
    name: getattr(ActionLabel, name.upper())
    for name in ["reach", "grasp", "move", "assemble", "release", "inspect", "wait", "hold", "idle"]
}
# Map ActionLabel enum to a comparable string
def label_to_str(label):
    if isinstance(label, ActionLabel):
        return label.value
    return str(label)

stgcn_model = STGCNClassifier()

skeleton_dir = "mes-backend/data/skeleton"
files = sorted([f for f in os.listdir(skeleton_dir) if f.endswith("_skeleton.npy")])

N_TO_SAMPLE = 64  # match training fixed T

results = []

for fname in files:
    basename = fname.replace("_skeleton.npy", "")
    gt_name, gt_enum = SKELETON_ACTIONS[basename]
    gt_label = label_to_str(gt_enum)
    
    skeleton = np.load(os.path.join(skeleton_dir, fname))  # (T, V, 3)

    # --- ST-GCN prediction ---
    stgcn_input = np.transpose(skeleton, (2, 0, 1))[:, :, :, np.newaxis]
    stgcn_result = stgcn_model.predict(stgcn_input)
    stgcn_pred = stgcn_result["action"]

    # --- Rule-based prediction ---
    # Convert skeleton (T, V, 3: x,y,confidence) to landmark dicts
    features_list = []
    for t in range(skeleton.shape[0]):
        landmarks = []
        for v in range(skeleton.shape[1]):
            x = float(skeleton[t, v, 0]) if not np.isnan(skeleton[t, v, 0]) else 0.0
            y = float(skeleton[t, v, 1]) if not np.isnan(skeleton[t, v, 1]) else 0.0
            z = float(skeleton[t, v, 2]) if not np.isnan(skeleton[t, v, 2]) else 0.0
            # Use available landmarks as visibility heuristic: non-NaN = visible
            vis = 0.0 if np.isnan(skeleton[t, v, 0]) else 1.0
            landmarks.append({"x": x, "y": y, "z": z, "visibility": vis})
        
        feat = extract_features(landmarks)
        if feat is not None:
            features_list.append(feat)
    
    if features_list:
        stats = compute_window_stats(features_list)
        rule_label, rule_conf, rule_region = classify_action(stats)
        rule_pred = label_to_str(rule_label)
    else:
        rule_pred = "unknown"
        rule_conf = 0.0

    stgcn_correct = (stgcn_pred == gt_label)
    rule_correct = (rule_pred == gt_label)
    
    results.append({
        "skeleton": basename,
        "ground_truth": gt_label,
        "stgcn_pred": stgcn_pred,
        "stgcn_conf": stgcn_result["confidence"],
        "stgcn_correct": stgcn_correct,
        "rule_pred": rule_pred,
        "rule_conf": round(rule_conf, 3),
        "rule_correct": rule_correct,
    })
    
    print(f"  {basename:45s} GT={gt_label:12s} ST-GCN={stgcn_pred:12s}({stgcn_result['confidence']:.2f}) {'✓' if stgcn_correct else '✗'} Rule={rule_pred:12s}({rule_conf:.2f}) {'✓' if rule_correct else '✗'}")

# Summary
stgcn_acc = sum(1 for r in results if r["stgcn_correct"]) / len(results) * 100
rule_acc = sum(1 for r in results if r["rule_correct"]) / len(results) * 100

print(f"\n{'='*80}")
print(f"Summary ({len(results)} skeleton sequences):")
print(f"  ST-GCN accuracy:      {stgcn_acc:.1f}%")
print(f"  Rule-based accuracy:  {rule_acc:.1f}%")
print(f"  ST-GCN > Rule?        {'YES' if stgcn_acc > rule_acc else 'NO'}")

print(f"\n=== Classification Report ===")
labels_used = sorted(set(r["ground_truth"] for r in results))
for lbl in labels_used:
    stgcn_c = sum(1 for r in results if r["ground_truth"] == lbl and r["stgcn_correct"])
    rule_c = sum(1 for r in results if r["ground_truth"] == lbl and r["rule_correct"])
    total = sum(1 for r in results if r["ground_truth"] == lbl)
    print(f"  {lbl:12s}: {total} samples | ST-GCN {stgcn_c}/{total} | Rule {rule_c}/{total}")

print(f"\nST-GCN confusion: {Counter(r['ground_truth'] for r in results if not r['stgcn_correct'])}")
print(f"Rule confusion:   {Counter(r['ground_truth'] for r in results if not r['rule_correct'])}")
print("Done.")
