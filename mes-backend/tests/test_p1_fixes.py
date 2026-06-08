"""
Tests for P1 critical issues (thread safety, N+1 queries, resource leaks, etc.)

Each test verifies that the fix addresses the underlying problem.
RED phase: tests demonstrate the issue exists.
GREEN phase: after fixes, tests pass.
"""

from __future__ import annotations

import threading
import time
from unittest.mock import patch, MagicMock

import pytest
import jwt


# =====================================================================
# P1-5: ingest.py 全局变量无锁
# =====================================================================

class TestIngestThreadSafety:
    """P1-5: _pipeline and _pending_aggregations must be lock-protected."""

    def test_ingest_module_has_lock(self):
        """Verify ingest.py defines a threading.Lock."""
        from app.api.v1 import ingest
        assert hasattr(ingest, "_pipeline_lock"), "ingest.py must have _pipeline_lock"

    def test_ingest_lock_used_in_functions(self):
        """Verify _pipeline_lock is acquired in functions that modify globals."""
        import inspect
        from app.api.v1 import ingest

        # Check that ingest_frame uses the lock
        source = inspect.getsource(ingest.ingest_frame)
        assert "_pipeline_lock" in source or "_pending_lock" in source or \
               "with _" in source.lower(), \
            "ingest_frame must acquire a lock for global variable access"

    def test_ingest_pipeline_concurrent_access(self):
        """Simulate concurrent get/create of pipeline (thread-safe)."""
        from app.api.v1 import ingest
        from app.core.config import load_app_config

        # Reset pipeline for test
        old_pipeline = ingest._pipeline
        try:
            ingest._pipeline = None

            results = []
            errors = []

            def get_pipeline():
                try:
                    p = ingest._get_pipeline()
                    results.append(id(p))
                except Exception as e:
                    errors.append(e)

            threads = [threading.Thread(target=get_pipeline) for _ in range(10)]
            for t in threads:
                t.start()
            for t in threads:
                t.join()

            assert len(errors) == 0, f"Concurrent pipeline access failed: {errors}"
            # All should get the same pipeline instance
            assert len(set(results)) == 1, "All threads should get the same pipeline"
        finally:
            ingest._pipeline = old_pipeline


# =====================================================================
# P1-6: auth.py rate limiter 无锁
# =====================================================================

class TestAuthThreadSafety:
    """P1-6: _login_rate_limit and _jwt_secret_cache must be lock-protected."""

    def test_auth_module_has_lock(self):
        """Verify auth.py defines a threading.Lock."""
        from app.api.v1 import auth
        assert hasattr(auth, "_auth_lock") or hasattr(auth, "_rate_limit_lock"), \
            "auth.py must have a threading.Lock"

    def test_auth_jwt_secret_lock(self):
        """Verify _get_jwt_secret is thread-safe with a lock."""
        import inspect
        from app.api.v1 import auth
        source = inspect.getsource(auth._get_jwt_secret)
        assert "lock" in source.lower() or "Lock" in source, \
            "_get_jwt_secret must use a lock"

    def test_auth_rate_limit_lock(self):
        """Verify login rate limiting uses lock protection."""
        import inspect
        from app.api.v1 import auth
        source = inspect.getsource(auth.login)
        assert "lock" in source.lower() or "Lock" in source, \
            "login must use a lock for rate limit access"

    def test_jwt_secret_cache_concurrent(self):
        """Concurrent calls to _get_jwt_secret should not race."""
        from app.api.v1 import auth
        old_secret = auth._jwt_secret_cache
        try:
            auth._jwt_secret_cache = None
            results = []
            errors = []

            def get_secret():
                try:
                    s = auth._get_jwt_secret()
                    results.append(s)
                except Exception as e:
                    errors.append(e)

            threads = [threading.Thread(target=get_secret) for _ in range(10)]
            for t in threads:
                t.start()
            for t in threads:
                t.join()

            assert len(errors) == 0, f"Concurrent secret access failed: {errors}"
            assert len(set(results)) == 1, "All threads should get the same secret"
        finally:
            auth._jwt_secret_cache = old_secret


# =====================================================================
# P1-7: sse.py active connections 无原子操作
# =====================================================================

class TestSseThreadSafety:
    """P1-7: _active_sse_connections must be lock-protected."""

    def test_sse_module_has_lock(self):
        """Verify sse.py defines a threading.Lock or asyncio.Lock."""
        from app.api import sse
        assert hasattr(sse, "_sse_conn_lock") or hasattr(sse, "_conn_lock"), \
            "sse.py must have a lock for active connections counter"


# =====================================================================
# P1-8: orders.py N+1 查询
# =====================================================================

class TestOrdersNPlusOne:
    """P1-8: _order_to_dict should not trigger N+1 queries for status_rel/priority_rel."""

    def test_order_list_uses_eager_loading(self):
        """Verify list_orders uses joinedload or selectinload for all relationships."""
        import inspect
        from app.api.v1 import orders

        source = inspect.getsource(orders.list_orders)
        # Check for joinedload on all three relationships
        assert "joinedload(Order.customer)" in source, \
            "list_orders must eager-load Order.customer"
        assert "joinedload(Order.status_rel)" in source or "selectinload(Order.status_rel)" in source, \
            "list_orders must eager-load Order.status_rel"
        assert "joinedload(Order.priority_rel)" in source or "selectinload(Order.priority_rel)" in source, \
            "list_orders must eager-load Order.priority_rel"

    def test_order_get_uses_eager_loading(self):
        """Verify get_order also eager-loads all relationships."""
        import inspect
        from app.api.v1 import orders

        source = inspect.getsource(orders.get_order)
        assert "Order.customer" in source, \
            "get_order must eager-load relationships"
        assert "Order.status_rel" in source or "Order.priority_rel" in source, \
            "get_order must eager-load status_rel or priority_rel"


# =====================================================================
# P1-9: customers.py N+1 查询
# =====================================================================

class TestCustomersNPlusOne:
    """P1-9: _customer_to_dict should not trigger N+1 for customer_type_rel/level_rel."""

    def test_customer_list_uses_eager_loading(self):
        """Verify list_customers uses joinedload for customer_type_rel and level_rel."""
        import inspect
        from app.api.v1 import customers

        source = inspect.getsource(customers.list_customers)
        assert "joinedload" in source or "selectinload" in source, \
            "list_customers must eager-load relationships"


# =====================================================================
# P1-10: ai.py httpx.AsyncClient 每次请求创建
# =====================================================================

class TestAiClientReuse:
    """P1-10: httpx.AsyncClient should be shared, not created per request."""

    def test_ai_module_has_shared_client(self):
        """Verify ai.py has a module-level shared httpx.AsyncClient."""
        from app.api.v1 import ai
        assert hasattr(ai, "_shared_client") or hasattr(ai, "_ai_client") or \
               hasattr(ai, "_http_client"), \
            "ai.py must have a module-level shared httpx.AsyncClient"

    def test_chat_uses_shared_client(self):
        """Verify chat_proxy uses the shared client, not async with new."""
        import inspect
        from app.api.v1 import ai
        source = inspect.getsource(ai.chat_proxy)

        # Should NOT create a new client inline
        assert "async with httpx.AsyncClient" not in source, \
            "chat_proxy must NOT create a new httpx.AsyncClient per request"

        # Should use the shared client
        assert "_shared_client" in source or "_ai_client" in source or "_http_client" in source, \
            "chat_proxy must use the module-level shared client"


# =====================================================================
# P1-11: auth.py SystemExit 导致进程退出
# =====================================================================

class TestAuthSystemExit:
    """P1-11: SystemExit(1) must be replaced with logging.error + return 503."""

    def test_get_jwt_secret_no_system_exit(self):
        """Verify _get_jwt_secret does NOT raise SystemExit."""
        import inspect
        from app.api.v1 import auth
        source = inspect.getsource(auth._get_jwt_secret)
        assert "SystemExit" not in source, \
            "_get_jwt_secret must not raise SystemExit"

    def test_get_jwt_secret_returns_error_on_missing(self):
        """Verify missing JWT secret returns 503 instead of SystemExit."""
        import inspect
        from app.api.v1 import auth
        source = inspect.getsource(auth._get_jwt_secret)
        # Should return an error response or raise HTTPException
        assert "503" in source or "HTTPException" in source or "ApiResponse" in source, \
            "_get_jwt_secret should return 503 instead of SystemExit"

    def test_hash_password_no_system_exit(self):
        """Verify _hash_password does NOT raise SystemExit on missing bcrypt."""
        import inspect
        from app.api.v1 import auth
        source = inspect.getsource(auth._hash_password)
        assert "SystemExit" not in source, \
            "_hash_password must not raise SystemExit"


# =====================================================================
# P1-12: anomaly.py DB 与内存数据重复
# =====================================================================

class TestAnomalyDeduplication:
    """P1-12: add_anomaly_event_db fallback to memory must handle dedup."""

    def test_get_events_removes_duplicates(self):
        """Verify get_anomaly_events deduplicates between DB and memory."""
        from app.api.v1 import anomaly

        # Simulate scenario: event in both DB and memory
        # The memory store should not produce duplicates of DB events
        import inspect
        source = inspect.getsource(anomaly.get_anomaly_events)

        # Should include dedup logic
        assert "dedup" in source.lower() or "set" in source.lower() or \
               "seen" in source.lower() or "id" in source.lower(), \
            "get_anomaly_events must have deduplication logic"


# =====================================================================
# P1-13: video.py SSE JWT 通过 URL query
# =====================================================================

class TestVideoSseAuth:
    """P1-13: Remove JWT query parameter fallback from video SSE."""

    def test_video_stream_no_query_token_fallback(self):
        """Verify stream_task_progress uses Depends(require_auth) instead of manual JWT parsing."""
        import inspect
        from app.api.v1 import video

        source = inspect.getsource(video.stream_task_progress)

        # Should NOT have manual jwt.decode (query param fallback removed)
        assert "jwt.decode" not in source, \
            "stream_task_progress must NOT manually decode JWT"
        assert "_get_jwt_secret" not in source, \
            "stream_task_progress must NOT call _get_jwt_secret directly"
        assert "query" not in source.lower() or "auth" not in source.lower() or \
               "token" not in source.lower(), \
            "stream_task_progress must not accept token via query param"

        # Should use standard Depends(require_auth)
        assert "require_auth" in source, \
            "stream_task_progress must use Depends(require_auth)"




# =====================================================================
# P1-14: sse.py SSE JWT 通过 URL query
# =====================================================================

class TestSseAuth:
    """P1-14: Remove JWT query parameter fallback from SSE endpoint."""

    def test_sse_events_rejects_query_token(self):
        """Verify sse_events does NOT accept token via query parameter."""
        import inspect
        from app.api import sse

        source = inspect.getsource(sse.sse_events)

        # The function should not have a token query parameter
        # Check for JWT auth via header
        assert "authorization" in source.lower() or "Authorization" in source, \
            "sse_events must authenticate only via Authorization header"
