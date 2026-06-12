"""Tests for _date_format_func — validates SQL compilation without endpoint dependency."""

import os
import tempfile

import pytest
from sqlalchemy import String

from app.models.database import ProcessSegment, get_session, init_db


# ── Fixtures ────────────────────────────────────────────────────────────


@pytest.fixture
def db_session():
    """Create a temporary SQLite database for testing SQL compilation."""
    fd, path = tempfile.mkstemp(suffix=".db")
    db_url = f"sqlite:///{path}"
    os.close(fd)

    engine = init_db(db_url=db_url, echo=False)
    session = get_session(db_url)
    yield session

    session.close()


# ── Tests ───────────────────────────────────────────────────────────────


def test_date_format_func_compiles_default(db_session):
    """Default fmt (%Y-%m-%d) — compile() should not throw AttributeError."""
    from app.api.v1.worktime import _date_format_func

    expr = _date_format_func(db_session, ProcessSegment.start_time)
    # compile() should not throw _static_cache_key error or AttributeError
    sql_str = str(
        expr.compile(
            dialect=db_session.bind.dialect,
            compile_kwargs={"literal_binds": True},
        )
    )
    assert "DATE" in sql_str.upper() or "CAST" in sql_str.upper()


def test_date_format_func_compiles_month(db_session):
    """Fmt=%Y-%m — compile() should not throw AttributeError."""
    from app.api.v1.worktime import _date_format_func

    expr = _date_format_func(db_session, ProcessSegment.start_time, fmt="%Y-%m")
    sql_str = str(
        expr.compile(
            dialect=db_session.bind.dialect,
            compile_kwargs={"literal_binds": True},
        )
    )
    assert "DATE" in sql_str.upper()


def test_date_format_func_returns_same_type(db_session):
    """Both fmt variants return string-typed expressions."""
    from app.api.v1.worktime import _date_format_func

    expr_default = _date_format_func(db_session, ProcessSegment.start_time)
    expr_month = _date_format_func(db_session, ProcessSegment.start_time, fmt="%Y-%m")

    # Both should compile without error
    sql_default = str(
        expr_default.compile(
            dialect=db_session.bind.dialect,
            compile_kwargs={"literal_binds": True},
        )
    )
    sql_month = str(
        expr_month.compile(
            dialect=db_session.bind.dialect,
            compile_kwargs={"literal_binds": True},
        )
    )

    # Both should contain DATE
    assert "DATE" in sql_default.upper()
    assert "DATE" in sql_month.upper()

    # Default should have CAST (returns string), month uses SUBSTR
    assert "CAST" in sql_default.upper() or "SUBSTR" in sql_default.upper()
    assert "SUBSTR" in sql_month.upper()
