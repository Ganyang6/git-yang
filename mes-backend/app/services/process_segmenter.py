"""
Sliding window processor for action classification.

Maintains a per-camera ring buffer of recent pose frames.  When the buffer
reaches the configured window size, it calls the action classifier and
feeds the result into the process segmenter state machine.
"""

from __future__ import annotations

import logging
import time
from collections import deque
from dataclasses import dataclass, field
from typing import Deque, Dict, List, Optional, Tuple

import numpy as np

from app.models.schemas import ActionLabel, ClassificationResultSchema, PoseFrameSchema
from app.services.action_classifier import (
    FrameFeatures,
    WindowStats,
    classify_action,
    compute_window_stats,
    extract_features,
)

logger = logging.getLogger(__name__)


class SlidingWindow:
    """
    Fixed-size ring buffer that stores extracted FrameFeatures.

    When full (size == window_size), the oldest frame is discarded and
    the window is ready for classification.
    """

    def __init__(self, camera_id: str, window_size: int = 10):
        self.camera_id = camera_id
        self.window_size = window_size
        self._buffer: Deque[FrameFeatures] = deque(maxlen=window_size)
        self._frame_count = 0

    @property
    def is_full(self) -> bool:
        return len(self._buffer) >= self.window_size

    @property
    def size(self) -> int:
        return len(self._buffer)

    def push(self, features: FrameFeatures) -> None:
        self._buffer.append(features)
        self._frame_count += 1

    def get_features_list(self) -> List[FrameFeatures]:
        return list(self._buffer)

    def clear(self) -> None:
        self._buffer.clear()


@dataclass
class SegmentEvent:
    """
    Emitted when the state machine confirms an action transition.

    This is the unit of work that gets persisted to the database.
    """
    camera_id: str
    station_id: str
    action: ActionLabel
    start_time: float  # epoch seconds
    end_time: float
    duration_ms: float
    confidence: float


class ProcessSegmenter:
    """
    State machine that consumes classification results and emits
    ProcessSegment events when a stable action transition is confirmed.

    Rules:
      1.  The current action must remain unchanged for `confirmation_frames`
          consecutive classifications before it becomes the confirmed action.
      2.  If the confirmed action changes, the previous segment is closed
          and a new one begins.
      3.  If no valid pose is received for `idle_timeout_frames`, an idle
          segment is inserted.
      4.  Segments exceeding `max_segment_duration_s` are force-split.
    """

    def __init__(
        self,
        confirmation_frames: int = 5,
        idle_timeout_frames: int = 30,
        max_segment_duration_s: float = 300.0,
    ):
        self.confirmation_frames = confirmation_frames
        self.idle_timeout_frames = idle_timeout_frames
        self.max_segment_duration_s = max_segment_duration_s

        # Current confirmed state
        self._current_action: Optional[ActionLabel] = None
        self._segment_start_time: Optional[float] = None
        self._segment_start_frame_count: int = 0
        self._segment_confidence: float = 0.0

        # Pending confirmation counter
        self._pending_action: Optional[ActionLabel] = None
        self._pending_count: int = 0

        # Idle detection
        self._frames_since_valid: int = 0

        # Total frames processed
        self._total_frames: int = 0

        # Track current station_id (updated on each process() call)
        self.current_station_id: str = "default"

    def process(
        self,
        classification: Optional[ClassificationResultSchema],
        frame_timestamp: float,
        camera_id: str,
        station_id: str = "default",
    ) -> Optional[SegmentEvent]:
        """
        Feed one classification result into the state machine.

        Returns:
            A SegmentEvent if a segment was just closed, otherwise None.
        """
        self._total_frames += 1
        self.current_station_id = station_id

        if classification is None:
            self._frames_since_valid += 1
            # Check idle timeout
            if (
                self._frames_since_valid >= self.idle_timeout_frames
                and self._current_action is not None
                and self._current_action != ActionLabel.IDLE
            ):
                return self._close_segment(
                    frame_timestamp, camera_id, station_id, ActionLabel.IDLE, 0.8
                )
            return None

        # Reset idle counter
        self._frames_since_valid = 0

        action = classification.action

        # First classification ever: start a segment
        if self._current_action is None:
            self._current_action = action
            self._segment_start_time = frame_timestamp
            self._segment_start_frame_count = self._total_frames
            self._segment_confidence = classification.confidence
            self._pending_action = None
            self._pending_count = 0
            return None

        # Check max segment duration
        if self._segment_start_time is not None:
            elapsed = frame_timestamp - self._segment_start_time
            if elapsed >= self.max_segment_duration_s:
                # Force-close current segment, start new one with same action
                return self._close_segment(
                    frame_timestamp, camera_id, station_id, action,
                    classification.confidence
                )

        # If classification matches current, reset pending
        if action == self._current_action:
            self._pending_action = None
            self._pending_count = 0
            self._segment_confidence = (
                self._segment_confidence + classification.confidence
            ) / 2
            return None

        # Action changed: accumulate pending confirmation
        if action == self._pending_action:
            self._pending_count += 1
        else:
            self._pending_action = action
            self._pending_count = 1

        # Check if pending is confirmed
        if self._pending_count >= self.confirmation_frames:
            return self._close_segment(
                frame_timestamp, camera_id, station_id, action,
                classification.confidence
            )

        return None

    def _close_segment(
        self,
        frame_timestamp: float,
        camera_id: str,
        station_id: str,
        new_action: ActionLabel,
        new_confidence: float,
    ) -> SegmentEvent:
        """Close the current segment and start a new one."""
        event = SegmentEvent(
            camera_id=camera_id,
            station_id=self.current_station_id,
            action=self._current_action or ActionLabel.IDLE,
            start_time=self._segment_start_time or frame_timestamp,
            end_time=frame_timestamp,
            duration_ms=(frame_timestamp - (self._segment_start_time or frame_timestamp)) * 1000,
            confidence=self._segment_confidence,
        )

        # Start new segment
        self._current_action = new_action
        self._segment_start_time = frame_timestamp
        self._segment_start_frame_count = self._total_frames
        self._segment_confidence = new_confidence
        self._pending_action = None
        self._pending_count = 0

        return event

    def flush(self, camera_id: str, station_id: str = "default") -> Optional[SegmentEvent]:
        """
        Flush any open segment (call on shutdown).

        Returns:
            The final open segment if any, otherwise None.
        """
        if self._current_action is None or self._segment_start_time is None:
            return None

        now = time.time()
        return SegmentEvent(
            camera_id=camera_id,
            station_id=self.current_station_id,
            action=self._current_action,
            start_time=self._segment_start_time,
            end_time=now,
            duration_ms=(now - self._segment_start_time) * 1000,
            confidence=self._segment_confidence,
        )

    @property
    def current_action(self) -> Optional[ActionLabel]:
        return self._current_action


class ActionPipeline:
    """
    End-to-end pipeline: sliding window -> classifier -> segmenter.

    Maintains per-camera sliding windows and segmenters.  Call
    `process_frame()` with each incoming PoseFrameSchema from the
    perception layer.
    """

    def __init__(
        self,
        window_size: int = 10,
        min_landmark_visibility: float = 0.5,
        confirmation_frames: int = 5,
        idle_timeout_frames: int = 30,
        max_segment_duration_s: float = 300.0,
    ):
        self.window_size = window_size
        self.min_landmark_visibility = min_landmark_visibility

        self._windows: Dict[str, SlidingWindow] = {}
        self._segmenters: Dict[str, ProcessSegmenter] = {}
        self._last_access: Dict[str, float] = {}  # camera_id -> last access timestamp
        self._MAX_CAMERAS = 20  # LRU eviction threshold

        self._confirmation_frames = confirmation_frames
        self._idle_timeout_frames = idle_timeout_frames
        self._max_segment_duration_s = max_segment_duration_s

        # Statistics
        self._frames_processed = 0
        self._segments_emitted = 0

    def _evict_stale_cameras(self) -> None:
        """Evict least-recently-used cameras when exceeding max threshold."""
        if len(self._windows) <= self._MAX_CAMERAS:
            return
        # Sort by last access time, evict the oldest
        sorted_cameras = sorted(self._last_access, key=lambda k: self._last_access[k])
        while len(self._windows) > self._MAX_CAMERAS and sorted_cameras:
            stale = sorted_cameras.pop(0)
            self._windows.pop(stale, None)
            self._segmenters.pop(stale, None)
            self._last_access.pop(stale, None)

    def _get_window(self, camera_id: str) -> SlidingWindow:
        self._last_access[camera_id] = time.time()
        if camera_id not in self._windows:
            self._windows[camera_id] = SlidingWindow(
                camera_id=camera_id, window_size=self.window_size
            )
            self._evict_stale_cameras()
        return self._windows[camera_id]

    def _get_segmenter(self, camera_id: str) -> ProcessSegmenter:
        self._last_access[camera_id] = time.time()
        if camera_id not in self._segmenters:
            self._segmenters[camera_id] = ProcessSegmenter(
                confirmation_frames=self._confirmation_frames,
                idle_timeout_frames=self._idle_timeout_frames,
                max_segment_duration_s=self._max_segment_duration_s,
            )
            self._evict_stale_cameras()
        return self._segmenters[camera_id]

    def process_frame(
        self, frame: PoseFrameSchema, station_id: str = "default",
        hand_features: dict | None = None,
    ) -> Optional[SegmentEvent]:
        """
        Process a single pose frame through the full pipeline.

        Args:
            frame:      PoseFrameSchema from the perception layer.
            station_id: The work station this camera is observing.

        Returns:
            A SegmentEvent if the segmenter closed a segment, else None.
        """
        self._frames_processed += 1

        # Extract features
        landmarks = [
            {"name": lm.name, "x": lm.x, "y": lm.y, "z": lm.z, "visibility": lm.visibility}
            for lm in frame.landmarks
        ]
        features = extract_features(landmarks, hand_features=hand_features)
        if features is None:
            # No valid pose: feed None to segmenter for idle detection
            segmenter = self._get_segmenter(frame.camera_id)
            event = segmenter.process(
                None, frame.timestamp, frame.camera_id, station_id
            )
            if event:
                self._segments_emitted += 1
            return event

        # Push to sliding window
        window = self._get_window(frame.camera_id)
        window.push(features)

        # Classify when window is full
        if not window.is_full:
            # Feed pending to segmenter (with no classification yet)
            return None

        features_list = window.get_features_list()
        stats = compute_window_stats(features_list)
        action, confidence, region = classify_action(stats)

        classification = ClassificationResultSchema(
            action=action,
            confidence=confidence,
            dominant_region=region,
        )

        # Feed to segmenter
        segmenter = self._get_segmenter(frame.camera_id)
        event = segmenter.process(
            classification, frame.timestamp, frame.camera_id, station_id
        )
        if event:
            self._segments_emitted += 1

        return event

    def flush_all(self, station_id: str = "default") -> List[SegmentEvent]:
        """Flush all open segments (call on shutdown)."""
        events = []
        for camera_id in list(self._segmenters.keys()):
            event = self._segmenters[camera_id].flush(camera_id, station_id)
            if event:
                events.append(event)
                self._segments_emitted += 1
        return events

    @property
    def stats(self) -> Dict:
        return {
            "frames_processed": self._frames_processed,
            "segments_emitted": self._segments_emitted,
            "active_cameras": len(self._windows),
        }
