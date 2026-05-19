"""
Test: legacy database schema migration for process_segments table.

Ensures that when a database already has a process_segments table WITHOUT
the `line` column, the migration logic in init_db (or a startup hook)
correctly adds it.
"""

import os
import tempfile
import pytest
from sqlalchemy import create_engine, inspect, text


# ── Fixture: create an OLD-SCHEMA database (no `line` column) ─────────────

@pytest.fixture(scope="module")
def _old_schema_db():
    """Create a SQLite DB with an *old* process_segments table (no `line` column).

    This simulates what would happen if the database was created before the
    `line` field was added to the ProcessSegment model.
    """
    fd, path = tempfile.mkstemp(suffix=".db", prefix="mes_legacy_")
    os.close(fd)

    engine = create_engine(f"sqlite:///{path}")
    # Create the OLD schema — no `line` column
    with engine.begin() as conn:
        conn.execute(text("""
            CREATE TABLE process_segments (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                camera_id VARCHAR(32) NOT NULL,
                station_id VARCHAR(32) NOT NULL,
                action VARCHAR(32) NOT NULL,
                therblig_symbol VARCHAR(8),
                start_time DATETIME NOT NULL,
                end_time DATETIME NOT NULL,
                duration_ms FLOAT NOT NULL,
                confidence FLOAT NOT NULL DEFAULT 0.0,
                shift VARCHAR(16) NOT NULL DEFAULT 'morning',
                worktime_record_id INTEGER,
                created_at DATETIME
            )
        """))
        # Create a second table so we can verify it's left untouched
        conn.execute(text("""
            CREATE TABLE worktime_records (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                operation VARCHAR(64) NOT NULL,
                station_id VARCHAR(32) NOT NULL,
                actual_ms FLOAT NOT NULL,
                standard_ms FLOAT NOT NULL DEFAULT 0.0,
                efficiency FLOAT NOT NULL DEFAULT 0.0,
                mod_total FLOAT NOT NULL DEFAULT 0.0,
                shift VARCHAR(16) NOT NULL DEFAULT 'morning',
                created_at DATETIME
            )
        """))

    yield path, engine
    engine.dispose()
    try:
        os.unlink(path)
    except OSError:
        pass


# ── Test: migration adds `line` column ───────────────────────────────────

class TestSchemaMigration:

    def test_migration_adds_line_column(self, _old_schema_db):
        """After running _ensure_migration, the `line` column should exist."""
        db_path, engine = _old_schema_db

        # Verify `line` does NOT exist before migration
        inspector = inspect(engine)
        cols_before = {c["name"] for c in inspector.get_columns("process_segments")}
        assert "line" not in cols_before, (
            f"Test setup broken: `line` already exists in process_segments: {cols_before}"
        )

        # ── Run migration ──────────────────────────────────────────────
        from app.models.database import _migrate_schema
        _migrate_schema(engine)

        # Verify `line` column was added
        cols_after = {c["name"] for c in inspector.get_columns("process_segments")}
        assert "line" in cols_after, (
            f"Migration did not add `line` column. Columns: {cols_after}"
        )

        # Verify schema is correct
        line_col = [
            c for c in inspector.get_columns("process_segments") if c["name"] == "line"
        ][0]
        assert line_col["nullable"] is True, "`line` should be nullable"

    def test_migration_idempotent(self, _old_schema_db):
        """Running migration twice should not error or change schema."""
        db_path, engine = _old_schema_db

        # Import and run migration twice
        from app.models.database import _migrate_schema

        _migrate_schema(engine)
        _migrate_schema(engine)  # second run — should be a no-op

        # Verify column exists
        inspector = inspect(engine)
        cols = {c["name"] for c in inspector.get_columns("process_segments")}
        assert "line" in cols, "Column should exist after idempotent migration"

    def test_migration_does_not_modify_other_tables(self, _old_schema_db):
        """Other tables should be left untouched by the migration."""
        db_path, engine = _old_schema_db

        from app.models.database import _migrate_schema
        _migrate_schema(engine)

        inspector = inspect(engine)
        wt_cols = {c["name"] for c in inspector.get_columns("worktime_records")}
        # worktime_records should NOT have `line`
        assert "line" not in wt_cols

    def test_migration_with_existing_data(self, _old_schema_db):
        """Existing rows should not be lost after migration."""
        db_path, engine = _old_schema_db

        # Insert a row into the old schema before migration
        with engine.begin() as conn:
            conn.execute(text("""
                INSERT INTO process_segments
                    (camera_id, station_id, action, start_time, end_time, duration_ms, confidence)
                VALUES ('cam1', 'st1', 'reach', '2025-01-01 00:00:00', '2025-01-01 00:00:05', 5000.0, 0.95)
            """))

        from app.models.database import _migrate_schema
        _migrate_schema(engine)

        # Data should still be there
        with engine.connect() as conn:
            rows = conn.execute(text("SELECT camera_id, station_id, action FROM process_segments")).fetchall()
        assert len(rows) == 1
        assert rows[0].camera_id == "cam1"

        # `line` in the old row should be NULL
        with engine.connect() as conn:
            lines = conn.execute(text("SELECT line FROM process_segments")).fetchall()
        assert lines[0].line is None, "Existing row should have NULL for new `line` column"
