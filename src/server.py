"""
Personal Journal Server - FastAPI backend with SQLite
Enhanced with per-record versioning and multi-client sync support
"""
import json
import sqlite3
import uuid
from datetime import datetime, timedelta
from pathlib import Path
from contextlib import contextmanager, asynccontextmanager
from typing import Any, Optional

from fastapi import FastAPI, HTTPException
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse, HTMLResponse
from pydantic import BaseModel, ConfigDict


# Configuration
PROJECT_ROOT = Path(__file__).parent.parent
DATABASE_PATH = PROJECT_ROOT / "journal.db"
PUBLIC_DIR = PROJECT_ROOT / "public"

# Cache busting: unique version generated on each server start
SERVER_VERSION = uuid.uuid4().hex[:8]

@asynccontextmanager
async def lifespan(app):
    # Startup
    init_database()
    yield
    # Shutdown (nothing needed)


app = FastAPI(title="Personal Journal Server", lifespan=lifespan)


# Database helpers
@contextmanager
def get_db():
    """Context manager for database connections."""
    conn = sqlite3.connect(DATABASE_PATH)
    conn.row_factory = sqlite3.Row
    try:
        yield conn
    finally:
        conn.close()


def init_database():
    """Initialize the database with required tables including versioning."""
    with get_db() as conn:
        cursor = conn.cursor()

        # clients table - track connected clients
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS clients (
                id TEXT PRIMARY KEY,
                name TEXT,
                last_seen_at TEXT
            )
        """)

        # meta_sync table
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS meta_sync (
                key TEXT PRIMARY KEY,
                value TEXT
            )
        """)

        # trackers table with versioning
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS trackers (
                id TEXT PRIMARY KEY,
                name TEXT,
                category TEXT,
                type TEXT,
                meta_json TEXT,
                version INTEGER DEFAULT 1,
                last_modified_by TEXT,
                last_modified_at TEXT,
                deleted INTEGER DEFAULT 0
            )
        """)
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_trackers_name ON trackers(name)")

        # entries table with versioning
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS entries (
                date TEXT,
                tracker_id TEXT,
                value REAL,
                completed INTEGER,
                version INTEGER DEFAULT 1,
                last_modified_by TEXT,
                last_modified_at TEXT,
                PRIMARY KEY (date, tracker_id),
                FOREIGN KEY (tracker_id) REFERENCES trackers(id)
            )
        """)
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_entries_date ON entries(date)")

        # sync_conflicts table - log conflicts for user review
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS sync_conflicts (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                entity_type TEXT,
                entity_id TEXT,
                client_id TEXT,
                client_data TEXT,
                server_data TEXT,
                resolution TEXT,
                resolved_at TEXT,
                created_at TEXT
            )
        """)
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_conflicts_resolved ON sync_conflicts(resolved_at)")

        # Add versioning columns to existing tables if missing (migration)
        try:
            cursor.execute("ALTER TABLE trackers ADD COLUMN version INTEGER DEFAULT 1")
        except sqlite3.OperationalError:
            pass
        try:
            cursor.execute("ALTER TABLE trackers ADD COLUMN last_modified_by TEXT")
        except sqlite3.OperationalError:
            pass
        try:
            cursor.execute("ALTER TABLE trackers ADD COLUMN last_modified_at TEXT")
        except sqlite3.OperationalError:
            pass
        try:
            cursor.execute("ALTER TABLE trackers ADD COLUMN deleted INTEGER DEFAULT 0")
        except sqlite3.OperationalError:
            pass
        try:
            cursor.execute("ALTER TABLE entries ADD COLUMN version INTEGER DEFAULT 1")
        except sqlite3.OperationalError:
            pass
        try:
            cursor.execute("ALTER TABLE entries ADD COLUMN last_modified_by TEXT")
        except sqlite3.OperationalError:
            pass
        try:
            cursor.execute("ALTER TABLE entries ADD COLUMN last_modified_at TEXT")
        except sqlite3.OperationalError:
            pass

        # Create indexes on new columns (after migrations ensure columns exist)
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_trackers_modified ON trackers(last_modified_at)")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_entries_modified ON entries(last_modified_at)")

        conn.commit()


def get_utc_now() -> str:
    """Return current UTC time as ISO-8601 string."""
    return datetime.utcnow().isoformat() + "Z"


# Pydantic models
class TrackerEntry(BaseModel):
    value: Optional[float] = None
    completed: Optional[bool] = None
    _version: Optional[int] = None
    _baseVersion: Optional[int] = None


class TrackerConfig(BaseModel):
    model_config = ConfigDict(extra="allow")

    id: str
    name: str
    category: Optional[str] = ""
    type: Optional[str] = "simple"
    _version: Optional[int] = None
    _baseVersion: Optional[int] = None
    _deleted: Optional[bool] = False


class SyncPayload(BaseModel):
    clientId: str
    config: list[dict[str, Any]] = []
    days: dict[str, dict[str, dict[str, Any]]] = {}
    lastSyncTime: Optional[str] = None


class StatusResponse(BaseModel):
    lastModified: Optional[str] = None


class FullSyncResponse(BaseModel):
    config: list[dict[str, Any]]
    days: dict[str, dict[str, dict[str, Any]]]
    serverTime: str


class ConflictInfo(BaseModel):
    entityType: str
    entityId: str
    serverVersion: int
    clientBaseVersion: int
    serverData: dict[str, Any]


class SyncResponse(BaseModel):
    success: bool
    conflicts: list[ConflictInfo] = []
    appliedConfig: list[dict[str, Any]] = []
    appliedDays: dict[str, dict[str, dict[str, Any]]] = {}
    lastModified: Optional[str] = None
    overwrittenData: list[dict[str, Any]] = []


class DeltaSyncResponse(BaseModel):
    config: list[dict[str, Any]]
    days: dict[str, dict[str, dict[str, Any]]]
    deletedTrackers: list[str]
    serverTime: str


# API Endpoints
@app.get("/api/sync/status", response_model=StatusResponse)
def sync_status():
    """Get the last server sync time."""
    with get_db() as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT value FROM meta_sync WHERE key = 'last_server_sync_time'")
        row = cursor.fetchone()

        if row:
            return StatusResponse(lastModified=row["value"])
        return StatusResponse(lastModified=None)


@app.post("/api/sync/register")
def register_client(client_id: str, client_name: Optional[str] = None):
    """Register or update a client."""
    with get_db() as conn:
        cursor = conn.cursor()
        now = get_utc_now()
        cursor.execute("""
            INSERT OR REPLACE INTO clients (id, name, last_seen_at)
            VALUES (?, ?, ?)
        """, (client_id, client_name or f"Client-{client_id[:8]}", now))
        conn.commit()
        return {"status": "ok", "clientId": client_id}


@app.get("/api/sync/full", response_model=FullSyncResponse)
def sync_full():
    """Get full data dump for client synchronization."""
    with get_db() as conn:
        cursor = conn.cursor()

        # Fetch all non-deleted trackers with version info
        cursor.execute("SELECT * FROM trackers WHERE deleted = 0 OR deleted IS NULL")
        tracker_rows = cursor.fetchall()

        config = []
        for row in tracker_rows:
            tracker = {
                "id": row["id"],
                "name": row["name"],
                "category": row["category"],
                "type": row["type"],
                "_version": row["version"] or 1,
                "_lastModifiedBy": row["last_modified_by"],
                "_lastModifiedAt": row["last_modified_at"]
            }
            # Merge meta_json fields
            if row["meta_json"]:
                meta = json.loads(row["meta_json"])
                tracker.update(meta)
            config.append(tracker)

        # Fetch entries for last 7 days with version info
        seven_days_ago = (datetime.now() - timedelta(days=7)).strftime("%Y-%m-%d")
        cursor.execute(
            "SELECT * FROM entries WHERE date >= ?",
            (seven_days_ago,)
        )
        entry_rows = cursor.fetchall()

        # Transform to client format
        days = {}
        for row in entry_rows:
            date_str = row["date"]
            tracker_id = row["tracker_id"]

            if date_str not in days:
                days[date_str] = {}

            days[date_str][tracker_id] = {
                "value": row["value"],
                "completed": bool(row["completed"]) if row["completed"] is not None else None,
                "_version": row["version"] or 1,
                "_lastModifiedBy": row["last_modified_by"],
                "_lastModifiedAt": row["last_modified_at"]
            }

        return FullSyncResponse(config=config, days=days, serverTime=get_utc_now())


@app.get("/api/sync/delta")
def sync_delta(since: str, client_id: str):
    """Get changes since a specific timestamp for incremental sync."""
    with get_db() as conn:
        cursor = conn.cursor()

        # Fetch trackers modified since timestamp
        cursor.execute("""
            SELECT * FROM trackers
            WHERE last_modified_at > ? OR last_modified_at IS NULL
        """, (since,))
        tracker_rows = cursor.fetchall()

        config = []
        deleted_trackers = []
        for row in tracker_rows:
            if row["deleted"]:
                deleted_trackers.append(row["id"])
            else:
                tracker = {
                    "id": row["id"],
                    "name": row["name"],
                    "category": row["category"],
                    "type": row["type"],
                    "_version": row["version"] or 1,
                    "_lastModifiedBy": row["last_modified_by"],
                    "_lastModifiedAt": row["last_modified_at"]
                }
                if row["meta_json"]:
                    meta = json.loads(row["meta_json"])
                    tracker.update(meta)
                config.append(tracker)

        # Fetch entries modified since timestamp (last 7 days only)
        seven_days_ago = (datetime.now() - timedelta(days=7)).strftime("%Y-%m-%d")
        cursor.execute("""
            SELECT * FROM entries
            WHERE (last_modified_at > ? OR last_modified_at IS NULL)
            AND date >= ?
        """, (since, seven_days_ago))
        entry_rows = cursor.fetchall()

        days = {}
        for row in entry_rows:
            date_str = row["date"]
            tracker_id = row["tracker_id"]

            if date_str not in days:
                days[date_str] = {}

            days[date_str][tracker_id] = {
                "value": row["value"],
                "completed": bool(row["completed"]) if row["completed"] is not None else None,
                "_version": row["version"] or 1,
                "_lastModifiedBy": row["last_modified_by"],
                "_lastModifiedAt": row["last_modified_at"]
            }

        return DeltaSyncResponse(
            config=config,
            days=days,
            deletedTrackers=deleted_trackers,
            serverTime=get_utc_now()
        )


@app.post("/api/sync/update", response_model=SyncResponse)
def sync_update(payload: SyncPayload):
    """Update server with client data, with conflict detection."""
    conflicts = []
    applied_config = []
    applied_days = {}
    overwritten_data = []
    now = get_utc_now()
    client_id = payload.clientId

    with get_db() as conn:
        cursor = conn.cursor()

        # Update client last seen
        cursor.execute("""
            INSERT OR REPLACE INTO clients (id, name, last_seen_at)
            VALUES (?, ?, ?)
        """, (client_id, f"Client-{client_id[:8]}", now))

        try:
            # 1. Process tracker configs with version checking
            for item in payload.config:
                tracker_id = item.get("id")
                client_base_version = item.get("_baseVersion", 0)
                is_deleted = item.get("_deleted", False)

                # Check current server version
                cursor.execute(
                    "SELECT version, name, category, type, meta_json, deleted FROM trackers WHERE id = ?",
                    (tracker_id,)
                )
                row = cursor.fetchone()
                server_version = row["version"] if row else 0

                # Conflict detection: server was modified by another client
                if row and server_version > client_base_version:
                    server_data = {
                        "id": tracker_id,
                        "name": row["name"],
                        "category": row["category"],
                        "type": row["type"],
                        "_version": server_version
                    }
                    if row["meta_json"]:
                        server_data.update(json.loads(row["meta_json"]))

                    conflicts.append(ConflictInfo(
                        entityType="tracker",
                        entityId=tracker_id,
                        serverVersion=server_version,
                        clientBaseVersion=client_base_version,
                        serverData=server_data
                    ))
                    continue

                # No conflict - apply update
                name = item.get("name")
                category = item.get("category", "")
                tracker_type = item.get("type", "simple")
                new_version = server_version + 1

                # Extract meta_json (all fields except known ones)
                excluded_keys = {"id", "name", "category", "type", "_version", "_baseVersion",
                               "_lastModifiedBy", "_lastModifiedAt", "_deleted"}
                meta = {k: v for k, v in item.items() if k not in excluded_keys}

                if is_deleted:
                    # Soft delete
                    cursor.execute("""
                        UPDATE trackers SET deleted = 1, version = ?,
                        last_modified_by = ?, last_modified_at = ?
                        WHERE id = ?
                    """, (new_version, client_id, now, tracker_id))
                else:
                    cursor.execute("""
                        INSERT INTO trackers (id, name, category, type, meta_json, version,
                                            last_modified_by, last_modified_at, deleted)
                        VALUES (?, ?, ?, ?, ?, ?, ?, ?, 0)
                        ON CONFLICT(id) DO UPDATE SET
                            name = excluded.name,
                            category = excluded.category,
                            type = excluded.type,
                            meta_json = excluded.meta_json,
                            version = excluded.version,
                            last_modified_by = excluded.last_modified_by,
                            last_modified_at = excluded.last_modified_at,
                            deleted = 0
                    """, (tracker_id, name, category, tracker_type, json.dumps(meta),
                          new_version, client_id, now))

                applied_config.append({
                    **item,
                    "_version": new_version,
                    "_lastModifiedBy": client_id,
                    "_lastModifiedAt": now
                })

            # 2. Process daily logs with version checking
            for date_str, trackers_map in payload.days.items():
                if date_str not in applied_days:
                    applied_days[date_str] = {}

                for tracker_id, data in trackers_map.items():
                    client_base_version = data.get("_baseVersion", 0)

                    # Check current server version
                    cursor.execute(
                        "SELECT version, value, completed FROM entries WHERE date = ? AND tracker_id = ?",
                        (date_str, tracker_id)
                    )
                    row = cursor.fetchone()
                    server_version = row["version"] if row else 0

                    # Conflict detection
                    if row and server_version > client_base_version:
                        server_data = {
                            "value": row["value"],
                            "completed": bool(row["completed"]) if row["completed"] is not None else None,
                            "_version": server_version
                        }
                        conflicts.append(ConflictInfo(
                            entityType="entry",
                            entityId=f"{date_str}|{tracker_id}",
                            serverVersion=server_version,
                            clientBaseVersion=client_base_version,
                            serverData=server_data
                        ))
                        continue

                    # No conflict - apply update
                    value = data.get("value")
                    completed = data.get("completed")
                    completed_int = 1 if completed else 0 if completed is not None else None
                    new_version = server_version + 1

                    cursor.execute("""
                        INSERT INTO entries (date, tracker_id, value, completed, version,
                                           last_modified_by, last_modified_at)
                        VALUES (?, ?, ?, ?, ?, ?, ?)
                        ON CONFLICT(date, tracker_id) DO UPDATE SET
                            value = excluded.value,
                            completed = excluded.completed,
                            version = excluded.version,
                            last_modified_by = excluded.last_modified_by,
                            last_modified_at = excluded.last_modified_at
                    """, (date_str, tracker_id, value, completed_int, new_version, client_id, now))

                    applied_days[date_str][tracker_id] = {
                        "value": value,
                        "completed": completed,
                        "_version": new_version,
                        "_lastModifiedBy": client_id,
                        "_lastModifiedAt": now
                    }

            # 3. Update sync time only if no conflicts
            if not conflicts:
                cursor.execute("""
                    INSERT OR REPLACE INTO meta_sync (key, value)
                    VALUES ('last_server_sync_time', ?)
                """, (now,))

            conn.commit()

            return SyncResponse(
                success=len(conflicts) == 0,
                conflicts=conflicts,
                appliedConfig=applied_config,
                appliedDays=applied_days,
                lastModified=now if not conflicts else None,
                overwrittenData=overwritten_data
            )

        except Exception as e:
            conn.rollback()
            raise HTTPException(status_code=500, detail=str(e))


@app.post("/api/sync/resolve-conflict")
def resolve_conflict(
    entity_type: str,
    entity_id: str,
    resolution: str,  # 'client' or 'server'
    client_id: str,
    client_data: Optional[dict[str, Any]] = None
):
    """Resolve a specific conflict by choosing client or server version."""
    now = get_utc_now()

    with get_db() as conn:
        cursor = conn.cursor()

        if resolution == "client" and client_data:
            # Apply client data with force (increment version)
            if entity_type == "tracker":
                cursor.execute("SELECT version FROM trackers WHERE id = ?", (entity_id,))
                row = cursor.fetchone()
                new_version = (row["version"] if row else 0) + 1

                name = client_data.get("name")
                category = client_data.get("category", "")
                tracker_type = client_data.get("type", "simple")
                excluded_keys = {"id", "name", "category", "type", "_version", "_baseVersion",
                               "_lastModifiedBy", "_lastModifiedAt", "_deleted"}
                meta = {k: v for k, v in client_data.items() if k not in excluded_keys}

                cursor.execute("""
                    INSERT OR REPLACE INTO trackers
                    (id, name, category, type, meta_json, version, last_modified_by, last_modified_at, deleted)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, 0)
                """, (entity_id, name, category, tracker_type, json.dumps(meta),
                      new_version, client_id, now))

            elif entity_type == "entry":
                date_str, tracker_id = entity_id.split("|")
                cursor.execute(
                    "SELECT version FROM entries WHERE date = ? AND tracker_id = ?",
                    (date_str, tracker_id)
                )
                row = cursor.fetchone()
                new_version = (row["version"] if row else 0) + 1

                value = client_data.get("value")
                completed = client_data.get("completed")
                completed_int = 1 if completed else 0 if completed is not None else None

                cursor.execute("""
                    INSERT OR REPLACE INTO entries
                    (date, tracker_id, value, completed, version, last_modified_by, last_modified_at)
                    VALUES (?, ?, ?, ?, ?, ?, ?)
                """, (date_str, tracker_id, value, completed_int, new_version, client_id, now))

        # Log the resolution
        cursor.execute("""
            INSERT INTO sync_conflicts
            (entity_type, entity_id, client_id, client_data, resolution, resolved_at, created_at)
            VALUES (?, ?, ?, ?, ?, ?, ?)
        """, (entity_type, entity_id, client_id,
              json.dumps(client_data) if client_data else None,
              resolution, now, now))

        # Update sync time
        cursor.execute("""
            INSERT OR REPLACE INTO meta_sync (key, value)
            VALUES ('last_server_sync_time', ?)
        """, (now,))

        conn.commit()

        return {"status": "ok", "resolution": resolution, "entityId": entity_id}


@app.get("/api/sync/conflicts")
def get_unresolved_conflicts(client_id: str):
    """Get unresolved conflicts for a client."""
    with get_db() as conn:
        cursor = conn.cursor()
        cursor.execute("""
            SELECT * FROM sync_conflicts
            WHERE client_id = ? AND resolved_at IS NULL
            ORDER BY created_at DESC
        """, (client_id,))
        rows = cursor.fetchall()

        conflicts = []
        for row in rows:
            conflicts.append({
                "id": row["id"],
                "entityType": row["entity_type"],
                "entityId": row["entity_id"],
                "clientData": json.loads(row["client_data"]) if row["client_data"] else None,
                "serverData": json.loads(row["server_data"]) if row["server_data"] else None,
                "createdAt": row["created_at"]
            })

        return {"conflicts": conflicts}


# Static file serving
@app.get("/")
def serve_root():
    """Serve the main index.html with cache-busting version injected."""
    index_path = PUBLIC_DIR / "index.html"
    if not index_path.exists():
        raise HTTPException(status_code=404, detail="index.html not found")

    # Read and inject version into static file URLs
    html = index_path.read_text()
    html = html.replace('href="/styles.css"', f'href="/styles.css?v={SERVER_VERSION}"')
    html = html.replace('src="/js/app.js"', f'src="/js/app.js?v={SERVER_VERSION}"')

    return HTMLResponse(content=html)


@app.get("/styles.css")
def serve_css():
    """Serve the stylesheet with no-cache headers."""
    css_path = PUBLIC_DIR / "styles.css"
    if css_path.exists():
        return FileResponse(
            css_path,
            media_type="text/css",
            headers={"Cache-Control": "no-cache, must-revalidate"}
        )
    raise HTTPException(status_code=404, detail="styles.css not found")


@app.get("/js/{file_path:path}")
def serve_js(file_path: str):
    """Serve JavaScript files with no-cache headers."""
    js_path = PUBLIC_DIR / "js" / file_path
    if js_path.exists() and js_path.is_file():
        return FileResponse(
            js_path,
            media_type="application/javascript",
            headers={"Cache-Control": "no-cache, must-revalidate"}
        )
    raise HTTPException(status_code=404, detail=f"JS file not found: {file_path}")


if __name__ == "__main__":
    import argparse
    import uvicorn

    parser = argparse.ArgumentParser(description="Personal Journal Server")
    parser.add_argument("--test", action="store_true", help="Run in testing mode (port 8001)")
    parser.add_argument("--port", type=int, help="Override the port number")
    args = parser.parse_args()

    port = args.port if args.port else (8001 if args.test else 8000)
    uvicorn.run(app, host="0.0.0.0", port=port)
