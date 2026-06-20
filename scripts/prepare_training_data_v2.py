"""
Prepare expanded training data for ST-GCN using sliding window augmentation.

Generates overlapping windows from each skeleton file, each labeled with the
video's action, to produce many more training samples.
"""
import sqlite3, os, sys
from datetime import datetime, timezone, timedelta
import numpy as np

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "mes-backend"))

# Map skeleton basename -> action label
SKELETON_ACTIONS = {
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

DB_PATH = "mes-backend/data/mes.db"
SKELETON_DIR = "mes-backend/data/skeleton"
VIDEO_DIR = "data/videos"

WINDOW_SIZE = 64     # frames per window (matches training FIXED_T)
WINDOW_STRIDE = 16   # overlap stride (75% overlap = more augmentation)

db = sqlite3.connect(DB_PATH)
c = db.cursor()

c.execute("DELETE FROM process_segments")
db.commit()

inserted = 0
for basename, action in sorted(SKELETON_ACTIONS.items()):
    skel_path = os.path.join(SKELETON_DIR, f"{basename}_skeleton.npy")
    if not os.path.isfile(skel_path):
        print(f"  SKIP: no skeleton for {basename}")
        continue

    # Find video for timestamp
    video_path = None
    for ext in (".mp4", ".avi", ".mov"):
        candidate = os.path.join(VIDEO_DIR, f"{basename}{ext}")
        if os.path.isfile(candidate):
            video_path = candidate
            break

    mtime = os.path.getmtime(video_path) if video_path else datetime.now().timestamp()
    base_time = datetime.fromtimestamp(mtime, tz=timezone.utc)

    skeleton = np.load(skel_path)
    T = skeleton.shape[0]  # total frames

    # Generate sliding windows
    n_windows = max(1, (T - WINDOW_SIZE) // WINDOW_STRIDE + 1)
    
    for i in range(n_windows):
        start_frame = i * WINDOW_STRIDE
        end_frame = min(start_frame + WINDOW_SIZE, T)

        # Time range for this window
        seg_start = base_time + timedelta(milliseconds=start_frame * 33)
        seg_end = base_time + timedelta(milliseconds=end_frame * 33)
        duration_ms = (end_frame - start_frame) * 33.0

        c.execute("""
            INSERT INTO process_segments
                (action, start_time, end_time, camera_id, duration_ms, confidence, station_id, shift, created_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            action,
            seg_start.isoformat(),
            seg_end.isoformat(),
            basename,
            round(duration_ms, 1),
            1.0,
            "WS-01",
            "morning",
            datetime.now(timezone.utc).isoformat(),
        ))
        inserted += 1

    print(f"  {basename:50s} T={T:4d} -> {n_windows:3d} windows ({action:12s})")

db.commit()
db.close()
print(f"\nTotal segments inserted: {inserted}")
print(f"Avg per class: {inserted / len(SKELETON_ACTIONS):.1f}")
