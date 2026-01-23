"""
Shared fixtures for all tests.
"""
import os
import sys
import tempfile
from pathlib import Path
from datetime import datetime, timedelta

import pytest
from fastapi.testclient import TestClient

# Add src to path for imports
sys.path.insert(0, str(Path(__file__).parent.parent / "src"))


@pytest.fixture(scope="function")
def temp_db_path():
    """Create a temporary database file for each test."""
    with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as f:
        db_path = f.name
    yield Path(db_path)
    # Cleanup after test
    if os.path.exists(db_path):
        os.unlink(db_path)


@pytest.fixture(scope="function")
def test_app(temp_db_path, tmp_path, monkeypatch):
    """
    Create a test FastAPI app with isolated database.
    Uses monkeypatch to override DATABASE_PATH and PUBLIC_DIR.
    """
    # Create minimal public directory structure for static file tests
    public_dir = tmp_path / "public"
    public_dir.mkdir()
    (public_dir / "index.html").write_text(
        '<html><head><link rel="stylesheet" href="/styles.css">'
        '<script src="/js/app.js"></script></head><body>Test</body></html>'
    )
    (public_dir / "styles.css").write_text("body { margin: 0; }")
    js_dir = public_dir / "js"
    js_dir.mkdir()
    (js_dir / "app.js").write_text("console.log('test');")

    # Patch the module-level variables before importing
    import server
    monkeypatch.setattr(server, "DATABASE_PATH", temp_db_path)
    monkeypatch.setattr(server, "PUBLIC_DIR", public_dir)

    # Re-initialize database with new path
    server.init_database()

    yield server.app


@pytest.fixture(scope="function")
def client(test_app):
    """Create a test client for the FastAPI app."""
    with TestClient(test_app) as c:
        yield c


@pytest.fixture
def sample_tracker():
    """Sample tracker configuration for tests."""
    return {
        "id": "tracker-001",
        "name": "Water Intake",
        "category": "health",
        "type": "quantifiable",
        "unit": "glasses",
        "goal": 8,
        "_baseVersion": 0
    }


@pytest.fixture
def sample_simple_tracker():
    """Sample simple (boolean) tracker for tests."""
    return {
        "id": "tracker-simple",
        "name": "Exercise",
        "category": "health",
        "type": "simple",
        "_baseVersion": 0
    }


@pytest.fixture
def sample_entry(sample_tracker):
    """Sample entry data for tests."""
    today = datetime.now().strftime("%Y-%m-%d")
    return {
        "date": today,
        "tracker_id": sample_tracker["id"],
        "value": 5,
        "completed": False,
        "_baseVersion": 0
    }


@pytest.fixture
def registered_client(client):
    """A client that has been registered with the server."""
    client_id = "test-client-001"
    response = client.post(f"/api/sync/register?client_id={client_id}&client_name=TestClient")
    assert response.status_code == 200
    return client_id


@pytest.fixture
def seeded_database(client, registered_client, sample_tracker):
    """Database seeded with sample data for testing."""
    # Create a tracker
    payload = {
        "clientId": registered_client,
        "config": [sample_tracker],
        "days": {}
    }
    response = client.post("/api/sync/update", json=payload)
    assert response.status_code == 200

    # Create entries for the last 3 days
    today = datetime.now()
    days = {}
    for i in range(3):
        date_str = (today - timedelta(days=i)).strftime("%Y-%m-%d")
        days[date_str] = {
            sample_tracker["id"]: {
                "value": 5 + i,
                "completed": i == 0,
                "_baseVersion": 0
            }
        }

    payload2 = {
        "clientId": registered_client,
        "config": [],
        "days": days
    }
    response = client.post("/api/sync/update", json=payload2)
    assert response.status_code == 200

    return {
        "client_id": registered_client,
        "tracker": sample_tracker,
        "dates": list(days.keys())
    }
