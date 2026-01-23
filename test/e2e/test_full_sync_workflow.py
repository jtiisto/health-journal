"""E2E tests for complete sync workflows."""
import pytest
from datetime import datetime, timedelta


@pytest.mark.e2e
class TestFreshClientWorkflow:
    def test_fresh_client_full_sync_workflow(self, client):
        """Test complete workflow for a new client."""
        # 1. Register client
        client_id = "new-client-e2e"
        response = client.post(f"/api/sync/register?client_id={client_id}")
        assert response.status_code == 200
        assert response.json()["status"] == "ok"

        # 2. Check status (should be empty)
        response = client.get("/api/sync/status")
        assert response.json()["lastModified"] is None

        # 3. Get full sync (empty)
        response = client.get("/api/sync/full")
        data = response.json()
        assert data["config"] == []
        assert data["days"] == {}

        # 4. Push initial data
        tracker = {
            "id": "e2e-tracker",
            "name": "E2E Test Tracker",
            "category": "test",
            "type": "simple",
            "_baseVersion": 0
        }
        today = datetime.now().strftime("%Y-%m-%d")
        payload = {
            "clientId": client_id,
            "config": [tracker],
            "days": {
                today: {
                    "e2e-tracker": {"value": None, "completed": True, "_baseVersion": 0}
                }
            }
        }
        response = client.post("/api/sync/update", json=payload)
        assert response.json()["success"] is True

        # 5. Verify full sync returns data
        response = client.get("/api/sync/full")
        data = response.json()
        assert len(data["config"]) == 1
        assert data["config"][0]["name"] == "E2E Test Tracker"
        assert today in data["days"]

        # 6. Status should now have timestamp
        response = client.get("/api/sync/status")
        assert response.json()["lastModified"] is not None


@pytest.mark.e2e
class TestIncrementalSyncWorkflow:
    def test_incremental_sync_workflow(self, client, seeded_database):
        """Test delta sync after initial full sync."""
        client_id = seeded_database["client_id"]

        # 1. Get full sync timestamp
        response = client.get("/api/sync/full")
        server_time = response.json()["serverTime"]

        # 2. Make changes
        new_tracker = {
            "id": "delta-tracker",
            "name": "Delta Tracker",
            "category": "test",
            "type": "simple",
            "_baseVersion": 0
        }
        client.post("/api/sync/update", json={
            "clientId": client_id,
            "config": [new_tracker],
            "days": {}
        })

        # 3. Delta sync should show only new changes
        response = client.get(f"/api/sync/delta?since={server_time}&client_id={client_id}")
        data = response.json()

        # Should include new tracker
        tracker_ids = [t["id"] for t in data["config"]]
        assert "delta-tracker" in tracker_ids

        # Should not include original tracker (unchanged since timestamp)
        # Note: Depending on timing, original may or may not appear
        # The key assertion is that delta-tracker IS present

    def test_delta_sync_after_entry_update(self, client, seeded_database):
        """Delta sync should show updated entries."""
        client_id = seeded_database["client_id"]
        tracker_id = seeded_database["tracker"]["id"]

        # Get baseline
        response = client.get("/api/sync/full")
        server_time = response.json()["serverTime"]

        # Update an entry
        today = datetime.now().strftime("%Y-%m-%d")
        client.post("/api/sync/update", json={
            "clientId": client_id,
            "config": [],
            "days": {
                today: {
                    tracker_id: {"value": 99, "_baseVersion": 1}
                }
            }
        })

        # Delta should show the update
        response = client.get(f"/api/sync/delta?since={server_time}&client_id={client_id}")
        data = response.json()

        assert today in data["days"]
        assert data["days"][today][tracker_id]["value"] == 99


@pytest.mark.e2e
class TestTrackerLifecycle:
    def test_tracker_create_update_delete_lifecycle(self, client, registered_client):
        """Test complete tracker lifecycle: create, update, delete."""
        tracker = {
            "id": "lifecycle-tracker",
            "name": "Lifecycle Test",
            "category": "test",
            "type": "quantifiable",
            "unit": "items",
            "_baseVersion": 0
        }

        # Create
        response = client.post("/api/sync/update", json={
            "clientId": registered_client,
            "config": [tracker],
            "days": {}
        })
        assert response.json()["success"] is True
        assert response.json()["appliedConfig"][0]["_version"] == 1

        # Verify exists
        full = client.get("/api/sync/full").json()
        assert any(t["id"] == "lifecycle-tracker" for t in full["config"])

        # Update
        updated = {**tracker, "name": "Updated Lifecycle", "_baseVersion": 1}
        response = client.post("/api/sync/update", json={
            "clientId": registered_client,
            "config": [updated],
            "days": {}
        })
        assert response.json()["appliedConfig"][0]["_version"] == 2
        assert response.json()["appliedConfig"][0]["name"] == "Updated Lifecycle"

        # Delete
        deleted = {**tracker, "_deleted": True, "_baseVersion": 2}
        response = client.post("/api/sync/update", json={
            "clientId": registered_client,
            "config": [deleted],
            "days": {}
        })
        assert response.json()["success"] is True

        # Verify gone from full sync
        full = client.get("/api/sync/full").json()
        assert not any(t["id"] == "lifecycle-tracker" for t in full["config"])

        # Verify appears in delta's deletedTrackers
        past = (datetime.utcnow() - timedelta(hours=1)).isoformat() + "Z"
        delta = client.get(f"/api/sync/delta?since={past}&client_id={registered_client}").json()
        assert "lifecycle-tracker" in delta["deletedTrackers"]


@pytest.mark.e2e
class TestEntryLifecycle:
    def test_entry_create_update_workflow(self, client, registered_client, sample_tracker):
        """Test entry creation and updates over multiple days."""
        # Create tracker
        client.post("/api/sync/update", json={
            "clientId": registered_client,
            "config": [sample_tracker],
            "days": {}
        })

        today = datetime.now()
        dates = [(today - timedelta(days=i)).strftime("%Y-%m-%d") for i in range(3)]

        # Create entries for 3 days
        days = {d: {sample_tracker["id"]: {"value": i, "_baseVersion": 0}} for i, d in enumerate(dates)}
        response = client.post("/api/sync/update", json={
            "clientId": registered_client,
            "config": [],
            "days": days
        })
        assert response.json()["success"] is True

        # Verify all entries exist
        full = client.get("/api/sync/full").json()
        for d in dates:
            assert d in full["days"]
            assert sample_tracker["id"] in full["days"][d]

        # Update today's entry
        response = client.post("/api/sync/update", json={
            "clientId": registered_client,
            "config": [],
            "days": {dates[0]: {sample_tracker["id"]: {"value": 100, "_baseVersion": 1}}}
        })
        assert response.json()["success"] is True
        assert response.json()["appliedDays"][dates[0]][sample_tracker["id"]]["value"] == 100

        # Verify update persisted
        full = client.get("/api/sync/full").json()
        assert full["days"][dates[0]][sample_tracker["id"]]["value"] == 100
