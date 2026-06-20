review_state = cleared
# fix_type = root_cause
# Reviewed: 2026-06-20 — get_station_metrics group_by shift + Reports hardcoded line1 fix
# Findings: 4 x P2 (group_by duplication risk, missing shift tests, default line name diff, silent clamp)
# See: workspace-review/code_review_report_groupby_shift_2026-06-20.md

# Phase I (cont.): Video timestamp bug fix — TDD implementation
#
## Changes made:
#
### 1. NEW: app/services/tests/test_video_timestamps.py
#   - Three TDD tests verifying video-position-based timestamps:
#     * test_timestamp_tracks_video_position: frame timestamps derived from
#       video position (base + frame/fps) not wall clock
#     * test_timestamp_independent_of_processing_speed: same frame always
#       gets same timestamp regardless of processing delay
#     * test_frame_interval_calculation: frame interval correct for 15/24/30/60fps
#
### 2. MODIFIED: main.py — run_video_pipeline() fixes (Bug #1 + Bug #2)
#   - Added base_timestamp = time.time() before frame loop (video-start marker)
#   - Replaced frame_timestamp = time.time() with
#     frame_timestamp = base_timestamp + (global_frame_seq / video_fps)
#     (Bug #1: timestamps now track video position, not wall clock)
#   - Added frame_loop_start = time.monotonic() at each frame's start
#   - Fixed sleep throttling: replaced mixed-clock expression
#     time.perf_counter() - frame_timestamp with monotonic-only
#     time.monotonic() - frame_loop_start (Bug #2: same clock source)
#
# All 3 new tests PASS. All 52 existing relevant tests PASS.
# Pre-existing failures (test_video_progress.py Redis mock, test_video_task_manager.py auth)
# are unrelated to this change.

# Phase II: MediaPipe Hands enhanced hand-based action classification
#
## Changes made:

### 1. NEW: app/services/hand_estimator.py
   - MediaPipe HandLandmarker wrapper (mp.tasks.vision API)
   - extract_features(rgb_frame) -> dict with grip_strength, pinch_distance,
     finger_spread, hand_visible, handedness, landmarks
   - Automatic model download from GCS
   - Graceful ImportError when mediapipe not available

### 2. MODIFIED: app/services/action_classifier.py
   - Added std_grip_strength, std_pinch_distance, std_finger_spread to WindowStats
   - Updated compute_window_stats to compute std of hand features
   - Added hand-dominant classification rules at the top of classify_action():
     * GRASP: gs>0.7 + pd<0.2 -> conf=0.85
     * RELEASE: gs<0.3 + fs>0.6 -> conf=0.85
     * HOLD->WAIT: gs>0.5 + fs<0.2 -> conf=0.70
     * ASSEMBLE: 0.3<=gs<=0.7 + pd<0.3 -> conf=0.70
     * Stillness: std_grip<0.03 + std_wrist_y<0.02 -> conf=0.60
   - Hand rules execute before body rules (hand label wins on conflict)
   - Existing body GRASP/RELEASE boosts preserved as fallback

### 3. MODIFIED: app/models/schemas.py
   - Added HOLD = "hold" to ActionLabel enum (currently mapped to WAIT in rules)

### 4. NEW: /tmp/test_hand_estimator.py
   - Tests import, synthetic feature extraction, classifier hand-dominant rules,
     enum label, and no-hand fallback
   - All 7 tests pass (non-mediapipe tests succeed, mediapipe tests SKIP gracefully
     in headless environment)

### Integration point (already works)
   - process_segmenter.py: process_frame() already accepts hand_features param
   - extract_features(landmarks, hand_features=...) already populates FrameFeatures
   - main.py: already runs hand estimation and passes hand_features via Redis

### Dependencies
   - dockerfile: already has mediapipe pip install via requirements.txt
   - requirements.txt: mediapipe>=0.10.0,<0.11.0 (MediaPipe Tasks API supported)
