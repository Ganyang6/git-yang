"""
Offline hand detection test - no Redis/Docker dependency.
Tests HandEstimator against a video file.

Usage:
    python test_hand_offline.py [video_path]
    python test_hand_offline.py                  # default: data/videos/230091.mp4
"""
import sys
import time
import numpy as np
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

import cv2
from hand_estimator import HandEstimator


def test_video_hand(video_path: str):
    cap = cv2.VideoCapture(video_path)
    if not cap.isOpened():
        print(f"ERROR: Cannot open {video_path}")
        return

    width = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
    height = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
    fps = cap.get(cv2.CAP_PROP_FPS) or 30.0
    total = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
    duration = total / fps if fps > 0 else 0

    print(f"Video: {Path(video_path).name}")
    print(f"  Resolution: {width}x{height} | FPS: {fps:.1f} | Frames: {total} | Duration: {duration:.1f}s")
    print()

    estimator = HandEstimator(
        num_hands=2,
        min_detection_confidence=0.5,
        min_tracking_confidence=0.5,
    )

    processed = 0
    left_detected = 0
    right_detected = 0
    both_detected = 0
    any_hand_detected = 0
    left_landmark_counts = []
    right_landmark_counts = []

    start = time.perf_counter()

    while True:
        ret, frame = cap.read()
        if not ret:
            break

        processed += 1
        result = estimator.estimate(frame, time.time())

        has_left = result.left_hand is not None and result.left_hand.is_valid()
        has_right = result.right_hand is not None and result.right_hand.is_valid()

        if has_left:
            left_detected += 1
            left_landmark_counts.append(len(result.left_hand.landmarks))
        if has_right:
            right_detected += 1
            right_landmark_counts.append(len(result.right_hand.landmarks))
        if has_left and has_right:
            both_detected += 1
        if has_left or has_right:
            any_hand_detected += 1

        if processed % 100 == 0:
            print(f"  Progress: {processed}/{total} frames...")

    elapsed = time.perf_counter() - start
    actual_fps = processed / elapsed if elapsed > 0 else 0
    cap.release()
    estimator.close()

    # Summary
    left_rate = left_detected / processed * 100 if processed else 0
    right_rate = right_detected / processed * 100 if processed else 0
    both_rate = both_detected / processed * 100 if processed else 0
    any_rate = any_hand_detected / processed * 100 if processed else 0
    avg_left_lm = np.mean(left_landmark_counts) if left_landmark_counts else 0
    avg_right_lm = np.mean(right_landmark_counts) if right_landmark_counts else 0

    print()
    print("=" * 55)
    print("HAND DETECTION RESULTS")
    print("=" * 55)
    print(f"  Total frames:       {processed}")
    print(f"  Processing FPS:     {actual_fps:.1f}")
    print(f"  Any hand detected:  {any_hand_detected}/{processed} ({any_rate:.1f}%)")
    print(f"  Left hand only:     {left_detected - both_detected} frames")
    print(f"  Right hand only:    {right_detected - both_detected} frames")
    print(f"  Both hands:         {both_detected}/{processed} ({both_rate:.1f}%)")
    print(f"  Left hand rate:     {left_detected}/{processed} ({left_rate:.1f}%)")
    print(f"  Right hand rate:    {right_detected}/{processed} ({right_rate:.1f}%)")
    if left_landmark_counts:
        print(f"  Left landmarks:      avg={avg_left_lm:.1f} min={min(left_landmark_counts)} max={max(left_landmark_counts)}")
    if right_landmark_counts:
        print(f"  Right landmarks:     avg={avg_right_lm:.1f} min={min(right_landmark_counts)} max={max(right_landmark_counts)}")
    print("=" * 55)

    # Verdict
    if any_rate >= 80:
        verdict = "PASS"
    elif any_rate >= 50:
        verdict = "ACCEPTABLE"
    else:
        verdict = "WEAK"
    print(f"  VERDICT: {verdict} (any hand detection rate: {any_rate:.1f}%)")


if __name__ == "__main__":
    default = str(Path(__file__).parent.parent / "data" / "videos" / "230091.mp4")
    video = sys.argv[1] if len(sys.argv) > 1 else default
    test_video_hand(video)
