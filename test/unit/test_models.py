"""Unit tests for Pydantic models."""
import pytest
from pydantic import ValidationError


@pytest.mark.unit
class TestTrackerConfig:
    def test_valid_tracker_config(self, test_app):
        """Valid tracker config should pass validation."""
        import server
        config = server.TrackerConfig(
            id="test-id",
            name="Test Tracker",
            category="health",
            type="simple"
        )
        assert config.id == "test-id"
        assert config.name == "Test Tracker"
        assert config.category == "health"
        assert config.type == "simple"

    def test_default_values(self, test_app):
        """TrackerConfig should have sensible defaults."""
        import server
        config = server.TrackerConfig(id="test", name="Test")
        assert config.category == ""
        assert config.type == "simple"

    def test_allows_extra_fields(self, test_app):
        """TrackerConfig should allow extra fields (for meta_json)."""
        import server
        config = server.TrackerConfig(
            id="test-id",
            name="Test",
            unit="cups",
            goal=8,
            minValue=0
        )
        # Extra fields should be accessible via model_extra
        assert config.model_extra.get("unit") == "cups"
        assert config.model_extra.get("goal") == 8

    def test_missing_id_raises(self, test_app):
        """Missing id field should raise ValidationError."""
        import server
        with pytest.raises(ValidationError):
            server.TrackerConfig(name="Test")

    def test_missing_name_raises(self, test_app):
        """Missing name field should raise ValidationError."""
        import server
        with pytest.raises(ValidationError):
            server.TrackerConfig(id="test")


@pytest.mark.unit
class TestTrackerEntry:
    def test_valid_entry(self, test_app):
        """Valid tracker entry should pass validation."""
        import server
        entry = server.TrackerEntry(value=5.0, completed=True)
        assert entry.value == 5.0
        assert entry.completed is True

    def test_all_optional(self, test_app):
        """All fields should be optional."""
        import server
        entry = server.TrackerEntry()
        assert entry.value is None
        assert entry.completed is None


@pytest.mark.unit
class TestSyncPayload:
    def test_valid_sync_payload(self, test_app):
        """Valid sync payload should pass validation."""
        import server
        payload = server.SyncPayload(
            clientId="client-001",
            config=[],
            days={}
        )
        assert payload.clientId == "client-001"
        assert payload.config == []
        assert payload.days == {}

    def test_default_values(self, test_app):
        """SyncPayload should have sensible defaults."""
        import server
        payload = server.SyncPayload(clientId="client-001")
        assert payload.config == []
        assert payload.days == {}
        assert payload.lastSyncTime is None

    def test_missing_client_id_raises(self, test_app):
        """Missing clientId should raise ValidationError."""
        import server
        with pytest.raises(ValidationError):
            server.SyncPayload()

    def test_complex_days_structure(self, test_app):
        """SyncPayload should accept complex days structure."""
        import server
        payload = server.SyncPayload(
            clientId="client-001",
            days={
                "2024-01-15": {
                    "tracker-1": {"value": 5, "completed": True},
                    "tracker-2": {"value": None, "completed": False}
                },
                "2024-01-16": {
                    "tracker-1": {"value": 3}
                }
            }
        )
        assert "2024-01-15" in payload.days
        assert "tracker-1" in payload.days["2024-01-15"]


@pytest.mark.unit
class TestStatusResponse:
    def test_null_last_modified(self, test_app):
        """StatusResponse should handle null lastModified."""
        import server
        response = server.StatusResponse()
        assert response.lastModified is None

    def test_with_timestamp(self, test_app):
        """StatusResponse should accept timestamp."""
        import server
        response = server.StatusResponse(lastModified="2024-01-15T10:30:00Z")
        assert response.lastModified == "2024-01-15T10:30:00Z"


@pytest.mark.unit
class TestConflictInfo:
    def test_valid_conflict_info(self, test_app):
        """Valid ConflictInfo should pass validation."""
        import server
        conflict = server.ConflictInfo(
            entityType="tracker",
            entityId="tracker-001",
            serverVersion=2,
            clientBaseVersion=1,
            serverData={"name": "Server Version"}
        )
        assert conflict.entityType == "tracker"
        assert conflict.serverVersion == 2
        assert conflict.clientBaseVersion == 1


@pytest.mark.unit
class TestSyncResponse:
    def test_successful_sync_response(self, test_app):
        """SyncResponse should represent successful sync."""
        import server
        response = server.SyncResponse(
            success=True,
            conflicts=[],
            appliedConfig=[{"id": "t1", "name": "Test"}],
            appliedDays={},
            lastModified="2024-01-15T10:30:00Z"
        )
        assert response.success is True
        assert len(response.conflicts) == 0
        assert len(response.appliedConfig) == 1

    def test_default_values(self, test_app):
        """SyncResponse should have sensible defaults."""
        import server
        response = server.SyncResponse(success=True)
        assert response.conflicts == []
        assert response.appliedConfig == []
        assert response.appliedDays == {}
        assert response.overwrittenData == []
