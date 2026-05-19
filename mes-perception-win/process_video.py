#!/usr/bin/env python3
"""精简视频处理管线 - 替代 main.py 解决卡死问题"""
import sys, os, json, time, shutil, logging
sys.path.insert(0, '/app')

import cv2
from pose_estimator import PoseEstimator
from video_optimizer import VideoOptimizerPipeline
from app.perception.redis_adapter import PerceptionAdapter
from hand_estimator import HandEstimator, HandAngleCalculator

from main import _publish_video_progress, _safe_redis_call

# ── Logging configuration (same as main.py) ──────────────────────────
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s [%(levelname)s] %(name)s: %(message)s',
    datefmt='%H:%M:%S',
    stream=sys.stdout,
    force=True,
)
sys.stdout.reconfigure(line_buffering=True)
sys.stderr.reconfigure(line_buffering=True)
logger = logging.getLogger(__name__)

REDIS_URL = os.environ.get('REDIS_URL', 'redis://:mes-redis-2026@redis:6379/0')
MAX_RES = int(os.environ.get('MAX_RESOLUTION', '640'))
INTERVAL = int(os.environ.get('DETECTION_INTERVAL', '6'))


def process(video_path, station_id='WS-01', task_id=''):
    os.makedirs('/tmp/mes-videos', exist_ok=True)
    tmp = f'/tmp/mes-videos/{os.path.basename(video_path)}'
    shutil.copy2(video_path, tmp)

    cap = cv2.VideoCapture(tmp)
    cap.set(cv2.CAP_PROP_BUFFERSIZE, 1)
    total = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))

    pe = PoseEstimator(model_complexity=2)
    he = HandEstimator(num_hands=2, min_detection_confidence=0.5, min_tracking_confidence=0.5)
    opt = VideoOptimizerPipeline(max_resolution=MAX_RES, detection_interval=INTERVAL)
    adapter = PerceptionAdapter(REDIS_URL)

    seq, pose_frames = 0, 0
    consecutive_failures = 0
    total_failures = 0

    try:
        # P0-1: validate adapter.connect() return value
        if not adapter.connect():
            raise RuntimeError("Redis connection failed")

        for idx in range(total):
            # P0-3: bad frame → continue, not break
            if not cap.grab():
                consecutive_failures += 1
                total_failures += 1
                # Terminate only when consecutive failures exceed 50% of total
                if consecutive_failures > max(1, total * 0.5):
                    logger.error(
                        "Consecutive frame grab failures exceeded 50%% of total frames "
                        "(%d / %d). Aborting.",
                        total_failures, total,
                    )
                    break
                logger.warning("Frame %d grab failed (skipping, failure #%d)", idx, consecutive_failures)
                continue
            ok, frame = cap.retrieve()
            if not ok:
                consecutive_failures += 1
                total_failures += 1
                if consecutive_failures > max(1, total * 0.5):
                    logger.error(
                        "Consecutive frame retrieve failures exceeded 50%% of total frames "
                        "(%d / %d). Aborting.",
                        total_failures, total,
                    )
                    break
                logger.warning("Frame %d retrieve failed (skipping, failure #%d)", idx, consecutive_failures)
                continue

            # Reset consecutive failure counter on a valid frame
            consecutive_failures = 0

            res = opt.process_frame(frame, idx)
            if res['should_infer']:
                pr = pe.estimate(res['frame'], time.time())
                if pr and pr.landmarks:
                    opt.update_last_result(pr)
                    lms = [{'name':lm.name,'x':float(lm.x),'y':float(lm.y),'z':float(lm.z),'visibility':float(lm.visibility)} for lm in pr.landmarks]

                    # ── Hand estimation ──────────────────────────────────────
                    hand_landmarks_list: list[dict] = []
                    hand_features_dict: dict[str, float] = {}
                    hand_count = 0
                    try:
                        hand_result = he.estimate(res['frame'], timestamp=time.time())
                        if hand_result.is_valid():
                            for hand in [hand_result.left_hand, hand_result.right_hand]:
                                if hand and hand.is_valid():
                                    hand_count += 1
                                    hand_landmarks_list.extend(
                                        {
                                            'name': lm.name,
                                            'x': float(lm.x),
                                            'y': float(lm.y),
                                            'z': float(lm.z),
                                            'visibility': float(lm.visibility),
                                        }
                                        for lm in hand.landmarks
                                    )
                                    feats = HandAngleCalculator.extract_features(hand)
                                    hand_features_dict = feats.to_dict()
                                    break  # keep features from first valid hand
                    except Exception as exc:
                        logger.warning("Frame %d hand estimation error: %s (skipping)", idx, exc)

                    adapter.publish_pose_frame(
                        camera_id=f'video_{os.path.basename(video_path)}',
                        station_id=station_id,
                        frame_id=f'{seq:020d}',
                        landmarks=lms,
                        pose_score=float(pr.pose_score),
                        timestamp=time.time(),
                        hand_count=hand_count,
                        hand_landmarks=hand_landmarks_list or None,
                        hand_features=hand_features_dict or None,
                    )
                    seq += 1; pose_frames += 1

        # P0-10: Publish flush marker so downstream PoseFrameConsumer
        # knows all frames are delivered and can close any open segments.
        adapter.publish_pose_frame(
            camera_id=f'video_{os.path.basename(video_path)}',
            station_id=station_id,
            frame_id='__flush__',
            landmarks=[],
            pose_score=0.0,
            timestamp=time.time(),
            hand_count=0,
        )
        logger.info("Published flush marker (station=%s)", station_id)

    except Exception as e:
        logger.error("Video processing failed: %s", e, exc_info=True)
        # P0-1: publish failure status via progress channel
        if task_id:
            try:
                _publish_video_progress(
                    adapter, task_id, 0.0,
                    seq, total,
                    status="failed",
                    error=str(e)[:500],
                )
            except Exception:
                logger.warning("Failed to publish error progress (best-effort)")
        raise
    finally:
        cap.release()
        # P0-2: adapter.close() with timeout protection
        try:
            _safe_redis_call(adapter.close, timeout=3.0, label="adapter_close")
        except Exception:
            logger.warning("adapter.close() failed or timed out during cleanup")

    logger.info('Done: %d pose frames, %d total frames (failures: %d)', pose_frames, total, total_failures)


if __name__ == '__main__':
    import argparse
    p = argparse.ArgumentParser()
    p.add_argument('--video', required=True)
    p.add_argument('--station-id', default='WS-01')
    p.add_argument('--task-id', default='')
    args = p.parse_args()
    process(args.video, args.station_id, args.task_id)
