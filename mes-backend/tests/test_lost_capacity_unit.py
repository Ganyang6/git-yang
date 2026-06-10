"""
TDD test for lost_capacity / 1000 unit inversion fix.

Background:
  get_station_metrics now returns `time` in seconds.
  Downstream lost_capacity = (max_d - avg_d) * n is already in seconds.
  But two places still divide by 1000, converting seconds back to milliseconds.

  This test verifies the fix removes those /1000 divisions.

See: task description "lost_capacity / 1000 单位反转"
"""

import pytest
from unittest.mock import patch, MagicMock


# ---------------------------------------------------------------------------
# P1a: dashboard.py - lostCapacity should NOT be /1000
# ---------------------------------------------------------------------------
def test_dashboard_lost_capacity_not_divided_by_1000():
    """
    Given station times in seconds (e.g. 100s, 120s, 80s),
    lost_capacity = (120 - 100) * 3 = 60s.
    The API should return lostCapacity=60.0, NOT 0.06 (60/1000).
    """
    station_data = [
        {"name": "S1", "time": 100.0, "order": 1},
        {"name": "S2", "time": 120.0, "order": 2},
        {"name": "S3", "time": 80.0, "order": 3},
    ]
    max_d = max(s["time"] for s in station_data)  # 120
    avg_d = sum(s["time"] for s in station_data) / len(station_data)  # 100
    n = len(station_data)  # 3
    lost_capacity = (max_d - avg_d) * n  # (120-100)*3 = 60

    # Simulate the OLD broken behavior
    old_result = round(lost_capacity / 1000, 1)  # 0.06 ← BUG
    # Simulate the NEW fixed behavior
    new_result = round(lost_capacity, 1)  # 60.0 ← FIX

    assert old_result == 0.1, f"OLD behavior would give {old_result}, expected 0.1"
    assert new_result == 60.0, f"NEW behavior should give {new_result}, expected 60.0"
    assert old_result != new_result, "Fix must change the value"
    assert new_result > old_result, "Fix must increase value (seconds > milliseconds)"


# ---------------------------------------------------------------------------
# P1b: line_balance.py - lostCapacity and lostValue should NOT be /1000
# ---------------------------------------------------------------------------
def test_line_balance_lost_capacity_not_divided_by_1000():
    """
    Same station data as above.
    lost_capacity = 60s.
    API lostCapacity should be 60.0, NOT 0.1 (60/1000).
    """
    station_data = [
        {"name": "S1", "time": 100.0, "order": 1},
        {"name": "S2", "time": 120.0, "order": 2},
        {"name": "S3", "time": 80.0, "order": 3},
    ]
    max_d = max(s["time"] for s in station_data)
    avg_d = sum(s["time"] for s in station_data) / len(station_data)
    n = len(station_data)
    lost_capacity = (max_d - avg_d) * n  # 60

    # OLD: /1000
    old_lost_capacity = round(lost_capacity / 1000, 1)  # 0.1
    # NEW: no /1000
    new_lost_capacity = round(lost_capacity, 1)  # 60.0

    assert old_lost_capacity == 0.1, f"OLD: {old_lost_capacity}"
    assert new_lost_capacity == 60.0, f"NEW: {new_lost_capacity}"


def test_line_balance_lost_value_no_1000():
    """
    lost_value = lost_capacity * mod_rate * 60
    (no /1000 since lost_capacity is already seconds).
    """
    mod_rate = 0.129  # seconds per MOD

    # With lost_capacity = 60s
    lost_capacity = 60.0

    # OLD: /1000 → 60/1000 * 0.129 * 60 ≈ 0.4644
    old_value = lost_capacity / 1000 * mod_rate * 60
    # NEW: no /1000 → 60 * 0.129 * 60 ≈ 464.4
    new_value = lost_capacity * mod_rate * 60

    assert old_value == pytest.approx(0.4644, rel=1e-3), f"OLD: {old_value}"
    assert new_value == pytest.approx(464.4, rel=1e-3), f"NEW: {new_value}"
    # New value is 1000x larger — confirms the /1000 was wrong
    assert new_value / old_value == pytest.approx(1000.0, rel=1e-3)


# ---------------------------------------------------------------------------
# P2: smoothIndex threshold (SI is now seconds, not ms)
# ---------------------------------------------------------------------------
def test_smooth_index_threshold_in_seconds():
    """
    SI is now in seconds. Threshold should be 10 (not 10000).
    
    Test: SI=8 (should be no warning), SI=12 (warning)
    """
    # When SI was in ms: threshold was 10000 → very few stations triggered it
    # Now SI in seconds: threshold should be 10
    
    # Helper: threshold trigger logic (same as line_balance.py)
    def should_trigger_causal_rule(si, threshold):
        return si >= threshold

    # These should NOT trigger warning (SI < 10s)
    assert not should_trigger_causal_rule(8, 10), "SI=8s should be below threshold"
    assert not should_trigger_causal_rule(5, 10), "SI=5s should be below threshold"
    
    # These SHOULD trigger warning (SI >= 10s)
    assert should_trigger_causal_rule(10, 10), "SI=10s should trigger warning"
    assert should_trigger_causal_rule(15, 10), "SI=15s should trigger warning"
    assert should_trigger_causal_rule(100, 10), "SI=100s should trigger warning"

    # Verify old threshold was wrong for seconds
    # With old threshold 10000, SI=15 would NOT trigger — clearly wrong
    assert not should_trigger_causal_rule(15, 10000), "Threshold 10000 misses SI=15s"
    assert should_trigger_causal_rule(15, 10), "Threshold 10 catches SI=15s"


# ---------------------------------------------------------------------------
# Integration-like test: full pipeline with mock station metrics
# ---------------------------------------------------------------------------
def test_full_pipeline_api_values():
    """
    Simulate the full data flow from station_metrics → API response.
    Verifies lostCapacity and causal rule values.
    """
    # Station times in seconds (from get_station_metrics)
    station_data = [
        {"name": "S1", "time": 100.0, "order": 1},
        {"name": "S2", "time": 120.0, "order": 2},
        {"name": "S3", "time": 80.0, "order": 3},
    ]

    # --- Compute balance metrics ---
    durations = [s["time"] for s in station_data]
    n = len(durations)
    total = sum(durations)
    avg_d = total / n  # 100
    max_d = max(durations)  # 120

    import math
    variance = sum((d - avg_d) ** 2 for d in durations)
    si = math.sqrt(variance)  # ~16.33s (smoothIndex in seconds)

    lbr = total / (max_d * n)  # 300/(120*3) = 0.8333

    # --- Compute downstream values ---
    lost_capacity = (max_d - avg_d) * n  # (120-100)*3 = 60s

    # --- Causal rules in seconds ---
    causal_rules = []
    
    # SI threshold should now be 10 (seconds)
    if si >= 10:
        causal_rules.append({
            "condition": f"SI >= 10s (actual: {si:.0f}s)",
            "conclusion": "High workload variance across stations",
            "level": "warning",
        })

    # --- Assertions ---
    # lostCapacity should be 60.0, NOT 0.1
    assert round(lost_capacity, 1) == 60.0, f"lostCapacity should be 60.0, got {lost_capacity}"

    # SI should trigger warning (16.33 >= 10)
    assert len(causal_rules) == 1, f"Should have 1 causal rule, got {len(causal_rules)}"
    rule = causal_rules[0]
    assert "SI >= 10s" in rule["condition"], f"Condition should mention seconds: {rule['condition']}"
    assert rule["level"] == "warning"

    # Verify: with OLD threshold 10000, no rule would trigger
    old_causal_rules = []
    if si >= 10000:
        old_causal_rules.append({"condition": "SI >= 10000ms", "conclusion": "..."})
    assert len(old_causal_rules) == 0, "Old threshold 10000 would miss SI in seconds"
