"""Tests for VideoTaskManager with Redis backend (T9-02)."""

import asyncio
import time
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.services.video_task_manager import VideoTaskManager, TaskStatus


class TestVideoTaskManagerRedis:
    """T9-02: VideoTaskManager Redis backend tests."""

    @patch('app.services.video_task_manager.RedisClient')
    def test_redis_backend_creation(self, mock_redis_client):
        """Creating VideoTaskManager with Redis backend should use Redis storage."""
        # Mock RedisClient to return a connected client
        mock_instance = AsyncMock()
        mock_instance.is_connected = True
        mock_redis_client.return_value = mock_instance
        
        mgr = VideoTaskManager(use_redis=True)
        assert mgr.use_redis is True

    def test_redis_backend_fallback_to_in_memory(self):
        """When Redis connection fails, should fall back to in-memory storage."""
        # This test verifies that the manager gracefully falls back to in-memory
        # when Redis is not available
        mgr = VideoTaskManager(use_redis=True)
        assert mgr.use_redis is False  # Should have fallen back
        
        # Test basic functionality still works
        task = mgr.create_task(
            filename="test.mp4",
            original_name="test.mp4",
            size=1000,
            station_id="WS-01",
            video_format="mp4",
        )
        assert task["status"] == TaskStatus.PENDING
        assert mgr.get_task(task["task_id"]) is not None

    def test_get_task_manager_with_redis(self):
        """Test get_task_manager function with Redis support."""
        from app.services.video_task_manager import get_task_manager, reset_task_manager
        
        # Reset the singleton
        reset_task_manager()
        
        # Get manager with Redis support
        mgr = get_task_manager(use_redis=True)
        assert mgr is not None
        
        # Reset again for clean state
        reset_task_manager()

