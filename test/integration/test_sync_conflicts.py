"""Integration tests for conflict resolution endpoints."""
import pytest
from datetime import datetime


@pytest.mark.integration
class TestResolveConflict:
    def test_resolve_tracker_conflict_with_client(self, client, registered_client, sample_tracker):
        """Should apply client data when resolving with 'client' resolution."""
        # Create tracker
        client.post("/api/sync/update", json={
            "clientId": registered_client,
            "config": [sample_tracker],
            "days": {}
        })

        # Update to version 2
        client.post("/api/sync/update", json={
            "clientId": registered_client,
            "config": [{**sample_tracker, "name": "Server Version", "_baseVersion": 1}],
            "days": {}
        })

        # Resolve with client data
        client_data = {
            "id": sample_tracker["id"],
            "name": "Client Wins",
            "category": sample_tracker["category"],
            "type": sample_tracker["type"]
        }
        response = client.post(
            "/api/sync/resolve-conflict",
            params={
                "entity_type": "tracker",
                "entity_id": sample_tracker["id"],
                "resolution": "client",
                "client_id": registered_client
            },
            json=client_data
        )
        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "ok"
        assert data["resolution"] == "client"
        assert data["entityId"] == sample_tracker["id"]

        # Verify client data was applied
        full_response = client.get("/api/sync/full")
        tracker = next(
            t for t in full_response.json()["config"]
            if t["id"] == sample_tracker["id"]
        )
        assert tracker["name"] == "Client Wins"

    def test_resolve_tracker_conflict_with_server(self, client, registered_client, sample_tracker):
        """Should keep server data when resolving with 'server' resolution."""
        # Create and update tracker
        client.post("/api/sync/update", json={
            "clientId": registered_client,
            "config": [sample_tracker],
            "days": {}
        })
        client.post("/api/sync/update", json={
            "clientId": registered_client,
            "config": [{**sample_tracker, "name": "Server Version", "_baseVersion": 1}],
            "days": {}
        })

        # Resolve keeping server
        response = client.post(
            "/api/sync/resolve-conflict",
            params={
                "entity_type": "tracker",
                "entity_id": sample_tracker["id"],
                "resolution": "server",
                "client_id": registered_client
            }
        )
        assert response.status_code == 200
        assert response.json()["resolution"] == "server"

        # Server data should remain
        full_response = client.get("/api/sync/full")
        tracker = next(
            t for t in full_response.json()["config"]
            if t["id"] == sample_tracker["id"]
        )
        assert tracker["name"] == "Server Version"

    def test_resolve_entry_conflict_with_client(self, client, registered_client, sample_tracker):
        """Should resolve entry conflicts with client data."""
        client.post("/api/sync/update", json={
            "clientId": registered_client,
            "config": [sample_tracker],
            "days": {}
        })

        today = datetime.now().strftime("%Y-%m-%d")

        # Create and update entry
        client.post("/api/sync/update", json={
            "clientId": registered_client,
            "config": [],
            "days": {today: {sample_tracker["id"]: {"value": 5, "_baseVersion": 0}}}
        })

        # Resolve with client data
        entity_id = f"{today}|{sample_tracker['id']}"
        client_data = {"value": 10, "completed": True}
        response = client.post(
            "/api/sync/resolve-conflict",
            params={
                "entity_type": "entry",
                "entity_id": entity_id,
                "resolution": "client",
                "client_id": registered_client
            },
            json=client_data
        )
        assert response.status_code == 200
        assert response.json()["status"] == "ok"

        # Verify entry was updated
        full_response = client.get("/api/sync/full")
        entry = full_response.json()["days"][today][sample_tracker["id"]]
        assert entry["value"] == 10
        assert entry["completed"] is True

    def test_resolution_increments_version(self, client, registered_client, sample_tracker, test_app):
        """Client resolution should increment version."""
        import server

        client.post("/api/sync/update", json={
            "clientId": registered_client,
            "config": [sample_tracker],
            "days": {}
        })

        # Get initial version
        with server.get_db() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT version FROM trackers WHERE id = ?", (sample_tracker["id"],))
            initial_version = cursor.fetchone()["version"]

        # Resolve conflict
        client.post(
            "/api/sync/resolve-conflict",
            params={
                "entity_type": "tracker",
                "entity_id": sample_tracker["id"],
                "resolution": "client",
                "client_id": registered_client
            },
            json={"name": "Resolved", "category": "test", "type": "simple"}
        )

        # Check version incremented
        with server.get_db() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT version FROM trackers WHERE id = ?", (sample_tracker["id"],))
            new_version = cursor.fetchone()["version"]

        assert new_version == initial_version + 1

    def test_resolution_logged_in_sync_conflicts(self, client, registered_client, sample_tracker, test_app):
        """Resolution should be logged in sync_conflicts table."""
        import server

        client.post("/api/sync/update", json={
            "clientId": registered_client,
            "config": [sample_tracker],
            "days": {}
        })

        client.post(
            "/api/sync/resolve-conflict",
            params={
                "entity_type": "tracker",
                "entity_id": sample_tracker["id"],
                "resolution": "client",
                "client_id": registered_client
            },
            json={"name": "Resolved", "category": "test", "type": "simple"}
        )

        # Check conflict was logged
        with server.get_db() as conn:
            cursor = conn.cursor()
            cursor.execute(
                "SELECT * FROM sync_conflicts WHERE entity_id = ?",
                (sample_tracker["id"],)
            )
            row = cursor.fetchone()

        assert row is not None
        assert row["entity_type"] == "tracker"
        assert row["resolution"] == "client"
        assert row["resolved_at"] is not None


@pytest.mark.integration
class TestGetUnresolvedConflicts:
    def test_returns_empty_for_new_client(self, client, registered_client):
        """Should return empty list for client with no conflicts."""
        response = client.get(f"/api/sync/conflicts?client_id={registered_client}")
        assert response.status_code == 200
        data = response.json()
        assert data["conflicts"] == []

    def test_requires_client_id(self, client):
        """Should require client_id parameter."""
        response = client.get("/api/sync/conflicts")
        assert response.status_code == 422

    def test_excludes_resolved_conflicts(self, client, registered_client, sample_tracker):
        """Should not include conflicts that have been resolved."""
        # Create tracker and resolve a "conflict"
        client.post("/api/sync/update", json={
            "clientId": registered_client,
            "config": [sample_tracker],
            "days": {}
        })

        client.post(
            "/api/sync/resolve-conflict",
            params={
                "entity_type": "tracker",
                "entity_id": sample_tracker["id"],
                "resolution": "client",
                "client_id": registered_client
            },
            json={"name": "Resolved", "category": "test", "type": "simple"}
        )

        # Get conflicts - should be empty since it's resolved
        response = client.get(f"/api/sync/conflicts?client_id={registered_client}")
        # Note: The resolved conflict has resolved_at set, so it won't appear
        data = response.json()
        unresolved = [c for c in data["conflicts"] if c.get("entityId") == sample_tracker["id"]]
        assert len(unresolved) == 0
