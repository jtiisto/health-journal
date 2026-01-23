"""E2E tests for conflict detection and resolution workflows."""
import pytest
from datetime import datetime, timedelta


@pytest.mark.e2e
class TestConflictResolutionWorkflow:
    def test_full_conflict_resolution_flow(self, client):
        """Test complete conflict detection and resolution workflow."""
        # Setup
        client.post("/api/sync/register?client_id=device-1")
        client.post("/api/sync/register?client_id=device-2")

        tracker = {
            "id": "conflict-test",
            "name": "Original Name",
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

        # Device 1 updates (version 2)
        client.post("/api/sync/update", json={
            "clientId": "device-1",
            "config": [{**tracker, "name": "Device 1 Update", "_baseVersion": 1}],
            "days": {}
        })

        # Device 2 tries stale update - gets conflict
        response = client.post("/api/sync/update", json={
            "clientId": "device-2",
            "config": [{**tracker, "name": "Device 2 Update", "_baseVersion": 1}],
            "days": {}
        })

        data = response.json()
        assert not data["success"]
        conflict = data["conflicts"][0]
        assert conflict["entityType"] == "tracker"
        assert conflict["entityId"] == "conflict-test"
        assert conflict["serverVersion"] == 2
        assert conflict["clientBaseVersion"] == 1
        assert conflict["serverData"]["name"] == "Device 1 Update"

        # Resolve conflict in favor of device 2
        resolve_response = client.post(
            "/api/sync/resolve-conflict",
            params={
                "entity_type": "tracker",
                "entity_id": "conflict-test",
                "resolution": "client",
                "client_id": "device-2"
            },
            json={"name": "Device 2 Update", "category": "test", "type": "simple"}
        )
        assert resolve_response.status_code == 200

        # Verify resolution
        full = client.get("/api/sync/full")
        resolved_tracker = next(
            t for t in full.json()["config"]
            if t["id"] == "conflict-test"
        )
        assert resolved_tracker["name"] == "Device 2 Update"

    def test_entry_conflict_resolution_flow(self, client):
        """Test entry conflict detection and resolution."""
        client.post("/api/sync/register?client_id=phone")
        client.post("/api/sync/register?client_id=tablet")

        tracker = {
            "id": "water-tracker",
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

        # Phone logs value
        client.post("/api/sync/update", json={
            "clientId": "phone",
            "config": [],
            "days": {today: {"water-tracker": {"value": 5, "_baseVersion": 0}}}
        })

        # Phone updates again
        client.post("/api/sync/update", json={
            "clientId": "phone",
            "config": [],
            "days": {today: {"water-tracker": {"value": 6, "_baseVersion": 1}}}
        })

        # Tablet with stale version gets conflict
        response = client.post("/api/sync/update", json={
            "clientId": "tablet",
            "config": [],
            "days": {today: {"water-tracker": {"value": 8, "_baseVersion": 1}}}
        })

        assert response.json()["success"] is False
        conflict = response.json()["conflicts"][0]
        assert conflict["entityType"] == "entry"
        assert conflict["serverData"]["value"] == 6

        # Resolve with tablet's value
        entity_id = f"{today}|water-tracker"
        client.post(
            "/api/sync/resolve-conflict",
            params={
                "entity_type": "entry",
                "entity_id": entity_id,
                "resolution": "client",
                "client_id": "tablet"
            },
            json={"value": 8, "completed": False}
        )

        # Verify
        full = client.get("/api/sync/full").json()
        assert full["days"][today]["water-tracker"]["value"] == 8


@pytest.mark.e2e
class TestSevenDayWindow:
    def test_7_day_window_enforcement_full_sync(self, client, registered_client, sample_tracker):
        """Entries older than 7 days should not appear in full sync."""
        client.post("/api/sync/update", json={
            "clientId": registered_client,
            "config": [sample_tracker],
            "days": {}
        })

        old_date = (datetime.now() - timedelta(days=10)).strftime("%Y-%m-%d")
        recent_date = (datetime.now() - timedelta(days=3)).strftime("%Y-%m-%d")
        today = datetime.now().strftime("%Y-%m-%d")

        client.post("/api/sync/update", json={
            "clientId": registered_client,
            "config": [],
            "days": {
                old_date: {sample_tracker["id"]: {"value": 1, "_baseVersion": 0}},
                recent_date: {sample_tracker["id"]: {"value": 2, "_baseVersion": 0}},
                today: {sample_tracker["id"]: {"value": 3, "_baseVersion": 0}}
            }
        })

        full = client.get("/api/sync/full").json()

        assert today in full["days"]
        assert recent_date in full["days"]
        assert old_date not in full["days"]

    def test_7_day_window_enforcement_delta_sync(self, client, registered_client, sample_tracker):
        """Entries older than 7 days should not appear in delta sync."""
        client.post("/api/sync/update", json={
            "clientId": registered_client,
            "config": [sample_tracker],
            "days": {}
        })

        old_date = (datetime.now() - timedelta(days=10)).strftime("%Y-%m-%d")
        today = datetime.now().strftime("%Y-%m-%d")

        client.post("/api/sync/update", json={
            "clientId": registered_client,
            "config": [],
            "days": {
                old_date: {sample_tracker["id"]: {"value": 1, "_baseVersion": 0}},
                today: {sample_tracker["id"]: {"value": 2, "_baseVersion": 0}}
            }
        })

        past = (datetime.utcnow() - timedelta(hours=1)).isoformat() + "Z"
        delta = client.get(f"/api/sync/delta?since={past}&client_id={registered_client}").json()

        assert today in delta["days"]
        assert old_date not in delta["days"]


@pytest.mark.e2e
class TestVersioningIntegrity:
    def test_version_always_increments(self, client, registered_client, sample_tracker):
        """Version should always increment on updates."""
        client.post("/api/sync/update", json={
            "clientId": registered_client,
            "config": [sample_tracker],
            "days": {}
        })

        # Multiple updates
        for i in range(1, 5):
            response = client.post("/api/sync/update", json={
                "clientId": registered_client,
                "config": [{**sample_tracker, "name": f"Update {i}", "_baseVersion": i}],
                "days": {}
            })
            assert response.json()["success"] is True
            assert response.json()["appliedConfig"][0]["_version"] == i + 1

        # Final version should be 5
        full = client.get("/api/sync/full").json()
        tracker = next(t for t in full["config"] if t["id"] == sample_tracker["id"])
        assert tracker["_version"] == 5

    def test_conflict_preserves_server_version(self, client, registered_client, sample_tracker):
        """Conflicting update should not change server version."""
        client.post("/api/sync/update", json={
            "clientId": registered_client,
            "config": [sample_tracker],
            "days": {}
        })

        # Update to v2
        client.post("/api/sync/update", json={
            "clientId": registered_client,
            "config": [{**sample_tracker, "name": "V2", "_baseVersion": 1}],
            "days": {}
        })

        # Conflicting update (should fail)
        response = client.post("/api/sync/update", json={
            "clientId": registered_client,
            "config": [{**sample_tracker, "name": "Conflict", "_baseVersion": 1}],
            "days": {}
        })
        assert response.json()["success"] is False

        # Version should still be 2
        full = client.get("/api/sync/full").json()
        tracker = next(t for t in full["config"] if t["id"] == sample_tracker["id"])
        assert tracker["_version"] == 2
        assert tracker["name"] == "V2"  # Server version preserved


@pytest.mark.e2e
class TestDataIntegrity:
    def test_metadata_survives_updates(self, client, registered_client):
        """Metadata fields should survive multiple updates."""
        tracker = {
            "id": "metadata-tracker",
            "name": "Metadata Test",
            "category": "test",
            "type": "quantifiable",
            "unit": "items",
            "goal": 10,
            "minValue": 0,
            "maxValue": 100,
            "customField": "custom value",
            "_baseVersion": 0
        }

        client.post("/api/sync/update", json={
            "clientId": registered_client,
            "config": [tracker],
            "days": {}
        })

        # Update name but keep other metadata
        updated = {**tracker, "name": "Updated Name", "_baseVersion": 1}
        client.post("/api/sync/update", json={
            "clientId": registered_client,
            "config": [updated],
            "days": {}
        })

        # Verify all metadata preserved
        full = client.get("/api/sync/full").json()
        saved = next(t for t in full["config"] if t["id"] == "metadata-tracker")

        assert saved["name"] == "Updated Name"
        assert saved["unit"] == "items"
        assert saved["goal"] == 10
        assert saved["minValue"] == 0
        assert saved["maxValue"] == 100
        assert saved["customField"] == "custom value"

    def test_boolean_conversion_entries(self, client, registered_client, sample_simple_tracker):
        """Entry completed field should correctly convert to/from boolean."""
        client.post("/api/sync/update", json={
            "clientId": registered_client,
            "config": [sample_simple_tracker],
            "days": {}
        })

        today = datetime.now().strftime("%Y-%m-%d")

        # Test True
        client.post("/api/sync/update", json={
            "clientId": registered_client,
            "config": [],
            "days": {today: {sample_simple_tracker["id"]: {"completed": True, "_baseVersion": 0}}}
        })

        full = client.get("/api/sync/full").json()
        assert full["days"][today][sample_simple_tracker["id"]]["completed"] is True

        # Test False
        client.post("/api/sync/update", json={
            "clientId": registered_client,
            "config": [],
            "days": {today: {sample_simple_tracker["id"]: {"completed": False, "_baseVersion": 1}}}
        })

        full = client.get("/api/sync/full").json()
        assert full["days"][today][sample_simple_tracker["id"]]["completed"] is False
