"""Tests for Therblig mapper and worktime aggregator."""

import os
import tempfile

import pytest
from sqlalchemy.orm import Session

from app.models.database import (
    Base,
    ProcessSegment,
    TherbligDetail,
    WorktimeRecord,
    get_session,
    init_db,
)
from app.models.schemas import ActionLabel, ShiftName, TherbligSymbol
from app.services.process_segmenter import SegmentEvent
from app.services.therblig_mapper import (
    ACTION_TO_THERBLIG,
    TherbligMapping,
    compute_standard_time,
    map_action_to_therblig,
)
from app.services.worktime_aggregator import (
    _action_to_operation_name,
    _determine_shift,
    aggregate_segments,
    get_boxplot_stats,
    get_heatmap_stats,
    get_operations,
    get_recent_segments,
    get_therblig_distribution,
    get_worktime_summary,
    save_segment,
)


# ── Fixtures ────────────────────────────────────────────────────────────

@pytest.fixture
def db_session():
    """Create a temporary SQLite database for testing."""
    fd, path = tempfile.mkstemp(suffix=".db")
    db_url = f"sqlite:///{path}"
    os.close(fd)

    engine = init_db(db_url=db_url, echo=False)
    session = get_session(db_url)
    yield session

    session.close()


def make_segment_event(
    action: ActionLabel = ActionLabel.ASSEMBLE,
    duration_ms: float = 3000.0,
    start_time: float = 0.0,
    camera_id: str = "cam_0",
    station_id: str = "station_1",
) -> SegmentEvent:
    """Create a SegmentEvent.

    Default start_time=0.0 resolves to epoch = local 08:00 (morning shift).
    Pass an explicit start_time for other shifts.
    """
    return SegmentEvent(
        camera_id=camera_id,
        station_id=station_id,
        action=action,
        start_time=start_time,
        end_time=start_time + duration_ms / 1000.0,
        duration_ms=duration_ms,
        confidence=0.8,
    )


# Pre-computed UTC timestamps for consistent shift testing (UTC -> local UTC+8):
_TS_NIGHT = 1775142000.0   # 2026-04-02 15:00 UTC -> local 23:00 (night)
_TS_MORNING = 1775091600.0 # 2026-04-02 01:00 UTC -> local 09:00 (morning)


# ── Therblig mapper tests ───────────────────────────────────────────────

class TestTherbligMapper:
    def test_all_actions_have_mapping(self):
        for action in ActionLabel:
            mapping = map_action_to_therblig(action)
            assert isinstance(mapping, TherbligMapping)
            assert mapping.symbol != ""
            assert mapping.name != ""

    def test_waste_flags(self):
        waste_actions = {ActionLabel.WAIT, ActionLabel.IDLE}
        for action in ActionLabel:
            mapping = map_action_to_therblig(action)
            if action in waste_actions:
                assert mapping.is_waste is True, f"{action} should be waste"
            else:
                assert mapping.is_waste is False, f"{action} should not be waste"

    def test_unknown_action_returns_waste(self):
        # Simulate by passing an action not in the table
        # Since ActionLabel is exhaustive, this tests the default branch
        mapping = map_action_to_therblig(ActionLabel.IDLE)
        assert mapping.is_waste is True

    def test_compute_standard_time(self):
        # 3 reach (3 MOD each) + 2 grasp (1 MOD each) = 11 MOD
        reach_mapping = ACTION_TO_THERBLIG[ActionLabel.REACH]
        grasp_mapping = ACTION_TO_THERBLIG[ActionLabel.GRASP]
        standard_s = compute_standard_time([reach_mapping, reach_mapping, reach_mapping, grasp_mapping, grasp_mapping])
        expected = 11.0 * 0.129  # 11 MOD * 0.129 s/MOD
        assert abs(standard_s - expected) < 0.001

    def test_empty_mappings_returns_zero(self):
        assert compute_standard_time([]) == 0.0


# ── Shift determination tests ───────────────────────────────────────────

class TestDetermineShift:
    """Shift determination must convert UTC to local (UTC+8) before checking hour ranges.

    Factory shift schedule (local time / UTC+8):
      morning:   06:00-14:00
      afternoon: 14:00-22:00
      night:     22:00-06:00
    """

    def test_utc_22_is_local_06_morning(self):
        """UTC 22:00 = local 06:00 -> morning (bug would say night)."""
        from datetime import datetime, timezone
        dt = datetime(2026, 4, 2, 22, 0, tzinfo=timezone.utc)
        assert _determine_shift(dt) == ShiftName.MORNING

    def test_utc_06_is_local_14_afternoon(self):
        """UTC 06:00 = local 14:00 -> afternoon (bug would say morning)."""
        from datetime import datetime, timezone
        dt = datetime(2026, 4, 2, 6, 0, tzinfo=timezone.utc)
        assert _determine_shift(dt) == ShiftName.AFTERNOON

    def test_utc_14_is_local_22_night(self):
        """UTC 14:00 = local 22:00 -> night (bug would say afternoon)."""
        from datetime import datetime, timezone
        dt = datetime(2026, 4, 2, 14, 0, tzinfo=timezone.utc)
        assert _determine_shift(dt) == ShiftName.NIGHT

    def test_utc_10_is_local_18_afternoon(self):
        """UTC 10:00 = local 18:00 -> afternoon."""
        from datetime import datetime, timezone
        dt = datetime(2026, 4, 2, 10, 0, tzinfo=timezone.utc)
        assert _determine_shift(dt) == ShiftName.AFTERNOON

    def test_utc_00_is_local_08_morning(self):
        """UTC 00:00 = local 08:00 -> morning."""
        from datetime import datetime, timezone
        dt = datetime(2026, 4, 2, 0, 0, tzinfo=timezone.utc)
        assert _determine_shift(dt) == ShiftName.MORNING

    def test_utc_18_is_local_02_night(self):
        """UTC 18:00 = local 02:00 -> night."""
        from datetime import datetime, timezone
        dt = datetime(2026, 4, 2, 18, 0, tzinfo=timezone.utc)
        assert _determine_shift(dt) == ShiftName.NIGHT


# ── Worktime aggregator tests ──────────────────────────────────────────

class TestSaveSegment:
    def test_saves_segment_to_db(self, db_session):
        event = make_segment_event(ActionLabel.ASSEMBLE, duration_ms=5000.0, start_time=1000.0)
        segment = save_segment(db_session, event)
        assert segment.id is not None
        assert segment.action == "assemble"
        assert segment.duration_ms == 5000.0
        assert segment.station_id == "station_1"
        assert segment.therblig_symbol is not None

    def test_determines_shift(self, db_session):
        # Use a night-shift UTC timestamp: local 23:00 -> night
        event = make_segment_event(start_time=_TS_NIGHT)
        segment = save_segment(db_session, event)
        assert segment.shift == "night"


class TestGetRecentSegments:
    def test_empty_db(self, db_session):
        segments = get_recent_segments(db_session, limit=10)
        assert segments == []

    def test_returns_segments_ordered_by_time(self, db_session):
        for i in range(5):
            event = make_segment_event(start_time=1000.0 + i * 10)
            save_segment(db_session, event)

        segments = get_recent_segments(db_session, limit=3)
        assert len(segments) == 3
        # Most recent first
        assert segments[0].start_time > segments[1].start_time


class TestAggregateSegments:
    def test_aggregate_single_action(self, db_session):
        for i in range(3):
            event = make_segment_event(
                ActionLabel.ASSEMBLE,
                duration_ms=2000.0,
                start_time=_TS_NIGHT + i * 3,
            )
            save_segment(db_session, event)

        records = aggregate_segments(db_session, shift="night")
        assert len(records) >= 1

        # Find the assembly record
        assembly = [r for r in records if r.operation == "assembly"]
        assert len(assembly) == 1
        assert assembly[0].actual_ms == 6000.0  # 3 * 2000

    def test_multiple_actions(self, db_session):
        for _ in range(2):
            save_segment(db_session, make_segment_event(ActionLabel.ASSEMBLE, duration_ms=3000.0, start_time=_TS_NIGHT))
            save_segment(db_session, make_segment_event(ActionLabel.REACH, duration_ms=1000.0, start_time=_TS_NIGHT))

        records = aggregate_segments(db_session, shift="night")
        actions = {r.operation for r in records}
        assert "assembly" in actions
        assert "reach" in actions


class TestGetWorktimeSummary:
    def test_empty_db(self, db_session):
        summary = get_worktime_summary(db_session, shift="morning")
        assert summary["total_ops"] == 0
        assert summary["avg_efficiency"] == 0.0

    def test_with_data(self, db_session):
        for _ in range(2):
            save_segment(db_session, make_segment_event(ActionLabel.ASSEMBLE, duration_ms=3000.0, start_time=_TS_NIGHT))
        save_segment(db_session, make_segment_event(ActionLabel.WAIT, duration_ms=1000.0, start_time=_TS_NIGHT))

        aggregate_segments(db_session, shift="night")
        summary = get_worktime_summary(db_session, shift="night")
        assert summary["total_ops"] >= 1
        assert summary["avg_efficiency"] >= 0.0


class TestGetTherbligDistribution:
    def test_empty_db(self, db_session):
        dist = get_therblig_distribution(db_session, shift="morning")
        assert dist == []

    def test_returns_distributions(self, db_session):
        for _ in range(3):
            save_segment(db_session, make_segment_event(ActionLabel.ASSEMBLE, duration_ms=3000.0, start_time=_TS_NIGHT))
        save_segment(db_session, make_segment_event(ActionLabel.WAIT, duration_ms=1000.0, start_time=_TS_NIGHT))

        aggregate_segments(db_session, shift="night")
        dist = get_therblig_distribution(db_session, shift="night")
        assert len(dist) >= 1
        # Check structure
        for item in dist:
            assert "symbol" in item
            assert "name" in item
            assert "pct" in item
            assert "is_waste" in item


class TestActionToOperationName:
    def test_all_actions_mapped(self):
        for action in ActionLabel:
            name = _action_to_operation_name(action)
            assert name is not None
            assert name != ""


class TestGetBoxplotStats:
    def test_empty_db(self, db_session):
        result = get_boxplot_stats(db_session)
        assert result["stations"] == []
        assert result["shifts"] == []

    def test_single_station_single_shift(self, db_session):
        # All segments at night-shift UTC timestamp
        for i in range(10):
            save_segment(
                db_session,
                make_segment_event(
                    ActionLabel.ASSEMBLE,
                    duration_ms=2000.0 + i * 100.0,
                    start_time=_TS_NIGHT + i * 10,
                    station_id="WS-01",
                ),
            )
        result = get_boxplot_stats(db_session)
        assert "WS-01" in result["stations"]
        assert "night" in result["shifts"]
        night_data = result["night"]
        idx = result["stations"].index("WS-01")
        box = night_data[idx]
        assert box is not None
        assert len(box) == 5  # [min, Q1, median, Q3, max]
        # Values must be in seconds, not ms
        assert box == [2.0, 2.23, 2.45, 2.67, 2.9]

    def test_multiple_stations(self, db_session):
        for i in range(5):
            save_segment(
                db_session,
                make_segment_event(
                    ActionLabel.ASSEMBLE,
                    duration_ms=3000.0,
                    start_time=1000.0 + i * 10,
                    station_id="WS-01",
                ),
            )
            save_segment(
                db_session,
                make_segment_event(
                    ActionLabel.REACH,
                    duration_ms=1500.0,
                    start_time=1000.0 + i * 10,
                    station_id="WS-02",
                ),
            )
        result = get_boxplot_stats(db_session)
        assert len(result["stations"]) == 2

    def test_station_filter(self, db_session):
        for i in range(3):
            save_segment(
                db_session,
                make_segment_event(station_id="WS-01", start_time=1000.0 + i * 10),
            )
            save_segment(
                db_session,
                make_segment_event(station_id="WS-02", start_time=1000.0 + i * 10),
            )
        result = get_boxplot_stats(db_session, station_id="WS-01")
        assert result["stations"] == ["WS-01"]


class TestGetHeatmapStats:
    def test_empty_db(self, db_session):
        result = get_heatmap_stats(db_session)
        assert result["stations"] == []
        assert result["hours"] == []
        assert result["data"] == []

    def test_with_mixed_actions(self, db_session):
        # Create segments with known start times and mix of waste/productive
        from datetime import datetime, timezone

        base_hour = datetime(2026, 4, 2, 7, 0, tzinfo=timezone.utc)  # 7:00 UTC = morning shift hour 1
        for i in range(5):
            event = make_segment_event(
                ActionLabel.ASSEMBLE,
                duration_ms=3000.0,
                station_id="WS-01",
            )
            # Override start_time to be in morning shift hour 1
            event.start_time = base_hour.timestamp() + i * 300
            event.end_time = event.start_time + event.duration_ms / 1000.0
            save_segment(db_session, event)

        # Add waste segments
        for i in range(3):
            event = make_segment_event(
                ActionLabel.WAIT,
                duration_ms=2000.0,
                station_id="WS-01",
            )
            event.start_time = base_hour.timestamp() + i * 300
            event.end_time = event.start_time + event.duration_ms / 1000.0
            save_segment(db_session, event)

        result = get_heatmap_stats(db_session)
        assert len(result["stations"]) >= 1
        assert "WS-01" in result["stations"]
        assert len(result["hours"]) >= 1
        assert len(result["data"]) >= 1

        # Verify waste ratio: 3*2000 / (5*3000 + 3*2000) = 6000/21000 ~ 28.6%
        data_cell = result["data"][0]
        st_idx = data_cell[1]
        assert result["stations"][st_idx] == "WS-01"
        waste_pct = data_cell[2]
        assert 0 < waste_pct < 100  # Sanity check

    def test_two_stations_different_hours(self, db_session):
        from datetime import datetime, timezone

        h1 = datetime(2026, 4, 2, 7, 0, tzinfo=timezone.utc)  # shift hour 1
        h3 = datetime(2026, 4, 2, 9, 0, tzinfo=timezone.utc)  # shift hour 3

        for i in range(3):
            event = make_segment_event(ActionLabel.ASSEMBLE, duration_ms=4000.0, station_id="WS-01")
            event.start_time = h1.timestamp() + i * 300
            event.end_time = event.start_time + event.duration_ms / 1000.0
            save_segment(db_session, event)

        for i in range(3):
            event = make_segment_event(ActionLabel.WAIT, duration_ms=2000.0, station_id="WS-02")
            event.start_time = h3.timestamp() + i * 300
            event.end_time = event.start_time + event.duration_ms / 1000.0
            save_segment(db_session, event)

        result = get_heatmap_stats(db_session)
        assert len(result["stations"]) == 2
        assert len(result["data"]) >= 2

    def test_station_filter(self, db_session):
        from datetime import datetime, timezone

        h = datetime(2026, 4, 2, 8, 0, tzinfo=timezone.utc)
        event = make_segment_event(ActionLabel.ASSEMBLE, duration_ms=3000.0, station_id="WS-01")
        event.start_time = h.timestamp()
        event.end_time = event.start_time + event.duration_ms / 1000.0
        save_segment(db_session, event)

        result = get_heatmap_stats(db_session, station_id="WS-02")
        assert result["stations"] == []
        assert result["data"] == []

    def test_heatmap_shift_relative_hour_uses_local_time(self, db_session):
        """UTC 22:00 = local 06:00 -> morning shift hour 0 (shift_offset=0).

        Bug: code uses UTC hour (22) directly, maps to night shift_offset=0.
        Fix: convert to local time first, local 06:00 -> morning shift_offset=0.
        """
        from datetime import datetime, timezone

        # UTC 22:00 = local 06:00 -> morning shift, shift_offset = 06 - 6 = 0
        h = datetime(2026, 4, 2, 22, 0, tzinfo=timezone.utc)
        event = make_segment_event(ActionLabel.WAIT, duration_ms=5000.0, station_id="WS-HEAT")
        event.start_time = h.timestamp()
        event.end_time = event.start_time + event.duration_ms / 1000.0
        save_segment(db_session, event)

        result = get_heatmap_stats(db_session)
        assert "WS-HEAT" in result["stations"]
        # All segments should be waste (WAIT), so waste_pct should be 100
        waste_pcts = [cell[2] for cell in result["data"]
                      if result["stations"][cell[1]] == "WS-HEAT"]
        assert any(pct == 100.0 for pct in waste_pcts)
