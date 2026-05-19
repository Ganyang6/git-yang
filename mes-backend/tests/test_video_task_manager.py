"""Tests for VideoTaskManager (T9-02)."""

import asyncio
import time
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.services.video_task_manager import VideoTaskManager, TaskStatus


class TestVideoTaskManager:
    """T9-02: VideoTaskManager unit tests."""

    def test_create_task_returns_task_dict(self):
        """Creating a task returns dict with id, status, filename, timestamps."""
        mgr = VideoTaskManager()
        task = mgr.create_task(
            filename="abc123.mp4",
            original_name="assembly.mp4",
            size=1024000,
            station_id="WS-01",
            video_format="mp4",
        )

        assert task["status"] == TaskStatus.PENDING
        assert task["filename"] == "abc123.mp4"
        assert task["original_name"] == "assembly.mp4"
        assert task["size"] == 1024000
        assert task["station_id"] == "WS-01"
        assert task["format"] == "mp4"
        assert "task_id" in task
        assert "created_at" in task

    def test_list_tasks_returns_all(self):
        """list_tasks() returns all created tasks."""
        mgr = VideoTaskManager()
        mgr.create_task("a.mp4", "a.mp4", 100, "WS-01", "mp4")
        mgr.create_task("b.mp4", "b.mp4", 200, "WS-02", "avi")

        tasks = mgr.list_tasks()
        assert len(tasks) == 2

    def test_get_task_by_id(self):
        """get_task() returns the correct task or None."""
        mgr = VideoTaskManager()
        task = mgr.create_task("a.mp4", "a.mp4", 100, "WS-01", "mp4")
        task_id = task["task_id"]

        found = mgr.get_task(task_id)
        assert found is not None
        assert found["task_id"] == task_id

        not_found = mgr.get_task("nonexistent-id")
        assert not_found is None

    def test_start_task_changes_status(self):
        """start_task() changes status from pending to processing."""
        mgr = VideoTaskManager()
        task = mgr.create_task("a.mp4", "a.mp4", 100, "WS-01", "mp4")
        task_id = task["task_id"]

        result = mgr.start_task(task_id)
        assert result is True
        assert mgr.get_task(task_id)["status"] == TaskStatus.PROCESSING
        assert "started_at" in mgr.get_task(task_id)

    def test_start_task_rejects_if_another_processing(self):
        """Only one task can be processing at a time."""
        mgr = VideoTaskManager()
        t1 = mgr.create_task("a.mp4", "a.mp4", 100, "WS-01", "mp4")
        t2 = mgr.create_task("b.mp4", "b.mp4", 200, "WS-02", "avi")

        mgr.start_task(t1["task_id"])
        result = mgr.start_task(t2["task_id"])
        assert result is False
        assert mgr.get_task(t2["task_id"])["status"] == TaskStatus.PENDING

    def test_start_task_rejects_if_already_completed(self):
        """Cannot start a task that is already completed."""
        mgr = VideoTaskManager()
        task = mgr.create_task("a.mp4", "a.mp4", 100, "WS-01", "mp4")
        mgr.start_task(task["task_id"])
        mgr.complete_task(task["task_id"])

        result = mgr.start_task(task["task_id"])
        assert result is False

    def test_complete_task(self):
        """complete_task() changes status to completed with duration."""
        mgr = VideoTaskManager()
        task = mgr.create_task("a.mp4", "a.mp4", 100, "WS-01", "mp4")
        mgr.start_task(task["task_id"])

        time.sleep(0.05)  # small delay for duration measurement
        mgr.complete_task(task["task_id"], total_frames=500, duration_s=45.2)

        updated = mgr.get_task(task["task_id"])
        assert updated["status"] == TaskStatus.COMPLETED
        assert updated["total_frames"] == 500
        assert updated["duration_s"] == 45.2
        assert "completed_at" in updated
        # Verify processing duration was recorded
        assert updated["started_at"] is not None
        assert updated["completed_at"] is not None

    def test_fail_task(self):
        """fail_task() changes status to failed with error message."""
        mgr = VideoTaskManager()
        task = mgr.create_task("a.mp4", "a.mp4", 100, "WS-01", "mp4")
        mgr.start_task(task["task_id"])

        mgr.fail_task(task["task_id"], error="Redis connection lost")

        updated = mgr.get_task(task["task_id"])
        assert updated["status"] == TaskStatus.FAILED
        assert updated["error"] == "Redis connection lost"
        assert "completed_at" in updated

    def test_cancel_task(self):
        """cancel_task() sets status to cancelled."""
        mgr = VideoTaskManager()
        task = mgr.create_task("a.mp4", "a.mp4", 100, "WS-01", "mp4")
        mgr.start_task(task["task_id"])

        mgr.cancel_task(task["task_id"])
        assert mgr.get_task(task["task_id"])["status"] == TaskStatus.CANCELLED

    def test_cancel_non_processing_task_is_noop(self):
        """Cancelling a completed/failed task is a no-op (returns False)."""
        mgr = VideoTaskManager()
        task = mgr.create_task("a.mp4", "a.mp4", 100, "WS-01", "mp4")
        result = mgr.cancel_task(task["task_id"])
        assert result is False

    def test_timeout_detection(self):
        """Tasks exceeding timeout are marked failed."""
        mgr = VideoTaskManager(task_timeout_s=0.1)
        task = mgr.create_task("a.mp4", "a.mp4", 100, "WS-01", "mp4")
        mgr.start_task(task["task_id"])

        time.sleep(0.2)
        timed_out = mgr.check_timeouts()
        assert timed_out == [task["task_id"]]
        assert mgr.get_task(task["task_id"])["status"] == TaskStatus.FAILED
        assert "timed out" in mgr.get_task(task["task_id"])["error"].lower()


class TestVideoTaskAPIs:
    """T9-02: Video task REST API tests."""

    ENDPOINT_TASKS = "/api/v1/video/tasks"

    @pytest.fixture(autouse=True)
    def _reset_manager(self):
        """Reset singleton between API tests to avoid cross-test state."""
        from app.services.video_task_manager import reset_task_manager
        reset_task_manager()
        yield
        reset_task_manager()

    def test_list_tasks_empty(self, client, auth_headers):
        """GET /api/v1/video/tasks returns empty list when no tasks."""
        resp = client.get(self.ENDPOINT_TASKS, headers=auth_headers)
        assert resp.status_code == 200
        assert resp.json()["data"] == []

    def test_list_tasks_after_upload(self, client, auth_headers, tmp_path):
        """After upload, task appears in list."""
        from tests.test_video_upload import TestVideoUpload
        video_data = TestVideoUpload.MP4_HEADER + b"\x00" * 100

        with patch("app.api.v1.video.VIDEO_UPLOAD_DIR", tmp_path), \
             patch("app.api.v1.video.VIDEO_SIZE_LIMIT_MB", 500):
            upload_resp = client.post(
                "/api/v1/video/upload",
                files=[TestVideoUpload._upload_file(video_data, "test.mp4")],
                headers=auth_headers,
            )

        task_id = upload_resp.json()["data"]["task_id"]

        resp = client.get(self.ENDPOINT_TASKS, headers=auth_headers)
        assert resp.status_code == 200
        tasks = resp.json()["data"]
        assert len(tasks) >= 1
        assert any(t["task_id"] == task_id for t in tasks)

    def test_get_task_detail(self, client, auth_headers, tmp_path):
        """GET /api/v1/video/tasks/{id} returns single task."""
        from tests.test_video_upload import TestVideoUpload
        video_data = TestVideoUpload.MP4_HEADER + b"\x00" * 100

        with patch("app.api.v1.video.VIDEO_UPLOAD_DIR", tmp_path), \
             patch("app.api.v1.video.VIDEO_SIZE_LIMIT_MB", 500):
            upload_resp = client.post(
                "/api/v1/video/upload",
                files=[TestVideoUpload._upload_file(video_data, "test.mp4")],
                headers=auth_headers,
            )

        task_id = upload_resp.json()["data"]["task_id"]

        resp = client.get(f"{self.ENDPOINT_TASKS}/{task_id}", headers=auth_headers)
        assert resp.status_code == 200
        assert resp.json()["data"]["task_id"] == task_id

    def test_get_task_not_found(self, client, auth_headers):
        """GET /api/v1/video/tasks/{id} returns 404 for unknown id."""
        resp = client.get(f"{self.ENDPOINT_TASKS}/nonexistent", headers=auth_headers)
        assert resp.status_code == 404
