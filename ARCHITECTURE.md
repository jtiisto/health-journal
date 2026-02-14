# Architecture

This document describes the overall architecture of the Personal Journal application, a full-stack system for habit and metric tracking with multi-device synchronization.

## System Overview

```
┌─────────────────────────────────────────────────────────────────┐
│                        Client Devices                           │
│  ┌──────────────┐  ┌──────────────┐  ┌──────────────┐          │
│  │   Browser    │  │   Browser    │  │   Browser    │          │
│  │   (PWA)      │  │   (PWA)      │  │   (PWA)      │          │
│  │              │  │              │  │              │          │
│  │ LocalForage  │  │ LocalForage  │  │ LocalForage  │          │
│  └──────┬───────┘  └──────┬───────┘  └──────┬───────┘          │
└─────────┼─────────────────┼─────────────────┼──────────────────┘
          │                 │                 │
          │    HTTP/REST    │                 │
          └────────────────┬┴─────────────────┘
                           │
┌──────────────────────────┼──────────────────────────────────────┐
│                    FastAPI Server                               │
│  ┌───────────────────────┴────────────────────────────────┐    │
│  │                    API Endpoints                        │    │
│  │  /api/sync/status  /api/sync/full  /api/sync/delta     │    │
│  │  /api/sync/update  /api/sync/register                  │    │
│  │  /api/sync/resolve-conflict  /api/sync/conflicts       │    │
│  └───────────────────────┬────────────────────────────────┘    │
│                          │                                      │
│  ┌───────────────────────┴────────────────────────────────┐    │
│  │              Static File Serving                        │    │
│  │         (HTML, CSS, JS with cache busting)              │    │
│  └────────────────────────────────────────────────────────┘    │
└──────────────────────────┬──────────────────────────────────────┘
                           │
┌──────────────────────────┼──────────────────────────────────────┐
│                     SQLite Database                             │
│  ┌────────────┐ ┌────────────┐ ┌────────────┐ ┌────────────┐   │
│  │  trackers  │ │  entries   │ │  clients   │ │sync_conflicts│  │
│  └────────────┘ └────────────┘ └────────────┘ └────────────┘   │
└──────────────────────────┬──────────────────────────────────────┘
                           │
┌──────────────────────────┼──────────────────────────────────────┐
│                    MCP Server (Optional)                        │
│  ┌───────────────────────┴────────────────────────────────┐    │
│  │              Read-Only Database Access                  │    │
│  │    Tools: list_trackers, get_entries, execute_sql      │    │
│  └────────────────────────────────────────────────────────┘    │
│                          │                                      │
│                    LLM Integration                              │
└─────────────────────────────────────────────────────────────────┘
```

## Frontend Application (PWA)

### No-Build Architecture

The frontend uses a **no-build architecture**, eliminating the need for bundlers, transpilers, or build steps. This is achieved through:

- **ES Modules**: Native browser support for `import`/`export` via `<script type="module">`
- **Import Maps**: Browser-native dependency resolution without bundling
- **CDN Dependencies**: Libraries loaded directly from esm.sh
- **htm**: Tagged template literals for JSX-like syntax without compilation

```html
<script type="importmap">
{
    "imports": {
        "preact": "https://esm.sh/preact@10.19.3",
        "preact/hooks": "https://esm.sh/preact@10.19.3/hooks",
        "@preact/signals": "https://esm.sh/@preact/signals@1.2.1",
        "htm": "https://esm.sh/htm@3.1.1",
        "localforage": "https://esm.sh/localforage@1.10.0"
    }
}
</script>
```

### Technology Stack

| Library | Purpose |
|---------|---------|
| **Preact** | Lightweight React alternative (3KB) |
| **Preact Signals** | Reactive state management |
| **htm** | JSX-like templates without build step |
| **LocalForage** | IndexedDB wrapper for offline storage |

### Offline-First Design

The application is designed to work offline with eventual consistency:

1. **Local Storage**: All data is persisted in IndexedDB via LocalForage
2. **Dirty Tracking**: Changes are marked as "dirty" until synced
3. **Background Sync**: Automatic synchronization when online
4. **Conflict Detection**: Version-based conflict detection for concurrent edits

```
┌─────────────────────────────────────────────────────────┐
│                   Client State                          │
│                                                         │
│  trackerConfig[]     dailyLogs{}      syncMetadata{}   │
│  ├─ id               ├─ "2024-01-22"  ├─ clientId      │
│  ├─ name             │  └─ trackerId  ├─ lastSyncTime  │
│  ├─ category         │     ├─ value   ├─ dirtyTrackers │
│  ├─ type             │     ├─ done    └─ dirtyEntries  │
│  ├─ _version         │     └─ _version                 │
│  └─ _baseVersion     └─ ...                            │
└─────────────────────────────────────────────────────────┘
```

### PWA Capabilities

- **Fully Installable**: Web App Manifest with icons, passes Chrome installability checks
- **Service Worker**: Offline asset caching with network-first strategy for app shell
- **Mobile-Optimized**: Responsive design with touch-friendly controls
- **Viewport Locked**: No zoom to maintain consistent UI

### Service Worker (`public/sw.js`)

The service worker provides offline asset caching alongside the existing LocalForage data layer:

| Request Type | Strategy | Rationale |
|-------------|----------|-----------|
| API (`/api/*`) | Network-only | LocalForage handles offline data |
| CDN (`esm.sh`) | Cache-first | Versioned/immutable URLs |
| App shell (local files) | Network-first, cache fallback | Respects server cache-busting |

Cache versioning uses a `CACHE_VERSION` constant. On `activate`, old caches are deleted and `clients.claim()` is called for immediate control. Query parameters are stripped when matching cache keys to work with the server's `?v={uuid}` cache-busting.

### App Icons (`public/icons/`)

| File | Size | Purpose |
|------|------|---------|
| `icon.svg` | scalable | Favicon |
| `icon-192.png` | 192x192 | Manifest icon |
| `icon-512.png` | 512x512 | Manifest icon, splash |
| `icon-maskable-192.png` | 192x192 | Android adaptive icon |
| `icon-maskable-512.png` | 512x512 | Android adaptive icon |
| `apple-touch-icon.png` | 180x180 | iOS home screen |

## Backend Server

### FastAPI Implementation

The server (`src/server.py`) provides:

1. **REST API**: Sync endpoints for multi-client data synchronization
2. **Static File Serving**: HTML, CSS, and JavaScript with cache busting
3. **PWA Asset Serving**: Manifest, service worker, and icons with appropriate cache headers
4. **Database Management**: SQLite initialization and migrations

### Static File Serving

Static files are served with cache-busting to ensure clients always receive the latest code:

```python
# Unique version generated on each server start
SERVER_VERSION = uuid.uuid4().hex[:8]

# Injected into HTML
html = html.replace('href="/styles.css"', f'href="/styles.css?v={SERVER_VERSION}"')
```

### PWA Asset Endpoints

| Endpoint | Content-Type | Cache Policy |
|----------|-------------|-------------|
| `/manifest.json` | `application/manifest+json` | `no-cache, must-revalidate` |
| `/sw.js` | `application/javascript` | `no-cache, must-revalidate` + `Service-Worker-Allowed: /` |
| `/icons/{path}` | `image/png` or `image/svg+xml` | `public, max-age=86400` |

### API Endpoints

| Endpoint | Method | Description |
|----------|--------|-------------|
| `/api/sync/status` | GET | Get server's last sync timestamp |
| `/api/sync/register` | POST | Register a client device |
| `/api/sync/full` | GET | Full data dump for initial sync |
| `/api/sync/delta` | GET | Changes since timestamp (incremental sync) |
| `/api/sync/update` | POST | Upload client changes with conflict detection |
| `/api/sync/resolve-conflict` | POST | Resolve a specific conflict |
| `/api/sync/conflicts` | GET | Get unresolved conflicts for a client |

### Server Modes

The server supports multiple running modes:

```bash
./bin/server.sh start           # Production mode (port 8000)
./bin/server.sh --test start    # Test mode (port 8001)
python src/server.py --port 9000  # Custom port
```

## Database

### SQLite Schema

The database uses SQLite for simplicity and portability, with per-record versioning for conflict detection.

#### Tables

**trackers** - Tracker definitions
```sql
CREATE TABLE trackers (
    id TEXT PRIMARY KEY,
    name TEXT,
    category TEXT,
    type TEXT,              -- 'simple', 'quantifiable', 'evaluation'
    meta_json TEXT,         -- Additional metadata as JSON
    version INTEGER,        -- Increments on each modification
    last_modified_by TEXT,  -- Client ID that made the change
    last_modified_at TEXT,  -- ISO-8601 timestamp
    deleted INTEGER         -- Soft delete flag
)
```

**entries** - Daily journal entries
```sql
CREATE TABLE entries (
    date TEXT,              -- YYYY-MM-DD
    tracker_id TEXT,
    value REAL,             -- Numeric value for quantifiable trackers
    completed INTEGER,      -- Boolean for simple trackers
    version INTEGER,
    last_modified_by TEXT,
    last_modified_at TEXT,
    PRIMARY KEY (date, tracker_id)
)
```

**clients** - Registered client devices
```sql
CREATE TABLE clients (
    id TEXT PRIMARY KEY,
    name TEXT,
    last_seen_at TEXT
)
```

**sync_conflicts** - Conflict resolution history
```sql
CREATE TABLE sync_conflicts (
    id INTEGER PRIMARY KEY,
    entity_type TEXT,       -- 'tracker' or 'entry'
    entity_id TEXT,
    client_id TEXT,
    client_data TEXT,
    server_data TEXT,
    resolution TEXT,        -- 'client' or 'server'
    resolved_at TEXT,
    created_at TEXT
)
```

### Versioning System

Each record maintains version metadata for optimistic concurrency control:

- **version**: Increments on every server-side modification
- **_baseVersion**: The version the client's changes are based on
- **last_modified_by**: Client ID that made the change
- **last_modified_at**: Timestamp of the modification

## Synchronization Protocol

### Sync Flow

```
┌──────────┐                              ┌──────────┐
│  Client  │                              │  Server  │
└────┬─────┘                              └────┬─────┘
     │                                         │
     │  1. GET /api/sync/delta?since=T         │
     │────────────────────────────────────────>│
     │                                         │
     │  2. {config[], days{}, serverTime}      │
     │<────────────────────────────────────────│
     │                                         │
     │  3. Detect local conflicts              │
     │  4. Apply non-conflicting changes       │
     │                                         │
     │  5. POST /api/sync/update               │
     │     {clientId, config[], days{}}        │
     │────────────────────────────────────────>│
     │                                         │
     │  6. Version check per record            │
     │  7. Apply or report conflicts           │
     │                                         │
     │  8. {success, conflicts[], applied}     │
     │<────────────────────────────────────────│
     │                                         │
```

### Conflict Detection

Conflicts are detected using version comparison:

1. **Client sends** `_baseVersion` (the version it last saw)
2. **Server compares** `_baseVersion` with current `version`
3. **If `server.version > client._baseVersion`**: Another client modified the record → **Conflict**
4. **Otherwise**: Safe to apply the change

### Conflict Resolution

When conflicts occur:

1. **Auto-merge**: Non-overlapping field changes can be automatically merged
2. **User resolution**: Overlapping changes require user to choose:
   - **Keep mine**: Client data overwrites server
   - **Keep server**: Server data overwrites local

## MCP Server

### Purpose

The MCP (Model Context Protocol) server provides **read-only** access to journal data for LLM integration, allowing AI assistants to analyze habits and provide insights.

### Security Model

- **Read-only database connection**: `file:{path}?mode=ro`
- **Query validation**: Only SELECT/WITH statements allowed
- **Forbidden keywords**: INSERT, UPDATE, DELETE, DROP, etc. blocked
- **Row limits**: Results capped at 1000 rows by default
- **No multi-statement queries**: Semicolons rejected outside strings

### Available Tools

| Tool | Description |
|------|-------------|
| `explore_database_structure` | List tables with row counts |
| `get_table_details` | Show columns and sample data |
| `execute_sql_query` | Run custom SELECT queries |
| `list_trackers` | List all trackers with metadata |
| `get_entries` | Get entries for date ranges |
| `get_journal_summary` | Summary statistics |

### Configuration

The MCP server is configured via environment variables:

```json
{
  "mcpServers": {
    "journal": {
      "command": "python",
      "args": ["-m", "journal_mcp"],
      "env": {
        "JOURNAL_DB_PATH": "/path/to/journal.db",
        "PYTHONPATH": "/path/to/journal/src"
      }
    }
  }
}
```

## Data Flow

### Creating a Tracker

```
User Action          Frontend                    Backend               Database
    │                   │                          │                      │
    │ Create Tracker    │                          │                      │
    │──────────────────>│                          │                      │
    │                   │                          │                      │
    │                   │ Add to trackerConfig     │                      │
    │                   │ Mark as dirty            │                      │
    │                   │ Save to LocalForage      │                      │
    │                   │                          │                      │
    │                   │ POST /api/sync/update    │                      │
    │                   │─────────────────────────>│                      │
    │                   │                          │                      │
    │                   │                          │ INSERT tracker       │
    │                   │                          │─────────────────────>│
    │                   │                          │                      │
    │                   │ {success, _version: 1}   │                      │
    │                   │<─────────────────────────│                      │
    │                   │                          │                      │
    │                   │ Update _baseVersion      │                      │
    │                   │ Clear dirty flag         │                      │
    │                   │                          │                      │
```

### Recording an Entry

```
User Action          Frontend                    Backend               Database
    │                   │                          │                      │
    │ Check/Update      │                          │                      │
    │──────────────────>│                          │                      │
    │                   │                          │                      │
    │                   │ Update dailyLogs         │                      │
    │                   │ Mark entry dirty         │                      │
    │                   │ Save to LocalForage      │                      │
    │                   │                          │                      │
    │                   │ POST /api/sync/update    │                      │
    │                   │─────────────────────────>│                      │
    │                   │                          │                      │
    │                   │                          │ UPSERT entry         │
    │                   │                          │─────────────────────>│
    │                   │                          │                      │
    │                   │ {success, _version: N}   │                      │
    │                   │<─────────────────────────│                      │
    │                   │                          │                      │
```

## Design Decisions

### Why No-Build Frontend?

1. **Simplicity**: No webpack, vite, or other build tools to configure
2. **Debugging**: Source code in browser matches actual files
3. **Fast iteration**: Edit and refresh, no compilation step
4. **Reduced dependencies**: No dev dependencies for building

### Why SQLite?

1. **Zero configuration**: Single file database
2. **Portability**: Easy backup and migration
3. **Performance**: Excellent for single-server, moderate-scale applications
4. **Reliability**: ACID-compliant with battle-tested stability

### Why Per-Record Versioning?

1. **Fine-grained conflicts**: Only conflicting records need resolution
2. **Partial sync success**: Non-conflicting changes can be applied
3. **Audit trail**: Track which client modified each record
4. **Scalability**: Better than whole-database version locks

### Why Offline-First?

1. **Reliability**: App works regardless of network
2. **Performance**: Instant UI response, sync in background
3. **Mobile-friendly**: Handles spotty connections gracefully
4. **User experience**: No loading spinners for data access
