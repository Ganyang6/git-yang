"""
RED phase test for line_balance_service ms→seconds bug.

get_station_metrics() returns avg_duration as-is, but avg_duration is in
milliseconds (from ProcessSegment.duration_ms). The returned 'time' value
must be in seconds (divide by 1000).

Test demonstrates the issue: expects 0.5s but current code returns 500.
"""
from __future__ import annotations

from unittest.mock import MagicMock, patch, PropertyMock

import pytest


class TestStationMetricsReturnsSeconds:
    """P1: get_station_metrics returns 'time' in seconds, not ms.

    avg_duration from func.avg(ProcessSegment.duration_ms) is in milliseconds.
    The return value must be divided by 1000 to provide seconds.
    """

    @patch("app.services.line_balance_service.datetime")
    def test_time_is_in_seconds_not_ms(self, mock_datetime):
        """When avg_duration=500 (ms), time must be 0.5 (s), not 500."""
        from app.services.line_balance_service import get_station_metrics

        # Mock datetime.now() to return a fixed UTC time
        from datetime import datetime, timezone
        fixed_now = datetime(2026, 6, 10, 10, 0, 0, tzinfo=timezone.utc)
        mock_datetime.now.return_value = fixed_now
        mock_datetime.side_effect = lambda *a, **kw: datetime(*a, **kw)

        # Create mock query results
        mock_row = MagicMock()
        mock_row.station_id = "WS-01"
        mock_row.avg_duration = 500  # 500 ms
        mock_row.seg_count = 10

        mock_query = MagicMock()
        mock_query.filter.return_value = mock_query
        mock_query.group_by.return_value = mock_query
        mock_query.all.return_value = [mock_row]

        mock_session = MagicMock()
        mock_session.query.return_value = mock_query

        result = get_station_metrics(mock_session)

        assert len(result) == 1
        assert result[0]["name"] == "WS-01"
        assert result[0]["count"] == 10
        # This is the critical assertion: 500ms → 0.5s
        assert result[0]["time"] == pytest.approx(0.5, rel=1e-3), (
            f"Expected 0.5s for 500ms, got {result[0]['time']}"
        )

    @patch("app.services.line_balance_service.datetime")
    def test_multiple_stations_in_seconds(self, mock_datetime):
        """Multiple stations with different durations must all be in seconds."""
        from app.services.line_balance_service import get_station_metrics

        from datetime import datetime, timezone
        fixed_now = datetime(2026, 6, 10, 10, 0, 0, tzinfo=timezone.utc)
        mock_datetime.now.return_value = fixed_now
        mock_datetime.side_effect = lambda *a, **kw: datetime(*a, **kw)

        rows = []
        for name, ms in [("WS-01", 500), ("WS-02", 1500), ("WS-03", 200)]:
            row = MagicMock()
            row.station_id = name
            row.avg_duration = ms
            row.seg_count = 5
            rows.append(row)

        mock_query = MagicMock()
        mock_query.filter.return_value = mock_query
        mock_query.group_by.return_value = mock_query
        mock_query.all.return_value = rows

        mock_session = MagicMock()
        mock_session.query.return_value = mock_query

        result = get_station_metrics(mock_session)

        assert len(result) == 3
        assert result[0]["time"] == pytest.approx(0.5, rel=1e-3)
        assert result[1]["time"] == pytest.approx(1.5, rel=1e-3)
        assert result[2]["time"] == pytest.approx(0.2, rel=1e-3)

    @patch("app.services.line_balance_service.datetime")
    def test_zero_duration_returns_zero(self, mock_datetime):
        """Zero ms duration must return 0.0 seconds."""
        from app.services.line_balance_service import get_station_metrics

        from datetime import datetime, timezone
        fixed_now = datetime(2026, 6, 10, 10, 0, 0, tzinfo=timezone.utc)
        mock_datetime.now.return_value = fixed_now
        mock_datetime.side_effect = lambda *a, **kw: datetime(*a, **kw)

        mock_row = MagicMock()
        mock_row.station_id = "WS-01"
        mock_row.avg_duration = 0
        mock_row.seg_count = 1

        mock_query = MagicMock()
        mock_query.filter.return_value = mock_query
        mock_query.group_by.return_value = mock_query
        mock_query.all.return_value = [mock_row]

        mock_session = MagicMock()
        mock_session.query.return_value = mock_query

        result = get_station_metrics(mock_session)
        assert result[0]["time"] == 0.0


class TestGenerateEcrsSuggestionsUnitAware:
    """P1: generate_ecrs_suggestions must handle time in seconds.

    When station_data 'time' is in seconds (not ms), the display string
    in 'Simplify' suggestion must show the correct seconds value
    without dividing by 1000 again.
    """

    def test_simplify_suggestion_shows_seconds(self):
        """Simplify suggestion should display time in seconds correctly."""
        from app.services.line_balance_service import generate_ecrs_suggestions

        station_data = [
            {"name": "WS-01", "time": 2.5, "count": 10},
            {"name": "WS-02", "time": 1.0, "count": 8},
        ]
        avg_d = 1.75

        suggestions = generate_ecrs_suggestions(station_data, avg_d)

        # Find the Simplify suggestion
        simplify = [s for s in suggestions if s["method"] == "Simplify"]
        assert len(simplify) == 1

        desc = simplify[0]["description"]
        # The time should be displayed as 2.5s, not 0.0s (2.5/1000 = 0.0025s)
        assert "2.5s" in desc, (
            f"Simplify suggestion should show 2.5s, got description: {desc}"
        )
        # Must NOT have a /1000 pattern in the format
        assert "0.0s" not in desc, (
            f"Simplify suggestion should not show 0.0s (would result from "
            f"dividing 2.5s by 1000 again). Description: {desc}"
        )
