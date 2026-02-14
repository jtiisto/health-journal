# Personal Journal

A full-stack web application for personal habit and metric tracking with multi-device sync capabilities.

## Features

- **Installable PWA**: Full Progressive Web App with offline support, installable on mobile and desktop
- **Tracker Management**: Create and manage trackers for habits, supplements, metrics, and more
- **Multiple Tracker Types**:
  - Simple (checkbox/boolean)
  - Quantifiable (numeric values)
  - Evaluation (rating scales)
  - Note (free-text input)
- **Offline-First**: All data persisted locally via IndexedDB, service worker caches app shell for full offline use
- **Multi-Client Sync**: Sync data across multiple devices with conflict detection and resolution
- **Per-Record Versioning**: Track changes at the individual record level
- **MCP Integration**: Model Context Protocol server for LLM access to journal data

## Project Structure

```
journal/
├── src/                    # Source code
│   ├── server.py           # FastAPI backend server
│   └── journal_mcp/        # MCP server package for LLM integration
├── public/                 # Frontend static files
│   ├── index.html          # Main HTML entry point
│   ├── styles.css          # Stylesheet
│   ├── manifest.json       # PWA web app manifest
│   ├── sw.js               # Service worker for offline caching
│   ├── icons/              # App icons (SVG, PNG, maskable)
│   └── js/                 # JavaScript modules
│       ├── app.js          # Main application component
│       ├── store.js        # State management with signals
│       ├── utils.js        # Utility functions
│       └── components/     # UI components
├── bin/                    # Executable scripts
│   └── server.sh           # Server control script
├── test/                   # Test files
├── docs/                   # Documentation
├── requirements.txt        # Python dependencies
└── journal.db              # SQLite database (created on first run)
```

## Requirements

- Python 3.10+
- pip

## Setup

1. Clone the repository:
   ```bash
   git clone <repository-url>
   cd journal
   ```

2. Create and activate a virtual environment:
   ```bash
   python -m venv venv
   source venv/bin/activate  # On Windows: venv\Scripts\activate
   ```

3. Install dependencies:
   ```bash
   pip install -r requirements.txt
   ```

## Usage

### Starting the Server

Use the server control script:

```bash
./bin/server.sh start
```

Or run directly with Python:

```bash
source venv/bin/activate
python src/server.py
```

The server will start on `http://localhost:8000`.

### Running in Test Mode

Test mode runs the server on port 8001, allowing you to run both production and test instances simultaneously on the same machine:

```bash
./bin/server.sh --test start
```

Or run directly with Python:

```bash
python src/server.py --test
```

You can also specify a custom port:

```bash
python src/server.py --port 9000
```

### Server Commands

```bash
./bin/server.sh start         # Start the server (port 8000)
./bin/server.sh --test start  # Start in test mode (port 8001)
./bin/server.sh stop          # Stop the server
./bin/server.sh status        # Check server status
./bin/server.sh restart       # Restart the server
./bin/server.sh logs          # Show last 50 lines of logs
./bin/server.sh follow        # Follow logs in real-time
```

### Accessing the Application

Open your browser and navigate to `http://localhost:8000` (or `http://localhost:8001` in test mode).

## API Endpoints

| Endpoint | Method | Description |
|----------|--------|-------------|
| `/api/sync/status` | GET | Get last sync time |
| `/api/sync/register` | POST | Register a client |
| `/api/sync/full` | GET | Get full data dump |
| `/api/sync/delta` | GET | Get changes since timestamp |
| `/api/sync/update` | POST | Update server with client data |
| `/api/sync/resolve-conflict` | POST | Resolve sync conflicts |
| `/api/sync/conflicts` | GET | Get unresolved conflicts |

## MCP Server

The journal includes an MCP (Model Context Protocol) server for LLM integration, providing read-only access to journal data.

### Running the MCP Server

```bash
JOURNAL_DB_PATH=/path/to/journal.db PYTHONPATH=src python -m journal_mcp
```

### MCP Tools Available

- `explore_database_structure`: View available tables and structure
- `get_table_details`: Get column info and sample data for a table
- `execute_sql_query`: Run custom SELECT queries
- `list_trackers`: List all trackers
- `get_entries`: Get journal entries for date ranges
- `get_journal_summary`: Get summary statistics

## Technology Stack

### Backend
- FastAPI
- SQLite
- Uvicorn
- Pydantic

### Frontend
- Preact
- Preact Signals (state management)
- htm (template literals)
- LocalForage (local storage)

### MCP Integration
- FastMCP

## Development

### Running in Development Mode

```bash
source venv/bin/activate
uvicorn src.server:app --reload --host 0.0.0.0 --port 8000
```

### Running Tests

The project includes a comprehensive test suite with unit, integration, and end-to-end tests. Tests run automatically via git hooks before commits and pushes.

**Run all tests:**

```bash
pytest test/ -v
```

**Run tests by category:**

```bash
pytest test/ -m unit         # Unit tests only
pytest test/ -m integration  # Integration tests only
pytest test/ -m e2e          # End-to-end tests only
```

**Run tests with coverage:**

```bash
pytest test/ -v --cov=src --cov-report=term-missing
```

**Run a specific test file:**

```bash
pytest test/integration/test_sync_update.py -v
```

### Database Schema

The SQLite database contains the following tables:

- **trackers**: Tracker definitions (id, name, category, type, metadata)
- **entries**: Daily journal entries (date, tracker_id, value, completed)
- **clients**: Connected client devices
- **meta_sync**: Sync metadata
- **sync_conflicts**: Conflict resolution history

## License

MIT
