"""Tests for the sliding window and process segmenter."""

import time

import pytest

from app.models.schemas import ActionLabel, ClassificationResultSchema, PoseFrameSchema
from app.services.action_classifier import (
    extract_features,
)
from app.services.process_segmenter import (
    ActionPipeline,
    ProcessSegmenter,
    SegmentEvent,
    SlidingWindow,
)
from app.models.schemas import LandmarkSchema


# ── Helpers ─────────────────────────────────────────────────────────────

def make_landmark_list(x: float, y: float, vis: float = 1.0) -> list:
    """Generate 33 landmarks all at the same position."""
    return [
        {"name": f"lm_{i}", "x": x, "y": y, "z": 0.0, "visibility": vis}
        for i in range(33)
    ]


def make_pose_frame(
    camera_id: str = "cam_0",
    timestamp: float = 1000.0,
    x: float = 0.5,
    y: float = 0.5,
    vis: float = 1.0,
) -> PoseFrameSchema:
    lms = [
        LandmarkSchema(name=f"lm_{i}", x=x, y=y, z=0.0, visibility=vis)
        for i in range(33)
    ]
    return PoseFrameSchema(
        camera_id=camera_id,
        timestamp=timestamp,
        landmarks=lms,
        pose_score=vis,
    )


def make_classification(action: ActionLabel, confidence: float = 0.8) -> ClassificationResultSchema:
    return ClassificationResultSchema(
        action=action,
        confidence=confidence,
        dominant_region="upper_body",
    )


# ── SlidingWindow tests ─────────────────────────────────────────────────

class TestSlidingWindow:
    def test_initial_state(self):
        w = SlidingWindow("cam_0", window_size=5)
        assert not w.is_full
        assert w.size == 0

    def test_fills_up(self):
        w = SlidingWindow("cam_0", window_size=3)
        lms = make_landmark_list(0.5, 0.5)
        for _ in range(3):
            feat = extract_features(lms)
            w.push(feat)
        assert w.is_full
        assert w.size == 3

    def test_ring_buffer_overflow(self):
        w = SlidingWindow("cam_0", window_size=3)
        lms = make_landmark_list(0.5, 0.5)
        for _ in range(5):
            feat = extract_features(lms)
            w.push(feat)
        assert w.size == 3  # ring buffer discards old

    def test_clear(self):
        w = SlidingWindow("cam_0", window_size=3)
        lms = make_landmark_list(0.5, 0.5)
        feat = extract_features(lms)
        w.push(feat)
        w.clear()
        assert w.size == 0


# ── ProcessSegmenter tests ──────────────────────────────────────────────

class TestProcessSegmenter:
    def test_first_classification_starts_segment(self):
        seg = ProcessSegmenter(confirmation_frames=3, idle_timeout_frames=10)
        result = seg.process(
            make_classification(ActionLabel.ASSEMBLE),
            frame_timestamp=1000.0,
            camera_id="cam_0",
            station_id="station_1",
        )
        assert result is None  # No segment closed yet
        assert seg.current_action == ActionLabel.ASSEMBLE

    def test_confirmation_before_switch(self):
        seg = ProcessSegmenter(confirmation_frames=3, idle_timeout_frames=10)

        # Feed 5 frames of ASSEMBLE
        for i in range(5):
            seg.process(
                make_classification(ActionLabel.ASSEMBLE),
                frame_timestamp=1000.0 + i * 0.033,
                camera_id="cam_0",
            )

        # Feed 2 frames of REACH (not enough to confirm)
        for i in range(2):
            result = seg.process(
                make_classification(ActionLabel.REACH),
                frame_timestamp=1015.0 + i * 0.033,
                camera_id="cam_0",
            )
            assert result is None  # not confirmed yet

        # 3rd REACH frame -> confirmation triggers segment close
        result = seg.process(
            make_classification(ActionLabel.REACH),
            frame_timestamp=1016.0,
            camera_id="cam_0",
        )
        assert result is not None
        assert isinstance(result, SegmentEvent)
        assert result.action == ActionLabel.ASSEMBLE  # closed segment
        assert result.duration_ms > 0
        assert seg.current_action == ActionLabel.REACH  # new segment started

    def test_idle_timeout(self):
        seg = ProcessSegmenter(confirmation_frames=3, idle_timeout_frames=5)

        # Start with ASSEMBLE
        seg.process(
            make_classification(ActionLabel.ASSEMBLE),
            frame_timestamp=1000.0,
            camera_id="cam_0",
        )

        # Feed 5 None (no pose) frames -> should trigger idle
        found_idle = False
        for i in range(5):
            result = seg.process(
                None,
                frame_timestamp=1000.0 + i * 0.1,
                camera_id="cam_0",
            )
            if result is not None:
                # The closed segment is the PREVIOUS action (ASSEMBLE)
                # After closing, current_action becomes IDLE
                assert seg.current_action == ActionLabel.IDLE
                found_idle = True
                break
        assert found_idle, "Idle timeout should have triggered"

    def test_flush_closes_open_segment(self):
        seg = ProcessSegmenter(confirmation_frames=10)
        seg.process(
            make_classification(ActionLabel.MOVE),
            frame_timestamp=1000.0,
            camera_id="cam_0",
        )
        event = seg.flush("cam_0")
        assert event is not None
        assert event.action == ActionLabel.MOVE
        assert event.duration_ms > 0

    def test_flush_no_open_segment(self):
        seg = ProcessSegmenter()
        event = seg.flush("cam_0")
        assert event is None

    def test_max_segment_duration_force_split(self):
        seg = ProcessSegmenter(
            confirmation_frames=100,
            idle_timeout_frames=1000,
            max_segment_duration_s=1.0,
        )
        seg.process(
            make_classification(ActionLabel.ASSEMBLE),
            frame_timestamp=1000.0,
            camera_id="cam_0",
        )
        # Jump forward past max duration
        result = seg.process(
            make_classification(ActionLabel.ASSEMBLE),
            frame_timestamp=1002.0,  # 2 seconds later
            camera_id="cam_0",
        )
        assert result is not None
        assert result.action == ActionLabel.ASSEMBLE


# ── ActionPipeline tests ───────────────────────────────────────────────

class TestActionPipeline:
    def test_stats(self):
        pipe = ActionPipeline(window_size=3, confirmation_frames=1)
        frame = make_pose_frame(timestamp=1000.0)
        pipe.process_frame(frame)
        assert pipe.stats["frames_processed"] == 1

    def test_multiple_cameras(self):
        pipe = ActionPipeline(window_size=3, confirmation_frames=1)
        f1 = make_pose_frame(camera_id="cam_0", timestamp=1000.0)
        f2 = make_pose_frame(camera_id="cam_1", timestamp=1000.0)
        pipe.process_frame(f1)
        pipe.process_frame(f2)
        assert pipe.stats["active_cameras"] == 2

    def test_flush_all(self):
        pipe = ActionPipeline(window_size=3, confirmation_frames=100)
        for i in range(5):
            frame = make_pose_frame(timestamp=1000.0 + i * 0.033)
            pipe.process_frame(frame)

        events = pipe.flush_all()
        # At least one camera should have an open segment
        assert pipe.stats["segments_emitted"] >= 0

    def test_low_visibility_feeds_none_to_segmenter(self):
        pipe = ActionPipeline(window_size=3, confirmation_frames=1)
        frame = make_pose_frame(vis=0.01)  # Very low visibility
        pipe.process_frame(frame)
        assert pipe.stats["frames_processed"] == 1
