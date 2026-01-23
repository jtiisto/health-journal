"""Integration tests for POST /api/sync/update endpoint."""
import pytest
from datetime import datetime


@pytest.mark.integration
class TestSyncUpdateTrackers:
    def test_create_new_tracker(self, client, registered_client, sample_tracker):
        """Should successfully create a new tracker."""
        payload = {
            "clientId": registered_client,
            "config": [sample_tracker],
            "days": {}
        }
        response = client.post("/api/sync/update", json=payload)
        assert response.status_code == 200
        data = response.json()
        assert data["success"] is True
        assert len(data["appliedConfig"]) == 1
        assert data["appliedConfig"][0]["_version"] == 1

    def test_update_existing_tracker(self, client, registered_client, sample_tracker):
        """Should update tracker with incremented version."""
        # Create tracker
        client.post("/api/sync/update", json={
            "clientId": registered_client,
            "config": [sample_tracker],
            "days": {}
        })

        # Update tracker
        updated = {**sample_tracker, "name": "Updated Name", "_baseVersion": 1}
        response = client.post("/api/sync/update", json={
            "clientId": registered_client,
            "config": [updated],
            "days": {}
        })
        data = response.json()
        assert data["success"] is True
        assert data["appliedConfig"][0]["_version"] == 2
        assert data["appliedConfig"][0]["name"] == "Updated Name"

    def test_soft_delete_tracker(self, client, registered_client, sample_tracker):
        """Should soft-delete tracker when _deleted flag is set."""
        # Create tracker
        client.post("/api/sync/update", json={
            "clientId": registered_client,
            "config": [sample_tracker],
            "days": {}
        })

        # Delete tracker
        deleted = {**sample_tracker, "_deleted": True, "_baseVersion": 1}
        response = client.post("/api/sync/update", json={
            "clientId": registered_client,
            "config": [deleted],
            "days": {}
        })
        assert response.status_code == 200

        # Verify tracker is excluded from full sync
        full_response = client.get("/api/sync/full")
        trackers = full_response.json()["config"]
        assert not any(t["id"] == sample_tracker["id"] for t in trackers)

    def test_conflict_detection_tracker(self, client, registered_client, sample_tracker):
        """Should detect conflict when server version > client base version."""
        # Create tracker (version 1)
        client.post("/api/sync/update", json={
            "clientId": registered_client,
            "config": [sample_tracker],
            "days": {}
        })

        # Update tracker (version 2)
        updated = {**sample_tracker, "name": "Updated", "_baseVersion": 1}
        client.post("/api/sync/update", json={
            "clientId": registered_client,
            "config": [updated],
            "days": {}
        })

        # Try to update with stale base version (should conflict)
        stale = {**sample_tracker, "name": "Stale Update", "_baseVersion": 1}
        response = client.post("/api/sync/update", json={
            "clientId": registered_client,
            "config": [stale],
            "days": {}
        })
        data = response.json()

        assert data["success"] is False
        assert len(data["conflicts"]) == 1
        assert data["conflicts"][0]["entityType"] == "tracker"
        assert data["conflicts"][0]["serverVersion"] == 2
        assert data["conflicts"][0]["clientBaseVersion"] == 1

    def test_metadata_json_preserved(self, client, registered_client):
        """Extra tracker fields should be preserved in meta_json."""
        tracker = {
            "id": "tracker-meta",
            "name": "Quantifiable Tracker",
            "category": "health",
            "type": "quantifiable",
            "unit": "glasses",
            "goal": 8,
            "minValue": 0,
            "maxValue": 20,
            "_baseVersion": 0
        }
        client.post("/api/sync/update", json={
            "clientId": registered_client,
            "config": [tracker],
            "days": {}
        })

        # Retrieve and verify
        response = client.get("/api/sync/full")
        config = response.json()["config"]
        saved_tracker = next(t for t in config if t["id"] == "tracker-meta")

        assert saved_tracker["unit"] == "glasses"
        assert saved_tracker["goal"] == 8
        assert saved_tracker["minValue"] == 0
        assert saved_tracker["maxValue"] == 20

    def test_multiple_trackers_in_single_update(self, client, registered_client):
        """Should handle multiple trackers in single update."""
        trackers = [
            {"id": f"tracker-{i}", "name": f"Tracker {i}", "category": "test", "type": "simple", "_baseVersion": 0}
            for i in range(3)
        ]
        response = client.post("/api/sync/update", json={
            "clientId": registered_client,
            "config": trackers,
            "days": {}
        })
        data = response.json()

        assert data["success"] is True
        assert len(data["appliedConfig"]) == 3


@pytest.mark.integration
class TestSyncUpdateEntries:
    def test_create_entry(self, client, registered_client, sample_tracker):
        """Should successfully create entry for a tracker."""
        # First create tracker
        client.post("/api/sync/update", json={
            "clientId": registered_client,
            "config": [sample_tracker],
            "days": {}
        })

        # Create entry
        today = datetime.now().strftime("%Y-%m-%d")
        response = client.post("/api/sync/update", json={
            "clientId": registered_client,
            "config": [],
            "days": {
                today: {
                    sample_tracker["id"]: {
                        "value": 5,
                        "completed": False,
                        "_baseVersion": 0
                    }
                }
            }
        })
        data = response.json()
        assert data["success"] is True
        assert today in data["appliedDays"]
        assert data["appliedDays"][today][sample_tracker["id"]]["value"] == 5

    def test_update_entry(self, client, registered_client, sample_tracker):
        """Should update entry with incremented version."""
        client.post("/api/sync/update", json={
            "clientId": registered_client,
            "config": [sample_tracker],
            "days": {}
        })

        today = datetime.now().strftime("%Y-%m-%d")

        # Create entry
        client.post("/api/sync/update", json={
            "clientId": registered_client,
            "config": [],
            "days": {today: {sample_tracker["id"]: {"value": 3, "_baseVersion": 0}}}
        })

        # Update entry
        response = client.post("/api/sync/update", json={
            "clientId": registered_client,
            "config": [],
            "days": {today: {sample_tracker["id"]: {"value": 5, "_baseVersion": 1}}}
        })
        data = response.json()

        assert data["success"] is True
        assert data["appliedDays"][today][sample_tracker["id"]]["_version"] == 2
        assert data["appliedDays"][today][sample_tracker["id"]]["value"] == 5

    def test_conflict_detection_entry(self, client, registered_client, sample_tracker):
        """Should detect conflict for entry updates."""
        client.post("/api/sync/update", json={
            "clientId": registered_client,
            "config": [sample_tracker],
            "days": {}
        })

        today = datetime.now().strftime("%Y-%m-%d")

        # Create entry (version 1)
        client.post("/api/sync/update", json={
            "clientId": registered_client,
            "config": [],
            "days": {today: {sample_tracker["id"]: {"value": 5, "_baseVersion": 0}}}
        })

        # Update entry (version 2)
        client.post("/api/sync/update", json={
            "clientId": registered_client,
            "config": [],
            "days": {today: {sample_tracker["id"]: {"value": 6, "_baseVersion": 1}}}
        })

        # Try stale update (should conflict)
        response = client.post("/api/sync/update", json={
            "clientId": registered_client,
            "config": [],
            "days": {today: {sample_tracker["id"]: {"value": 7, "_baseVersion": 1}}}
        })
        data = response.json()

        assert data["success"] is False
        assert len(data["conflicts"]) == 1
        assert data["conflicts"][0]["entityType"] == "entry"
        assert f"{today}|{sample_tracker['id']}" == data["conflicts"][0]["entityId"]

    def test_entry_with_null_value(self, client, registered_client, sample_simple_tracker):
        """Should handle entry with null value (simple tracker)."""
        client.post("/api/sync/update", json={
            "clientId": registered_client,
            "config": [sample_simple_tracker],
            "days": {}
        })

        today = datetime.now().strftime("%Y-%m-%d")
        response = client.post("/api/sync/update", json={
            "clientId": registered_client,
            "config": [],
            "days": {today: {sample_simple_tracker["id"]: {"value": None, "completed": True, "_baseVersion": 0}}}
        })
        data = response.json()

        assert data["success"] is True
        entry = data["appliedDays"][today][sample_simple_tracker["id"]]
        assert entry["completed"] is True

    def test_multiple_entries_multiple_dates(self, client, registered_client, sample_tracker):
        """Should handle multiple entries across multiple dates."""
        client.post("/api/sync/update", json={
            "clientId": registered_client,
            "config": [sample_tracker],
            "days": {}
        })

        from datetime import timedelta
        today = datetime.now()
        days = {}
        for i in range(3):
            date_str = (today - timedelta(days=i)).strftime("%Y-%m-%d")
            days[date_str] = {
                sample_tracker["id"]: {"value": 5 + i, "_baseVersion": 0}
            }

        response = client.post("/api/sync/update", json={
            "clientId": registered_client,
            "config": [],
            "days": days
        })
        data = response.json()

        assert data["success"] is True
        assert len(data["appliedDays"]) == 3


@pytest.mark.integration
class TestSyncUpdateResponse:
    def test_success_true_when_no_conflicts(self, client, registered_client, sample_tracker):
        """success should be True when there are no conflicts."""
        response = client.post("/api/sync/update", json={
            "clientId": registered_client,
            "config": [sample_tracker],
            "days": {}
        })
        data = response.json()

        assert data["success"] is True
        assert data["conflicts"] == []

    def test_success_false_with_conflicts(self, client, registered_client, sample_tracker):
        """success should be False when there are conflicts."""
        # Create and update tracker to force conflict
        client.post("/api/sync/update", json={
            "clientId": registered_client,
            "config": [sample_tracker],
            "days": {}
        })
        client.post("/api/sync/update", json={
            "clientId": registered_client,
            "config": [{**sample_tracker, "name": "V2", "_baseVersion": 1}],
            "days": {}
        })

        # Stale update
        response = client.post("/api/sync/update", json={
            "clientId": registered_client,
            "config": [{**sample_tracker, "name": "Stale", "_baseVersion": 1}],
            "days": {}
        })
        data = response.json()

        assert data["success"] is False
        assert len(data["conflicts"]) > 0

    def test_last_modified_only_on_success(self, client, registered_client, sample_tracker):
        """lastModified should only be set on successful sync."""
        # Successful sync
        response = client.post("/api/sync/update", json={
            "clientId": registered_client,
            "config": [sample_tracker],
            "days": {}
        })
        assert response.json()["lastModified"] is not None

        # Force conflict
        client.post("/api/sync/update", json={
            "clientId": registered_client,
            "config": [{**sample_tracker, "name": "V2", "_baseVersion": 1}],
            "days": {}
        })
        response = client.post("/api/sync/update", json={
            "clientId": registered_client,
            "config": [{**sample_tracker, "name": "Stale", "_baseVersion": 1}],
            "days": {}
        })
        assert response.json()["lastModified"] is None

    def test_partial_success(self, client, registered_client):
        """Should handle mixed success/conflict scenarios."""
        # Create two trackers
        tracker1 = {"id": "t1", "name": "Tracker 1", "category": "test", "type": "simple", "_baseVersion": 0}
        tracker2 = {"id": "t2", "name": "Tracker 2", "category": "test", "type": "simple", "_baseVersion": 0}

        client.post("/api/sync/update", json={
            "clientId": registered_client,
            "config": [tracker1, tracker2],
            "days": {}
        })

        # Update only tracker1 to version 2
        client.post("/api/sync/update", json={
            "clientId": registered_client,
            "config": [{**tracker1, "name": "T1 V2", "_baseVersion": 1}],
            "days": {}
        })

        # Try to update both: tracker1 with stale version, tracker2 with correct version
        response = client.post("/api/sync/update", json={
            "clientId": registered_client,
            "config": [
                {**tracker1, "name": "T1 Stale", "_baseVersion": 1},  # Conflict
                {**tracker2, "name": "T2 Updated", "_baseVersion": 1}  # Success
            ],
            "days": {}
        })
        data = response.json()

        assert data["success"] is False
        assert len(data["conflicts"]) == 1
        assert data["conflicts"][0]["entityId"] == "t1"
        # tracker2 should still be applied
        assert any(t["id"] == "t2" for t in data["appliedConfig"])
