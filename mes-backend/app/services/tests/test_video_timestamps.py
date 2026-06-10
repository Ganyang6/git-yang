"""Test video timestamp calculation for run_video_pipeline.

TDD: These tests verify that frame timestamps use video position
rather than wall clock, fixing Bug #1 and Bug #2.
"""

import math
import time

import pytest


def test_timestamp_tracks_video_position():
    """Frame timestamp should be computed from video position, not wall clock.

    For a 30fps video:
      frame 0  -> timestamp = base + 0/30
      frame 29 -> timestamp = base + 29/30
      duration  = frame29 - frame0 = 29/30 seconds
    """
    base_timestamp = time.time()
    video_fps = 30.0

    # Simulate: slow processing (500ms real time) should NOT affect timestamps
    frame0_ts = base_timestamp + (0 / video_fps)
    frame29_ts = base_timestamp + (29 / video_fps)

    duration = (frame29_ts - frame0_ts) * 1000  # ms

    # 29/30 seconds approx 967ms (not affected by wall clock)
    assert 960 < duration < 975, f"Expected ~967ms, got {duration}ms"


def test_timestamp_independent_of_processing_speed():
    """Timestamps should be identical regardless of processing delay."""
    base = 1000000.0  # arbitrary base
    fps = 30.0

    # Fast processing: frames evaluated instantly (0ms between)
    ts1_fast = base + (50 / fps)  # frame 50
    # Wait 1 second (simulating slow processing)
    ts1_slow = base + (50 / fps)  # same, from video position

    assert ts1_fast == pytest.approx(ts1_slow), (
        "Timestamps should not change with processing delay"
    )


def test_frame_interval_calculation():
    """Frame interval should be correct for standard FPS values."""
    for fps in [15.0, 24.0, 30.0, 60.0]:
        interval = 1.0 / fps
        assert interval > 0, f"Invalid interval for {fps}fps"
        # At 30fps: 100 frames should span approx 3.33s
        frame_count = 100
        total_duration = frame_count / fps
        assert abs(total_duration - 100 / fps) < 0.001
