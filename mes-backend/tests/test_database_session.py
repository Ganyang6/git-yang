"""
Tests for database session lifecycle:
- sessionmaker caching in get_session() (P0-2)
- session leak removal from init_db() (P0-3)
"""

import os


def test_get_session_caches_sessionmaker():
    """get_session() should reuse a cached sessionmaker, not create a new one each call."""
    from app.models.database import get_session
    from sqlalchemy.orm import sessionmaker

    # Track sessionmaker construction
    import app.models.database as db_mod
    original_get_session = db_mod.get_session

    construction_count = [0]

    # Monkey-patch sessionmaker class to count constructions
    original_sm_init = sessionmaker.__init__

    def tracked_sm_init(self, *args, **kwargs):
        construction_count[0] += 1
        original_sm_init(self, *args, **kwargs)

    sessionmaker.__init__ = tracked_sm_init

    try:
        # Call get_session multiple times
        s1 = get_session("sqlite:///:memory:")
        s2 = get_session("sqlite:///:memory:")
        count_after_2 = construction_count[0]

        s3 = get_session("sqlite:///:memory:")
        s4 = get_session("sqlite:///:memory:")
        count_after_4 = construction_count[0]

        s1.close()
        s2.close()
        s3.close()
        s4.close()

        # Should have created at most 1 sessionmaker
        assert count_after_2 == 1, (
            f"Expected 1 sessionmaker after 2 calls, got {count_after_2}. "
            "sessionmaker is being re-created each time."
        )
        assert count_after_4 == 1, (
            f"Expected 1 sessionmaker after 4 calls, got {count_after_4}. "
            "sessionmaker cache is not working."
        )
    finally:
        sessionmaker.__init__ = original_sm_init


def test_init_db_no_session_leak():
    """init_db() should NOT return a session object that can leak."""
    from app.models.database import init_db

    result = init_db("sqlite:///:memory:")
    # init_db should return None, not a Session
    assert result is None, (
        f"Expected init_db() to return None, got {type(result).__name__}. "
        "This leaks unmanaged sessions."
    )
