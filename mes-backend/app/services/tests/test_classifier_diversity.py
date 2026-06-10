"""Test classifier diversity: hand rules must not block body rules.

TDD for fix: Phase I hand-dominant rules were returning early without
ever reaching body rules, causing all frames in a repetitive task video
(e.g. conveyor-pick product) to get the same label (ASSEMBLE).  The
segmenter never saw an action transition -> never closed a segment ->
0 SegmentEvent produced -> 0 DB rows.

RED:  Tests that fail with the buggy hand-dominant returns.
GREEN: After removing hand-dominant returns, these tests should pass.
"""

import pytest

from app.models.schemas import ActionLabel, ClassificationResultSchema
from app.services.action_classifier import (
    WindowStats,
    classify_action,
)
from app.services.process_segmenter import ProcessSegmenter, SegmentEvent


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_stats(**overrides) -> WindowStats:
    """Build a WindowStats with sensible defaults."""
    defaults = {
        "avg_left_elbow": 90.0,
        "avg_right_elbow": 90.0,
        "avg_left_shoulder": 45.0,
        "avg_right_shoulder": 45.0,
        "avg_left_knee": 120.0,
        "avg_right_knee": 120.0,
        "avg_left_hip": 160.0,
        "avg_right_hip": 160.0,
        "avg_wrist_y": 0.5,
        "avg_shoulder_y": 0.35,
        "avg_wrist_spread": 0.15,
        "std_wrist_y": 0.04,
        "std_wrist_spread": 0.04,
        "avg_visible_fraction": 0.8,
        "standing_ratio": 1.0,
        "n_frames": 10,
        # Hand data: defaults that DON'T match any hand-dominant rule
        # (gs=0.5/pd=0.5/fs=0.4/std_gs=0.05 avoid all Phase-I triggers)
        "avg_grip_strength": 0.5,
        "avg_pinch_distance": 0.5,
        "avg_finger_spread": 0.4,
        "std_grip_strength": 0.05,
        "std_pinch_distance": 0.05,
        "std_finger_spread": 0.05,
        "has_hand_data": True,
    }
    defaults.update(overrides)
    return WindowStats(**defaults)


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

class TestClassifierBodyRulesReachable:
    """Classifier must still evaluate body rules when hand data is present."""

    def test_hand_rules_do_not_block_body_rules(self):
        """Body rules remain reachable even when hand data matches a
        hand-dominant rule.

        Bug symptom: hand features matching GRASP (gs>0.7, pd<0.2)
        cause early return of GRASP even when body features clearly
        indicate WAIT (arms straight, still).
        """
        # Case: hand data matches Phase-I GRASP rule, body matches WAIT
        stats = _make_stats(
            # Hand features triggering hand-dominant GRASP
            avg_grip_strength=0.85,
            avg_pinch_distance=0.10,
            avg_finger_spread=0.10,
            # Body features for WAIT (straight arms, very still)
            avg_left_elbow=165.0,
            avg_right_elbow=165.0,
            avg_left_shoulder=10.0,
            avg_right_shoulder=10.0,
            avg_wrist_y=0.6,
            std_wrist_y=0.01,
            std_wrist_spread=0.01,
        )
        label, _, _ = classify_action(stats)
        # After fix: body WAIT rule should dominate
        # Before fix: hand GRASP rule would return GRASP early
        assert label == ActionLabel.WAIT, (
            f"Body WAIT rule should win over hand GRASP rule, got {label}"
        )

    def test_hand_release_does_not_block_body_move(self):
        """Hand Release features must not prevent MOVE body rule."""
        stats = _make_stats(
            # Hand features triggering hand-dominant RELEASE
            avg_grip_strength=0.15,
            avg_finger_spread=0.75,
            # Body features for MOVE (high wrist variance)
            std_wrist_y=0.08,
            standing_ratio=0.6,
        )
        label, _, _ = classify_action(stats)
        assert label == ActionLabel.MOVE, (
            f"Body MOVE rule should win over hand RELEASE rule, got {label}"
        )

    def test_hand_assemble_does_not_block_body_reach(self):
        """Hand Assemble features must not block REACH body rule."""
        stats = _make_stats(
            # Hand features triggering hand-dominant ASSEMBLE
            avg_grip_strength=0.5,
            avg_pinch_distance=0.10,
            # Body features for REACH (high shoulder angle)
            avg_left_shoulder=80.0,
            avg_right_shoulder=80.0,
            avg_wrist_y=0.6,
            std_wrist_y=0.06,
        )
        label, _, _ = classify_action(stats)
        assert label == ActionLabel.REACH, (
            f"Body REACH rule should win over hand ASSEMBLE rule, got {label}"
        )

    def test_classifier_produces_diverse_labels(self):
        """Different feature profiles must produce different labels."""
        # MOVE
        move = _make_stats(std_wrist_y=0.08, standing_ratio=0.6)
        label_a, _, _ = classify_action(move)
        assert label_a == ActionLabel.MOVE, f"Expected MOVE, got {label_a}"

        # GRASP (body rule with hand boost): high wrist-spread variance + bent elbows
        grasp = _make_stats(
            std_wrist_spread=0.06,
            avg_wrist_spread=0.20,
            avg_left_elbow=80.0,
            avg_right_elbow=80.0,
            avg_grip_strength=0.8,
        )
        label_b, _, _ = classify_action(grasp)
        assert label_b == ActionLabel.GRASP, f"Expected GRASP, got {label_b}"

        # REACH
        reach = _make_stats(
            avg_left_shoulder=75.0,
            avg_right_shoulder=75.0,
            avg_wrist_y=0.6,
            std_wrist_y=0.06,
        )
        label_c, _, _ = classify_action(reach)
        assert label_c == ActionLabel.REACH, f"Expected REACH, got {label_c}"

        # At least 3 distinct labels
        labels = {label_a, label_b, label_c}
        assert len(labels) >= 3, (
            f"Expected >=3 distinct labels, got {labels}"
        )


class TestSegmenterWithClassifierOutput:
    """Segmenter must close segments when classifier output changes."""

    def test_segmenter_produces_events(self):
        """Action transitions must trigger segment closes."""
        seg = ProcessSegmenter(confirmation_frames=2)
        t0 = 1000.0

        # Phase 1: same label 5 times -> no segment close
        for i in range(5):
            ev = seg.process(
                ClassificationResultSchema(
                    action=ActionLabel.GRASP, confidence=0.80,
                    dominant_region="upper_body",
                ),
                t0 + i * 0.1, "cam_1", "station_1",
            )
            assert ev is None, "Same repeated label must NOT close segment"

        # Phase 2: switch label, confirm after 2 frames -> SegmentEvent fires
        events = []
        for i in range(3):
            ev = seg.process(
                ClassificationResultSchema(
                    action=ActionLabel.ASSEMBLE, confidence=0.70,
                    dominant_region="upper_body",
                ),
                t0 + 5.0 + i * 0.1, "cam_1", "station_1",
            )
            if ev is not None:
                events.append(ev)

        assert len(events) >= 1, "Segmenter must produce event on transition"
        ev = events[0]
        assert isinstance(ev, SegmentEvent), f"Expected SegmentEvent, got {type(ev)}"
        assert ev.action == ActionLabel.GRASP, (
            f"Closed segment action should be GRASP (old), got {ev.action}"
        )
        assert ev.duration_ms > 0, f"Duration should be positive, got {ev.duration_ms}"
        assert ev.camera_id == "cam_1"
        assert ev.station_id == "station_1"

    def test_classifier_transition_triggers_segmenter(self):
        """End-to-end: different stats -> different labels -> segment events."""
        seg = ProcessSegmenter(confirmation_frames=2)
        t0 = 2000.0

        # Produce INSPECT
        inspect = _make_stats(
            avg_wrist_y=0.20,
            std_wrist_y=0.01,
            std_wrist_spread=0.02,
        )
        label1, conf1, _ = classify_action(inspect)
        assert label1 == ActionLabel.INSPECT

        for i in range(5):
            ev = seg.process(
                ClassificationResultSchema(
                    action=label1, confidence=conf1, dominant_region="upper_body",
                ),
                t0 + i * 0.1, "cam_2", "station_1",
            )
            assert ev is None

        # Produce WAIT
        wait = _make_stats(
            avg_left_elbow=160.0, avg_right_elbow=160.0,
            avg_left_shoulder=15.0, avg_right_shoulder=15.0,
            avg_wrist_y=0.6,
            std_wrist_y=0.01, std_wrist_spread=0.01,
        )
        label2, conf2, _ = classify_action(wait)
        assert label2 == ActionLabel.WAIT
        assert label2 != label1, "Different stats should give different labels"

        events = []
        for i in range(3):
            ev = seg.process(
                ClassificationResultSchema(
                    action=label2, confidence=conf2, dominant_region="full_body",
                ),
                t0 + 5.0 + i * 0.1, "cam_2", "station_1",
            )
            if ev is not None:
                events.append(ev)

        assert len(events) >= 1, "Transition should trigger segment close"
        assert events[0].action == label1, (
            f"Closed segment should have old label (INSPECT), got {events[0].action}"
        )
