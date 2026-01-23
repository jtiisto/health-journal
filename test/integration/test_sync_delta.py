"""Integration tests for GET /api/sync/delta endpoint."""
import pytest
from datetime import datetime, timedelta


@pytest.mark.integration
class TestSyncDelta:
    def test_returns_changes_since_timestamp(self, client, seeded_database):
        """Should return only changes since the given timestamp."""
        # Get a timestamp from the past
        past = (datetime.utcnow() - timedelta(hours=1)).isoformat() + "Z"

        response = client.get(
            f"/api/sync/delta?since={past}&client_id={seeded_database['client_id']}"
        )
        assert response.status_code == 200
        data = response.json()
        assert "config" in data
        assert "days" in data
        assert "deletedTrackers" in data
        assert "serverTime" in data

    def test_response_structure(self, client, seeded_database):
        """Response should have correct structure."""
        past = (datetime.utcnow() - timedelta(hours=1)).isoformat() + "Z"
        response = client.get(
            f"/api/sync/delta?since={past}&client_id={seeded_database['client_id']}"
        )
        data = response.json()

        assert isinstance(data["config"], list)
        assert isinstance(data["days"], dict)
        assert isinstance(data["deletedTrackers"], list)
        assert isinstance(data["serverTime"], str)

    def test_includes_deleted_tracker_ids(self, client, registered_client, sample_tracker):
        """Should include IDs of deleted trackers."""
        # Create tracker
        response = client.post("/api/sync/update", json={
            "clientId": registered_client,
            "config": [sample_tracker],
            "days": {}
        })
        sync_time = response.json()["lastModified"]

        # Delete tracker
        deleted_tracker = {**sample_tracker, "_deleted": True, "_baseVersion": 1}
        client.post("/api/sync/update", json={
            "clientId": registered_client,
            "config": [deleted_tracker],
            "days": {}
        })

        # Delta should include deleted tracker ID
        response = client.get(
            f"/api/sync/delta?since={sync_time}&client_id={registered_client}"
        )
        data = response.json()
        assert sample_tracker["id"] in data["deletedTrackers"]

    def test_requires_since_parameter(self, client, registered_client):
        """Should require since parameter."""
        response = client.get(f"/api/sync/delta?client_id={registered_client}")
        assert response.status_code == 422  # Validation error

    def test_requires_client_id_parameter(self, client):
        """Should require client_id parameter."""
        past = (datetime.utcnow() - timedelta(hours=1)).isoformat() + "Z"
        response = client.get(f"/api/sync/delta?since={past}")
        assert response.status_code == 422  # Validation error

    def test_empty_response_for_future_timestamp(self, client, seeded_database):
        """Future timestamp should return empty changes."""
        future = (datetime.utcnow() + timedelta(hours=1)).isoformat() + "Z"
        response = client.get(
            f"/api/sync/delta?since={future}&client_id={seeded_database['client_id']}"
        )
        data = response.json()

        # Should be empty since no changes after future time
        assert data["config"] == []
        assert data["days"] == {}
        assert data["deletedTrackers"] == []

    def test_only_returns_recent_entries(self, client, registered_client, sample_tracker):
        """Should only return entries from last 7 days."""
        # Create tracker and entries
        old_date = (datetime.now() - timedelta(days=10)).strftime("%Y-%m-%d")
        today = datetime.now().strftime("%Y-%m-%d")
        past = (datetime.utcnow() - timedelta(hours=1)).isoformat() + "Z"

        client.post("/api/sync/update", json={
            "clientId": registered_client,
            "config": [sample_tracker],
            "days": {
                old_date: {sample_tracker["id"]: {"value": 1, "_baseVersion": 0}},
                today: {sample_tracker["id"]: {"value": 2, "_baseVersion": 0}}
            }
        })

        response = client.get(
            f"/api/sync/delta?since={past}&client_id={registered_client}"
        )
        days = response.json()["days"]

        assert today in days
        assert old_date not in days

    def test_includes_version_metadata(self, client, seeded_database):
        """Returned items should include version metadata."""
        past = (datetime.utcnow() - timedelta(hours=1)).isoformat() + "Z"
        response = client.get(
            f"/api/sync/delta?since={past}&client_id={seeded_database['client_id']}"
        )
        data = response.json()

        if data["config"]:
            tracker = data["config"][0]
            assert "_version" in tracker
            assert "_lastModifiedBy" in tracker
            assert "_lastModifiedAt" in tracker
