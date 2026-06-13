"""
P1 fixes for Station operations and Line Balance display issues.

Tests:
  1. test_delete_station_warns — 删除 Station 时返回 warning（有相关 ProcessSegment 数据时）
  2. test_bottleneck_hint_valid — 验证后端 bottleneck 字段结构与前端兼容
  3. test_ecrs_causal_fields_survive_validation — 验证 ECRS/causal 字段通过 validate_response_data 后前端可用
"""

from __future__ import annotations

import os
from datetime import datetime, timezone

import pytest


# =====================================================================
# P1-1: 删除 Station 前警告
# =====================================================================

class TestDeleteStationWarning:
    """P1-1: delete_station must warn (not silently) when ProcessSegment references the station."""

    @pytest.fixture(autouse=True)
    def _cleanup(self, client):
        """Clean up test data before and after."""
        # Delete any ProcessSegments and Stations from previous tests
        for endpoint in ["/api/v1/worktime/cleanup", "/api/stations/cleanup"]:
            try:
                client.delete(endpoint)
            except Exception:
                pass
        yield
        # Clean up after
        for endpoint in ["/api/v1/worktime/cleanup", "/api/stations/cleanup"]:
            try:
                client.delete(endpoint)
            except Exception:
                pass

    def _find_seg_count(self, client, station_name: str) -> int:
        """Query the process_segments count for a station via an internal endpoint."""
        from app.models.database import get_session, ProcessSegment
        db_url = self._get_db_url()
        if not db_url:
            return 0
        session = get_session(db_url)
        try:
            return session.query(ProcessSegment).filter(
                ProcessSegment.station_id == station_name
            ).count()
        finally:
            session.close()

    def _get_db_url(self):
        import os
        return os.environ.get("MES_DB_URL", "")

    def test_delete_station_warns(self, client, seed_data):
        """Deleting a station with related ProcessSegment should return a warning."""
        import time as time_mod

        # 1. Create a station via API
        ts = int(time_mod.time() * 1000) % 100000
        name = f"P1-TEST-{ts}"
        resp = client.post("/api/stations", json={
            "name": name,
            "worker": "test",
            "line": "line1",
            "shift": "早班",
        })
        assert resp.status_code == 200, f"Create station failed: {resp.text}"
        # Unwrap the envelope
        body = resp.json()
        station_id = body["data"]["id"]

        # 2. Inject a ProcessSegment via direct DB access
        from app.models.database import get_session, ProcessSegment
        db_url = os.environ.get("MES_DB_URL", "")
        session = get_session(db_url)
        try:
            seg = ProcessSegment(
                camera_id="cam-test",
                station_id=name,
                line="line1",
                action="work",
                start_time=datetime.now(timezone.utc),
                end_time=datetime.now(timezone.utc),
                duration_ms=1000.0,
                confidence=0.95,
                shift="morning",
            )
            session.add(seg)
            session.commit()
        finally:
            session.close()

        # 3. Delete the station via API
        resp_del = client.delete(f"/api/stations/{station_id}")
        data = resp_del.json()

        # Should succeed but contain a warning
        assert resp_del.status_code == 200, \
            f"Expected 200 with warning, got {resp_del.status_code}: {data}"
        assert data.get("data", {}).get("deleted") is True, \
            f"Expected deleted=True, got {data}"
        # The response should contain a warning key
        assert "warning" in data.get("data", {}), \
            f"Expected warning in response data, got {data}"

    def test_delete_station_no_warning(self, client, seed_data):
        """Deleting a station with NO related data should not have a warning."""
        import time as time_mod

        ts = int(time_mod.time() * 1000) % 100000
        name = f"P1-NO-{ts}"
        resp = client.post("/api/stations", json={
            "name": name,
            "worker": "test",
            "line": "line2",
            "shift": "早班",
        })
        assert resp.status_code == 200, f"Create station failed: {resp.text}"
        body = resp.json()
        station_id = body["data"]["id"]

        # Delete without any ProcessSegment
        resp_del = client.delete(f"/api/stations/{station_id}")
        data = resp_del.json()

        assert resp_del.status_code == 200
        inner = data.get("data", {})
        assert inner.get("deleted") is True
        assert "warning" not in inner, \
            f"Should not have warning for clean deletion, got: {data}"


# =====================================================================
# P1-2: 瓶颈工位 hint undefined
# =====================================================================

class TestBottleneckHint:
    """P1-2: lbData.bottleneck is a string (station name), NOT an object with .time/.over."""

    def test_bottleneck_field_type_via_api(self, client, seed_data):
        """Verify /api/line-balance/full returns bottleneck as a string and stations have isBottleneck."""
        # Create stations for line1
        for name in ["BN-A", "BN-B", "BN-C"]:
            client.post("/api/stations", json={
                "name": name,
                "worker": f"worker-{name}",
                "line": "line1",
                "shift": "早班",
            })

        resp = client.get("/api/line-balance/full?line=line1")
        assert resp.status_code == 200, f"API failed: {resp.text}"
        data = resp.json().get("data", {})

        bottleneck = data.get("bottleneck", "")
        assert isinstance(bottleneck, str), \
            f"bottleneck must be a string, got {type(bottleneck).__name__}: {bottleneck}"

        stations_list = data.get("stations", [])
        assert isinstance(stations_list, list), "stations must be a list"
        assert len(stations_list) > 0, "stations should not be empty"

        for s in stations_list:
            assert isinstance(s.get("time"), (int, float)), \
                f"station.time must be numeric, got {s}"
            assert isinstance(s.get("isBottleneck"), bool), \
                f"station.isBottleneck must be bool, got {s}"

        # Find the bottleneck station from stations list
        bottleneck_station = next(
            (s for s in stations_list if s.get("isBottleneck")),
            None
        )
        if bottleneck_station:
            assert bottleneck_station.get("time") is not None, \
                "Bottleneck station must have time value"
        else:
            # All equal — verify
            times = [s.get("time") for s in stations_list]
            assert len(set(times)) <= 1, \
                f"No bottleneck but times vary: {times}"


# =====================================================================
# P1-3: ECRS/causal 字段不匹配
# =====================================================================

class TestEcrsCausalFieldValidation:
    """P1-3: ECRS and CausalRule schemas must include all fields the frontend renders."""

    def test_causal_rule_has_frontend_fields(self):
        """Verify CausalRule schema includes station, condition, cause, action, saving, improvement."""
        from app.models.schemas import CausalRule

        frontend_fields = {"station", "condition", "cause", "action", "saving", "improvement"}
        schema_fields = set(CausalRule.model_fields.keys())
        missing = frontend_fields - schema_fields
        assert not missing, \
            f"CausalRule schema missing frontend-required fields: {missing}"

    def test_ecrs_item_has_frontend_fields(self):
        """Verify EcrsItem schema includes all frontend-used fields."""
        from app.models.schemas import EcrsItem

        frontend_fields = {"type", "typeLabel", "station", "content", "saving", "difficulty", "priority", "status"}
        schema_fields = set(EcrsItem.model_fields.keys())
        missing = frontend_fields - schema_fields
        assert not missing, \
            f"EcrsItem schema missing frontend-required fields: {missing}"

    def test_ecrs_causal_fields_survive_validation(self, client, seed_data):
        """After validate_response_data(LineBalanceFull, ...), all frontend fields must present."""
        from app.models.schemas import LineBalanceFull, validate_response_data

        # Create test stations
        for name in ["ECRS-A", "ECRS-B", "ECRS-C"]:
            client.post("/api/stations", json={
                "name": name,
                "worker": f"worker-{name}",
                "line": "line1",
                "shift": "早班",
            })

        # Get the raw data before schema validation
        resp = client.get("/api/line-balance/full?line=line1")
        assert resp.status_code == 200
        raw_data = resp.json().get("data", {})

        # Validate through the schema
        validated = validate_response_data(LineBalanceFull, raw_data)

        # Check causalRules
        causal_rules = validated.get("causalRules", [])
        for i, rule in enumerate(causal_rules):
            assert "station" in rule, f"causalRules[{i}] missing 'station'"
            assert "condition" in rule, f"causalRules[{i}] missing 'condition'"
            assert "cause" in rule, f"causalRules[{i}] missing 'cause'"
            assert "action" in rule, f"causalRules[{i}] missing 'action'"
            assert "saving" in rule, f"causalRules[{i}] missing 'saving'"
            assert "improvement" in rule, f"causalRules[{i}] missing 'improvement'"

        # Check ecrsItems
        ecrs_items = validated.get("ecrsItems", [])
        for i, item in enumerate(ecrs_items):
            assert "type" in item, f"ecrsItems[{i}] missing 'type'"
            assert "typeLabel" in item, f"ecrsItems[{i}] missing 'typeLabel'"
            assert "station" in item, f"ecrsItems[{i}] missing 'station'"
            assert "content" in item, f"ecrsItems[{i}] missing 'content'"
            assert "saving" in item, f"ecrsItems[{i}] missing 'saving'"
            assert "difficulty" in item, f"ecrsItems[{i}] missing 'difficulty'"
            assert "priority" in item, f"ecrsItems[{i}] missing 'priority'"
            assert "status" in item, f"ecrsItems[{i}] missing 'status'"
