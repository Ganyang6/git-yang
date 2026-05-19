"""
Offline video pose detection test - no Redis dependency.
Uses the project's own PoseEstimator module.

Usage:
    python test_video_offline.py [--video PATH] [--max-frames N]
"""
import argparse
import json
import time
import sys
import threading
import logging
from pathlib import Path

import cv2

# Set up logging
logging.basicConfig(level=logging.WARNING, format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)


def _safe_release(cap, timeout: float = 3.0, source_name: str = "source"):
    """Release a VideoCapture with timeout protection.

    OpenCV VideoCapture.release() can block indefinitely when the
    underlying V4L2 driver hangs (e.g. USB hot-plug, device fd race).
    This wrapper runs release() in a daemon thread and gives up after
    *timeout* seconds.
    """
    if cap is None:
        return
    def _release():
        try:
            cap.release()
        except Exception as e:
            logger.warning("Error releasing %s: %s", source_name, e)
    t = threading.Thread(target=_release, daemon=True)
    t.start()
    t.join(timeout=timeout)
    if t.is_alive():
        logger.warning(
            "%s release did not complete within %.1fs, "
            "likely V4L2 driver hang (abandoning daemon thread)",
            source_name, timeout,
        )


def _safe_read(cap, timeout: float = 5.0):
    """Read a frame from VideoCapture with timeout protection.

    cv2.VideoCapture.read() can block indefinitely when the underlying
    native C I/O stalls (Docker + WSL2 + NTFS bind mount, damaged file
    headers, V4L2 driver hangs).  This wrapper runs read() in a daemon
    thread and returns (False, None) if it does not complete within
    *timeout* seconds.

    Args:
        cap: cv2.VideoCapture instance.
        timeout: Maximum seconds to wait for read() to return.

    Returns:
        (ret, frame): Same as cap.read(), or (False, None) on timeout/error.
    """
    if cap is None or not cap.isOpened():
        return False, None

    result: dict = {"ret": False, "frame": None}

    def _read():
        try:
            result["ret"], result["frame"] = cap.read()
        except Exception as exc:
            logger.warning(
                "cv2.VideoCapture.read() raised %s: %s",
                type(exc).__name__, exc,
            )
            result["ret"] = False

    t = threading.Thread(target=_read, daemon=True)
    t.start()
    t.join(timeout=timeout)

    if t.is_alive():
        logger.warning(
            "cv2.VideoCapture.read() blocked for %.1fs, aborting "
            "(possible Docker/WSL2/NTFS mount issue or corrupted video)",
            timeout,
        )
        return False, None

    return result["ret"], result["frame"]

sys.path.insert(0, str(Path(__file__).parent))

from pose_estimator import PoseEstimator


def test_single_video(video_path: str, max_frames: int = 0) -> dict:
    """Run pose estimation on a single video file."""
    cap = cv2.VideoCapture(video_path)
    if not cap.isOpened():
        return {"error": f"Cannot open video: {video_path}"}

    total_frames = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
    fps = cap.get(cv2.CAP_PROP_FPS) or 30.0
    width = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
    height = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
    duration = total_frames / fps if fps > 0 else 0.0

    print(f"\n{'='*60}")
    print(f"Video: {video_path}")
    print(f"Resolution: {width}x{height} | FPS: {fps:.1f} | "
          f"Frames: {total_frames} | Duration: {duration:.1f}s")
    print(f"{'='*60}")

    estimator = PoseEstimator(
        model_complexity=1,
        smooth=True,
        min_detection_confidence=0.5,
        min_tracking_confidence=0.5,
    )

    frames_to_process = max_frames if max_frames > 0 else total_frames
    processed = 0
    pose_detected = 0
    pose_scores = []
    frame_interval = 1.0 / fps if fps > 0 else 0.0
    start_time = time.perf_counter()

    while processed < frames_to_process:
        ret, frame = _safe_read(cap, timeout=5.0)
        if not ret:
            break

        processed += 1
        frame_timestamp_ms = int(processed * 1000 / fps) if fps > 0 else processed * 33

        result = estimator.estimate(frame, frame_timestamp_ms)

        if result.landmarks:
            pose_detected += 1
            scores = [lm.visibility for lm in result.landmarks]
            avg_score = sum(scores) / len(scores) if scores else 0.0
            pose_scores.append(avg_score)

        if processed % max(1, int(fps)) == 0:
            elapsed = time.perf_counter() - start_time
            actual_fps = processed / elapsed if elapsed > 0 else 0.0
            print(f"  Frame {processed}/{frames_to_process} | "
                  f"Pose: {pose_detected}/{processed} | "
                  f"FPS: {actual_fps:.1f}")

    elapsed = time.perf_counter() - start_time
    _safe_release(cap, timeout=3.0, source_name=str(video_path))
    estimator.close(timeout=5.0)

    detection_rate = (pose_detected / processed * 100) if processed > 0 else 0.0
    avg_pose_score = (sum(pose_scores) / len(pose_scores)) if pose_scores else 0.0
    actual_fps = processed / elapsed if elapsed > 0 else 0.0

    stats = {
        "video": str(video_path),
        "resolution": f"{width}x{height}",
        "fps": round(fps, 1),
        "total_frames": total_frames,
        "duration_s": round(duration, 1),
        "frames_processed": processed,
        "pose_detected_frames": pose_detected,
        "detection_rate_pct": round(detection_rate, 1),
        "avg_pose_score": round(avg_pose_score, 4),
        "processing_fps": round(actual_fps, 1),
        "processing_time_s": round(elapsed, 1),
    }

    print(f"\n{'='*60}")
    print(f"Results:")
    print(f"  Frames processed:  {processed}/{total_frames}")
    print(f"  Pose detected:     {pose_detected} ({detection_rate:.1f}%)")
    print(f"  Avg pose score:    {avg_pose_score:.4f}")
    print(f"  Processing FPS:    {actual_fps:.1f}")
    print(f"  Processing time:   {elapsed:.1f}s")
    print(f"{'='*60}")

    return stats


def main():
    parser = argparse.ArgumentParser(description="Offline video pose detection test")
    parser.add_argument("--video", type=str, default="", help="Single video file path")
    parser.add_argument("--max-frames", type=int, default=0, help="Max frames to process (0=all)")
    args = parser.parse_args()

    videos_dir = Path(__file__).parent.parent / "data" / "videos"

    if args.video:
        video_files = [Path(args.video)]
    else:
        video_files = sorted(videos_dir.glob("*.mp4"))

    if not video_files:
        print("No video files found.")
        sys.exit(1)

    print(f"Found {len(video_files)} video file(s) to test")
    all_results = []

    for vf in video_files:
        result = test_single_video(str(vf), max_frames=args.max_frames)
        if "error" not in result:
            all_results.append(result)
        else:
            print(f"ERROR: {result['error']}")

    # Summary
    if len(all_results) > 1:
        print(f"\n{'#'*60}")
        print(f"SUMMARY - {len(all_results)} videos tested")
        print(f"{'#'*60}")
        for r in all_results:
            name = Path(r['video']).name
            print(f"  {name:20s} | "
                  f"Detection: {r['detection_rate_pct']:5.1f}% | "
                  f"Avg score: {r['avg_pose_score']:.4f} | "
                  f"FPS: {r['processing_fps']:5.1f}")

    # Verdict
    print(f"\n--- Verdict ---")
    for r in all_results:
        name = Path(r['video']).name
        rate = r['detection_rate_pct']
        if rate >= 50:
            print(f"  PASS:  {name} - detection rate {rate:.1f}%")
        elif rate >= 10:
            print(f"  WEAK:  {name} - detection rate {rate:.1f}% (may need better video)")
        else:
            print(f"  FAIL:  {name} - detection rate {rate:.1f}% (no visible human figures)")


if __name__ == "__main__":
    main()
