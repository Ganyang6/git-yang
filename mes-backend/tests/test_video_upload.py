"""Tests for video upload API (T9-01) and pipeline trigger bridge (T9-02)."""

import io
import json
import os
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi.testclient import TestClient


class TestVideoUpload:
    """T9-01: Video upload endpoint tests."""

    ENDPOINT = "/api/v1/video/upload"

    @pytest.fixture(autouse=True)
    def _reset_manager(self):
        """Reset singleton between upload tests."""
        from app.services.video_task_manager import reset_task_manager
        reset_task_manager()
        yield
        reset_task_manager()

    # Video format magic bytes (file header signatures)
    MP4_HEADER = b"\x00\x00\x00\x20\x66\x74\x79\x70\x69\x73\x6f\x6d"  # minimal ftyp
    AVI_HEADER = b"RIFF\x00\x00\x00\x00AVI LIST"
    MOV_HEADER = b"\x00\x00\x00\x18\x66\x74\x79\x70\x71\x74\x20\x20"
    MKV_HEADER = b"\x1a\x45\xdf\xa3" + b"\x00" * 12
    TXT_CONTENT = b"This is not a video file"

    @staticmethod
    def _upload_file(content: bytes, filename: str = "test.mp4"):
        """Return httpx-compatible file tuple for TestClient."""
        return ("file", (filename, io.BytesIO(content), "video/mp4"))

    def test_upload_mp4_success(self, client, auth_headers, tmp_path):
        """POST /api/v1/video/upload with valid MP4 returns task info."""
        video_data = self.MP4_HEADER + b"\x00" * 100

        with patch("app.api.v1.video.VIDEO_UPLOAD_DIR", tmp_path), \
             patch("app.api.v1.video.VIDEO_SIZE_LIMIT_MB", 500):
            resp = client.post(
                self.ENDPOINT,
                files=[self._upload_file(video_data, "assembly.mp4")],
                headers=auth_headers,
            )

        assert resp.status_code == 200, f"Expected 200, got {resp.status_code}: {resp.text}"
        data = resp.json()["data"]
        assert data["status"] == "pending"  # Task registered, waiting to start
        assert data["filename"].endswith(".mp4")
        assert data["size"] == len(video_data)
        assert "task_id" in data
        assert len(data["task_id"]) == 36  # UUID format

    def test_upload_creates_file_on_disk(self, client, auth_headers, tmp_path):
        """Uploaded file is saved to VIDEO_UPLOAD_DIR with UUID filename."""
        video_data = self.MP4_HEADER + b"\x00" * 50

        with patch("app.api.v1.video.VIDEO_UPLOAD_DIR", tmp_path), \
             patch("app.api.v1.video.VIDEO_SIZE_LIMIT_MB", 500):
            resp = client.post(
                self.ENDPOINT,
                files=[self._upload_file(video_data, "test.mp4")],
                headers=auth_headers,
            )

        assert resp.status_code == 200
        saved_name = resp.json()["data"]["filename"]
        saved_path = tmp_path / saved_name
        assert saved_path.exists()
        assert saved_path.read_bytes() == video_data

    def test_upload_rejects_invalid_format(self, client, auth_headers, tmp_path):
        """Non-video file (detected by header) is rejected with 400."""
        with patch("app.api.v1.video.VIDEO_UPLOAD_DIR", tmp_path), \
             patch("app.api.v1.video.VIDEO_SIZE_LIMIT_MB", 500):
            resp = client.post(
                self.ENDPOINT,
                files=[("file", ("fake.mp4", io.BytesIO(self.TXT_CONTENT), "video/mp4"))],
                headers=auth_headers,
            )

        assert resp.status_code == 400

    def test_upload_rejects_file_too_large(self, client, auth_headers, tmp_path):
        """File exceeding size limit is rejected with 413."""
        big_content = self.MP4_HEADER + b"\x00" * (1024 * 1024)

        with patch("app.api.v1.video.VIDEO_UPLOAD_DIR", tmp_path), \
             patch("app.api.v1.video.VIDEO_SIZE_LIMIT_MB", 1):
            resp = client.post(
                self.ENDPOINT,
                files=[self._upload_file(big_content, "big.mp4")],
                headers=auth_headers,
            )

        assert resp.status_code == 413

    def test_upload_avi_format_accepted(self, client, auth_headers, tmp_path):
        """AVI format is accepted (header-based detection)."""
        video_data = self.AVI_HEADER + b"\x00" * 100

        with patch("app.api.v1.video.VIDEO_UPLOAD_DIR", tmp_path), \
             patch("app.api.v1.video.VIDEO_SIZE_LIMIT_MB", 500):
            resp = client.post(
                self.ENDPOINT,
                files=[("file", ("clip.avi", io.BytesIO(video_data), "video/avi"))],
                headers=auth_headers,
            )

        assert resp.status_code == 200
        assert resp.json()["data"]["status"] == "pending"

    def test_upload_mov_format_accepted(self, client, auth_headers, tmp_path):
        """MOV format is accepted (header-based detection)."""
        video_data = self.MOV_HEADER + b"\x00" * 100

        with patch("app.api.v1.video.VIDEO_UPLOAD_DIR", tmp_path), \
             patch("app.api.v1.video.VIDEO_SIZE_LIMIT_MB", 500):
            resp = client.post(
                self.ENDPOINT,
                files=[("file", ("clip.mov", io.BytesIO(video_data), "video/quicktime"))],
                headers=auth_headers,
            )

        assert resp.status_code == 200
        assert resp.json()["data"]["format"] == "mov"

    def test_upload_mkv_format_accepted(self, client, auth_headers, tmp_path):
        """MKV format is accepted (header-based detection)."""
        video_data = self.MKV_HEADER + b"\x00" * 100

        with patch("app.api.v1.video.VIDEO_UPLOAD_DIR", tmp_path), \
             patch("app.api.v1.video.VIDEO_SIZE_LIMIT_MB", 500):
            resp = client.post(
                self.ENDPOINT,
                files=[("file", ("clip.mkv", io.BytesIO(video_data), "video/x-matroska"))],
                headers=auth_headers,
            )

        assert resp.status_code == 200

    def test_upload_auto_creates_directory(self, client, auth_headers, tmp_path):
        """VIDEO_UPLOAD_DIR is created if it does not exist."""
        nonexistent = tmp_path / "subdir" / "videos"
        assert not nonexistent.exists()

        video_data = self.MP4_HEADER + b"\x00" * 50

        with patch("app.api.v1.video.VIDEO_UPLOAD_DIR", nonexistent), \
             patch("app.api.v1.video.VIDEO_SIZE_LIMIT_MB", 500):
            resp = client.post(
                self.ENDPOINT,
                files=[self._upload_file(video_data, "test.mp4")],
                headers=auth_headers,
            )

        assert resp.status_code == 200
        assert nonexistent.exists()

    def test_upload_triggers_pipeline_and_starts_task(self, client, auth_headers, tmp_path):
        """After upload, task transitions to 'processing' and a Redis command is published."""
        video_data = self.MP4_HEADER + b"\x00" * 100

        mock_redis = MagicMock()
        mock_redis.is_connected = True
        mock_redis.publish_channel = AsyncMock(return_value=True)

        with patch("app.api.v1.video.VIDEO_UPLOAD_DIR", tmp_path), \
             patch("app.api.v1.video.VIDEO_SIZE_LIMIT_MB", 500), \
             patch("app.api.v1.video._get_redis_client", return_value=mock_redis), \
             patch("app.api.v1.video._publish_pipeline_command", new_callable=AsyncMock) as mock_publish:
            resp = client.post(
                self.ENDPOINT,
                files=[self._upload_file(video_data, "pipeline_test.mp4")],
                headers=auth_headers,
            )

        assert resp.status_code == 200, f"Expected 200, got {resp.status_code}: {resp.text}"
        data = resp.json()["data"]
        task_id = data["task_id"]

        # Task should be in 'processing' state (not stuck at 'pending')
        assert data["status"] == "processing"

        # Verify _publish_pipeline_command was called with correct arguments
        mock_publish.assert_called_once()
        call_kwargs = mock_publish.call_args[1] if mock_publish.call_args[1] else {}
        assert call_kwargs.get("task_id") == task_id
        assert call_kwargs.get("filename") == data["filename"]
        assert call_kwargs.get("station_id") == "WS-01"

    def test_upload_no_redis_falls_back_to_pending(self, client, auth_headers, tmp_path):
        """When Redis is unavailable, upload succeeds but task stays 'pending'."""
        video_data = self.MP4_HEADER + b"\x00" * 100

        with patch("app.api.v1.video.VIDEO_UPLOAD_DIR", tmp_path), \
             patch("app.api.v1.video.VIDEO_SIZE_LIMIT_MB", 500), \
             patch("app.api.v1.video._get_redis_client", return_value=None):
            resp = client.post(
                self.ENDPOINT,
                files=[self._upload_file(video_data, "no_redis.mp4")],
                headers=auth_headers,
            )

        assert resp.status_code == 200
        assert resp.json()["data"]["status"] == "pending"
