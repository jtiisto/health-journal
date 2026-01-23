"""E2E tests for multi-client synchronization scenarios."""
import pytest
from datetime import datetime


@pytest.mark.e2e
class TestMultiClientSync:
    def test_two_clients_create_different_trackers(self, client):
        """Two clients should be able to create different trackers."""
        # Register two clients
        client.post("/api/sync/register?client_id=client-a")
        client.post("/api/sync/register?client_id=client-b")

        # Client A creates tracker
        tracker_a = {
            "id": "tracker-a",
            "name": "Client A Tracker",
            "category": "test",
            "type": "simple",
            "_baseVersion": 0
        }
        client.post("/api/sync/update", json={
            "clientId": "client-a",
            "config": [tracker_a],
            "days": {}
        })

        # Client B creates different tracker
        tracker_b = {
            "id": "tracker-b",
            "name": "Client B Tracker",
            "category": "test",
            "type": "simple",
            "_baseVersion": 0
        }
        client.post("/api/sync/update", json={
            "clientId": "client-b",
            "config": [tracker_b],
            "days": {}
        })

        # Both trackers should exist
        response = client.get("/api/sync/full")
        tracker_ids = [t["id"] for t in response.json()["config"]]
        assert "tracker-a" in tracker_ids
        assert "tracker-b" in tracker_ids

    def test_concurrent_updates_same_tracker_conflict(self, client):
        """Concurrent updates to same tracker should detect conflicts."""
        client.post("/api/sync/register?client_id=client-x")
        client.post("/api/sync/register?client_id=client-y")

        # Both clients know tracker at version 0
        tracker = {
            "id": "shared-tracker",
            "name": "Shared",
            "category": "test",
            "type": "simple",
            "_baseVersion": 0
        }

        # Client X creates tracker
        client.post("/api/sync/update", json={
            "clientId": "client-x",
            "config": [tracker],
            "days": {}
        })

        # Client X updates (version 2)
        updated_x = {**tracker, "name": "X Updated", "_baseVersion": 1}
        client.post("/api/sync/update", json={
            "clientId": "client-x",
            "config": [updated_x],
            "days": {}
        })

        # Client Y tries to update from stale base (should conflict)
        updated_y = {**tracker, "name": "Y Updated", "_baseVersion": 1}
        response = client.post("/api/sync/update", json={
            "clientId": "client-y",
            "config": [updated_y],
            "days": {}
        })

        data = response.json()
        assert data["success"] is False
        assert len(data["conflicts"]) == 1
        assert data["conflicts"][0]["serverVersion"] == 2
        assert data["conflicts"][0]["clientBaseVersion"] == 1

    def test_concurrent_entry_updates_conflict(self, client):
        """Concurrent entry updates should detect conflicts."""
        client.post("/api/sync/register?client_id=phone")
        client.post("/api/sync/register?client_id=tablet")

        # Create shared tracker
        tracker = {
            "id": "water",
            "name": "Water",
            "category": "health",
            "type": "quantifiable",
            "_baseVersion": 0
        }
        client.post("/api/sync/update", json={
            "clientId": "phone",
            "config": [tracker],
            "days": {}
        })

        today = datetime.now().strftime("%Y-%m-%d")

        # Phone logs 3 glasses
        client.post("/api/sync/update", json={
            "clientId": "phone",
            "config": [],
            "days": {today: {"water": {"value": 3, "_baseVersion": 0}}}
        })

        # Tablet logs 5 glasses (with old base version - conflict!)
        response = client.post("/api/sync/update", json={
            "clientId": "tablet",
            "config": [],
            "days": {today: {"water": {"value": 5, "_baseVersion": 0}}}
        })

        data = response.json()
        assert data["success"] is False
        assert data["conflicts"][0]["entityType"] == "entry"

    def test_sequential_updates_no_conflict(self, client):
        """Sequential updates with correct versions should not conflict."""
        client.post("/api/sync/register?client_id=device-1")
        client.post("/api/sync/register?client_id=device-2")

        tracker = {
            "id": "sequential-tracker",
            "name": "Original",
            "category": "test",
            "type": "simple",
            "_baseVersion": 0
        }

        # Device 1 creates tracker
        client.post("/api/sync/update", json={
            "clientId": "device-1",
            "config": [tracker],
            "days": {}
        })

        # Device 2 syncs and gets version 1
        full = client.get("/api/sync/full").json()
        tracker_v1 = next(t for t in full["config"] if t["id"] == "sequential-tracker")
        assert tracker_v1["_version"] == 1

        # Device 2 updates with correct base version
        response = client.post("/api/sync/update", json={
            "clientId": "device-2",
            "config": [{
                **tracker,
                "name": "Device 2 Update",
                "_baseVersion": 1
            }],
            "days": {}
        })

        assert response.json()["success"] is True
        assert response.json()["appliedConfig"][0]["_version"] == 2

    def test_three_clients_sync_scenario(self, client):
        """Complex scenario with three clients syncing."""
        # Register three clients
        for name in ["laptop", "phone", "tablet"]:
            client.post(f"/api/sync/register?client_id={name}")

        # Laptop creates tracker
        tracker = {
            "id": "exercise",
            "name": "Exercise",
            "category": "health",
            "type": "simple",
            "_baseVersion": 0
        }
        client.post("/api/sync/update", json={
            "clientId": "laptop",
            "config": [tracker],
            "days": {}
        })

        today = datetime.now().strftime("%Y-%m-%d")

        # Phone marks exercise as done
        client.post("/api/sync/update", json={
            "clientId": "phone",
            "config": [],
            "days": {today: {"exercise": {"completed": True, "_baseVersion": 0}}}
        })

        # Tablet syncs and sees the entry
        full = client.get("/api/sync/full").json()
        assert today in full["days"]
        assert full["days"][today]["exercise"]["completed"] is True

        # Tablet updates entry with correct version
        response = client.post("/api/sync/update", json={
            "clientId": "tablet",
            "config": [],
            "days": {today: {"exercise": {"completed": False, "_baseVersion": 1}}}
        })
        assert response.json()["success"] is True

        # All clients see updated value
        full = client.get("/api/sync/full").json()
        assert full["days"][today]["exercise"]["completed"] is False


@pytest.mark.e2e
class TestClientTracking:
    def test_last_modified_by_tracked(self, client, test_app):
        """Last modified by should track which client made changes."""
        import server

        client.post("/api/sync/register?client_id=client-alpha")
        client.post("/api/sync/register?client_id=client-beta")

        tracker = {
            "id": "tracked-tracker",
            "name": "Tracked",
            "category": "test",
            "type": "simple",
            "_baseVersion": 0
        }

        # Alpha creates tracker
        client.post("/api/sync/update", json={
            "clientId": "client-alpha",
            "config": [tracker],
            "days": {}
        })

        # Check last_modified_by
        with server.get_db() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT last_modified_by FROM trackers WHERE id = ?", ("tracked-tracker",))
            row = cursor.fetchone()
            assert row["last_modified_by"] == "client-alpha"

        # Beta updates tracker
        client.post("/api/sync/update", json={
            "clientId": "client-beta",
            "config": [{**tracker, "name": "Updated by Beta", "_baseVersion": 1}],
            "days": {}
        })

        # Check last_modified_by changed
        with server.get_db() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT last_modified_by FROM trackers WHERE id = ?", ("tracked-tracker",))
            row = cursor.fetchone()
            assert row["last_modified_by"] == "client-beta"
