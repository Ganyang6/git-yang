"""Populate process_segments with skeleton-matched action labels for ST-GCN training."""
import sqlite3, os
from datetime import datetime, timezone, timedelta
import numpy as np

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

VIDEO_DIR = "data/videos"
SKELETON_DIR = "mes-backend/data/skeleton"

db = sqlite3.connect("data/mes.db")
c = db.cursor()

# Clear old segments
c.execute("DELETE FROM process_segments")
db.commit()

inserted = 0
for basename, action in SKELETON_ACTIONS.items():
    video_path = None
    for ext in (".mp4", ".avi", ".mov"):
        candidate = os.path.join(VIDEO_DIR, f"{basename}{ext}")
        if os.path.isfile(candidate):
            video_path = candidate
            break

    skel_path = os.path.join(SKELETON_DIR, f"{basename}_skeleton.npy")
    if not os.path.isfile(skel_path):
        print(f"  SKIP: no skeleton for {basename}")
        continue

    mtime = os.path.getmtime(video_path) if video_path else datetime.now().timestamp()
    record_time = datetime.fromtimestamp(mtime, tz=timezone.utc)

    skeleton = np.load(skel_path)
    T = skeleton.shape[0]
    est_duration_ms = T * 33

    segment_start = record_time
    segment_end = record_time + timedelta(milliseconds=est_duration_ms)

    camera_id = basename

    c.execute("""
        INSERT INTO process_segments
            (action, start_time, end_time, camera_id, duration_ms, confidence, station_id, shift, created_at)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
    """, (
        action,
        segment_start.isoformat(),
        segment_end.isoformat(),
        camera_id,
        round(est_duration_ms, 1),
        1.0,
        "WS-01",
        "morning",
        datetime.now(timezone.utc).isoformat(),
    ))
    inserted += 1
    print(f"  INSERT: {basename:50s} -> action={action:12s} T={T:4d} dur={est_duration_ms:.0f}ms")

db.commit()
db.close()
print(f"\nTotal segments inserted: {inserted}")
