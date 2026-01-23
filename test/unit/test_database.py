"""Unit tests for database helper functions."""
import pytest
import sqlite3


@pytest.mark.unit
class TestGetDb:
    def test_returns_connection_with_row_factory(self, test_app, temp_db_path):
        """get_db should return connection with sqlite3.Row factory."""
        import server
        with server.get_db() as conn:
            assert conn.row_factory == sqlite3.Row

    def test_connection_closes_after_context(self, test_app, temp_db_path):
        """Connection should be closed after context manager exits."""
        import server
        conn_ref = None
        with server.get_db() as conn:
            conn_ref = conn
            cursor = conn.cursor()
            cursor.execute("SELECT 1")
        # After context, connection should be closed
        with pytest.raises(sqlite3.ProgrammingError):
            conn_ref.execute("SELECT 1")


@pytest.mark.unit
class TestInitDatabase:
    def test_creates_all_required_tables(self, test_app, temp_db_path):
        """init_database should create all required tables."""
        import server
        with server.get_db() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT name FROM sqlite_master WHERE type='table'")
            tables = {row[0] for row in cursor.fetchall()}

        expected_tables = {'clients', 'meta_sync', 'trackers', 'entries', 'sync_conflicts'}
        assert expected_tables.issubset(tables)

    def test_creates_required_indexes(self, test_app, temp_db_path):
        """init_database should create performance indexes."""
        import server
        with server.get_db() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT name FROM sqlite_master WHERE type='index'")
            indexes = {row[0] for row in cursor.fetchall()}

        expected_indexes = {
            'idx_trackers_name',
            'idx_entries_date',
            'idx_trackers_modified',
            'idx_entries_modified',
            'idx_conflicts_resolved'
        }
        assert expected_indexes.issubset(indexes)

    def test_trackers_table_has_versioning_columns(self, test_app, temp_db_path):
        """trackers table should have versioning columns."""
        import server
        with server.get_db() as conn:
            cursor = conn.cursor()
            cursor.execute("PRAGMA table_info(trackers)")
            columns = {row[1] for row in cursor.fetchall()}

        assert 'version' in columns
        assert 'last_modified_by' in columns
        assert 'last_modified_at' in columns
        assert 'deleted' in columns

    def test_entries_table_has_versioning_columns(self, test_app, temp_db_path):
        """entries table should have versioning columns."""
        import server
        with server.get_db() as conn:
            cursor = conn.cursor()
            cursor.execute("PRAGMA table_info(entries)")
            columns = {row[1] for row in cursor.fetchall()}

        assert 'version' in columns
        assert 'last_modified_by' in columns
        assert 'last_modified_at' in columns


@pytest.mark.unit
class TestGetUtcNow:
    def test_returns_iso_format_with_z_suffix(self, test_app):
        """get_utc_now should return ISO-8601 format with Z suffix."""
        import server
        result = server.get_utc_now()
        assert result.endswith("Z")
        assert "T" in result

    def test_returns_parseable_datetime(self, test_app):
        """get_utc_now should return parseable datetime string."""
        import server
        from datetime import datetime
        result = server.get_utc_now()
        # Should be parseable (remove Z and parse)
        parsed = datetime.fromisoformat(result.replace("Z", "+00:00"))
        assert parsed is not None

    def test_returns_current_time(self, test_app):
        """get_utc_now should return approximately current time."""
        import server
        from datetime import datetime, timezone
        result = server.get_utc_now()
        parsed = datetime.fromisoformat(result.replace("Z", "+00:00"))
        now = datetime.now(timezone.utc)
        # Should be within 1 second
        diff = abs((now - parsed).total_seconds())
        assert diff < 1
