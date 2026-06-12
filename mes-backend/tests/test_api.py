"""Tests for FastAPI API endpoints."""

import os
import tempfile
import time

import pytest
from fastapi.testclient import TestClient


# ---------------------------------------------------------------------------
# Session-patching helper (same as test_phase3.py)
# ---------------------------------------------------------------------------


def _patch_db_url(db_url: str):
    """Patch get_session and deps.get_db_session to use test DB."""
    from app.models import database as db_mod
    from app.api import deps as deps_mod

    original_get_session = db_mod.get_session

    def patched_get_session(url=None):
        return original_get_session(db_url)

    db_mod.get_session = patched_get_session
    db_mod._engine_cache.clear()

    original_deps_get_db = deps_mod.get_db_session

    def patched_deps_get_db():
        return original_get_session(db_url)

    deps_mod.get_db_session = patched_deps_get_db


def _unpatch_db_url():
    """Restore original get_session (best effort)."""
    from app.models import database as db_mod
    db_mod._engine_cache.clear()


@pytest.fixture(scope="session")
def db_url():
    """Isolated test database path (shared across session)."""
    fd, path = tempfile.mkstemp(suffix=".db")
    os.close(fd)
    yield f"sqlite:///{path}"
    try:
        os.unlink(path)
    except OSError:
        pass


@pytest.fixture(scope="session")
def client(db_url):
    """FastAPI test client with isolated DB (session-scoped to avoid restart)."""
    from app.models.database import init_db, _engine_cache

    # Set MES_DB_URL so the lifespan can find it
    os.environ["MES_DB_URL"] = db_url
    _engine_cache.clear()

    init_db(db_url=db_url, echo=False)
    _patch_db_url(db_url)

    from app.main import app
    with TestClient(app) as c:
        yield c

    _unpatch_db_url()
    os.environ.pop("MES_DB_URL", None)
    _engine_cache.clear()


# ── Health and ping ─────────────────────────────────────────────────────

class TestHealthEndpoints:
    def test_health(self, client):
        resp = client.get("/health")
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "ok"
        assert data["service"] == "mes-backend"

    def test_ping(self, client):
        resp = client.get("/api/v1/ping")
        assert resp.status_code == 200
        assert resp.json()["pong"] is True


# ── Worktime endpoints (empty DB) ───────────────────────────────────────

class TestWorktimeEndpointsEmpty:
    def test_summary_empty(self, client):
        resp = client.get("/api/v1/worktime/summary")
        assert resp.status_code == 200
        data = resp.json()["data"]
        assert data["totalOps"] == 0

    def test_operations_empty(self, client):
        resp = client.get("/api/v1/worktime/operations")
        assert resp.status_code == 200
        data = resp.json()["data"]
        assert data == []

    def test_recent_empty(self, client):
        resp = client.get("/api/v1/worktime/recent")
        assert resp.status_code == 200
        data = resp.json()["data"]
        assert len(data) == 0

    def test_trend_empty(self, client):
        resp = client.get("/api/v1/worktime/trend?days=3")
        assert resp.status_code == 200
        data = resp.json()["data"]
        assert len(data["labels"]) == 3
        assert len(data["actual"]) == 3

    def test_therblig_distribution_empty(self, client):
        resp = client.get("/api/v1/worktime/therblig-distribution")
        assert resp.status_code == 200
        data = resp.json()["data"]
        assert data["items"] == []

    def test_therblig_detail_404(self, client):
        resp = client.get("/api/v1/worktime/therblig/99999")
        assert resp.status_code == 404

    def test_boxplot_empty(self, client):
        resp = client.get("/api/v1/worktime/boxplot")
        assert resp.status_code == 200
        data = resp.json()["data"]
        assert data["stations"] == []
        assert data["shifts"] == []

    def test_heatmap_empty(self, client):
        resp = client.get("/api/v1/worktime/heatmap")
        assert resp.status_code == 200
        data = resp.json()["data"]
        assert data["stations"] == []
        assert data["hours"] == []
        assert data["data"] == []


# ── Ingest endpoints ───────────────────────────────────────────────────

class TestIngestEndpoints:
    def test_ingest_single_frame(self, client):
        frame = {
            "camera_id": "cam_test",
            "timestamp": time.time(),
            "landmarks": [
                {"name": f"lm_{i}", "x": 0.5, "y": 0.5, "z": 0.0, "visibility": 1.0}
                for i in range(33)
            ],
            "pose_score": 0.95,
        }
        resp = client.post("/api/v1/ingest/frame", json=frame)
        assert resp.status_code == 200
        data = resp.json()
        assert data["code"] == 0
        assert data["data"]["accepted"] is True

    def test_ingest_batch_frames(self, client):
        frames = []
        for i in range(5):
            frames.append({
                "camera_id": "cam_test",
                "timestamp": time.time() + i * 0.033,
                "landmarks": [
                    {"name": f"lm_{j}", "x": 0.5, "y": 0.5, "z": 0.0, "visibility": 1.0}
                    for j in range(33)
                ],
                "pose_score": 0.95,
            })
        resp = client.post("/api/v1/ingest/frames", json=frames)
        assert resp.status_code == 200
        data = resp.json()
        assert data["data"]["accepted"] == 5

    def test_ingest_flush(self, client):
        resp = client.post("/api/v1/ingest/flush")
        assert resp.status_code == 200
        data = resp.json()
        assert data["code"] == 0

    def test_pipeline_stats(self, client):
        resp = client.get("/api/v1/ingest/stats")
        assert resp.status_code == 200
        data = resp.json()["data"]
        assert "frames_processed" in data
        assert "segments_emitted" in data
        assert "active_cameras" in data

    def test_invalid_frame_missing_landmarks(self, client):
        frame = {
            "camera_id": "cam_test",
            "timestamp": time.time(),
            "landmarks": [],
        }
        resp = client.post("/api/v1/ingest/frame", json=frame)
        # Should still be accepted (just won't classify)
        assert resp.status_code == 200


# ── API response structure ──────────────────────────────────────────────

class TestApiResponseStructure:
    def test_standard_response_envelope(self, client):
        resp = client.get("/health")
        # Health endpoint doesn't use ApiResponse wrapper
        assert resp.status_code == 200

    def test_worktime_response_envelope(self, client):
        resp = client.get("/api/v1/worktime/summary")
        data = resp.json()
        assert "code" in data
        assert "message" in data
        assert "data" in data
        assert "timestamp" in data
        assert data["code"] == 0
