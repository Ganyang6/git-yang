"""
Tests for ActionEventConsumer session pooling (P0-5).

Verifies that _persist_to_sqlite reuses a single session across events
rather than creating a new one per event, preventing DB lock errors.
"""

import os
import tempfile


def test_consumer_reuses_session_instead_of_creating_new():
    """ActionEventConsumer should cache a single DB session, not create per event."""
    from unittest.mock import MagicMock, AsyncMock
    from app.services.stream_consumers import ActionEventConsumer
    from app.models.database import get_session

    mock_redis = MagicMock()
    mock_redis.consume_stream = AsyncMock(return_value=[])
    mock_redis.publish_action_event = AsyncMock()
    mock_redis.ack_message = AsyncMock()

    consumer = ActionEventConsumer(mock_redis)

    # Before any persist, _db_session should be None
    assert consumer._db_session is None, (
        "Session should not be created until first persist call"
    )

    # Setup a real DB
    with tempfile.NamedTemporaryFile(suffix='.db', delete=False) as f:
        db_path = f.name
    db_url = f"sqlite:///{db_path}"
    os.environ["MES_DB_URL"] = db_url

    from app.models.database import init_db
    init_db(db_url, echo=False)

    try:
        # Call _persist_to_sqlite with valid data
        consumer._db_session = get_session(db_url)

        # Track how many times get_session is called
        import app.models.database as db_mod
        original_get_session = db_mod.get_session
        get_session_call_count = [0]

        def tracking_get_session(*args, **kwargs):
            get_session_call_count[0] += 1
            return original_get_session(*args, **kwargs)

        db_mod.get_session = tracking_get_session

        try:
            # Persist multiple events
            for i in range(5):
                consumer._persist_to_sqlite(
                    camera_id="cam_1",
                    station_id="station_1",
                    action="reach",
                    therblig_symbol="RE",
                    shift="morning",
                    duration_ms=100.0,
                    confidence=0.95,
                    end_time=1000000.0 + i,
                )

            # After fix, get_session should NOT be called by _persist_to_sqlite
            # because it reuses self._db_session
            # Before fix: get_session would be called 5 times (one per event)
            assert get_session_call_count[0] == 0, (
                f"get_session() was called {get_session_call_count[0]} times. "
                "Expected 0 — _persist_to_sqlite should reuse self._db_session "
                "instead of calling get_session() each time."
            )
        finally:
            db_mod.get_session = original_get_session
    finally:
        os.unlink(db_path)
