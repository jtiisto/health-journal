#!/bin/bash

# Server control script for Personal Journal
# Usage: ./server.sh {start|stop|status|restart|logs}

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
VENV_DIR="$PROJECT_ROOT/venv"
PID_FILE="$PROJECT_ROOT/.server.pid"
LOG_FILE="$PROJECT_ROOT/server.log"
SRC_DIR="$PROJECT_ROOT/src"
PORT=8001

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

get_pid() {
    if [ -f "$PID_FILE" ]; then
        cat "$PID_FILE"
    fi
}

is_running() {
    local pid=$(get_pid)
    if [ -n "$pid" ] && kill -0 "$pid" 2>/dev/null; then
        return 0
    fi
    # Also check if something is listening on the port
    if lsof -i :"$PORT" -sTCP:LISTEN >/dev/null 2>&1; then
        return 0
    fi
    return 1
}

start_server() {
    if is_running; then
        echo -e "${YELLOW}Server is already running${NC}"
        status_server
        return 1
    fi

    echo -e "${GREEN}Starting server...${NC}"

    # Activate virtual environment and start server
    cd "$PROJECT_ROOT"
    source "$VENV_DIR/bin/activate"

    nohup python "$SRC_DIR/server.py" > "$LOG_FILE" 2>&1 &
    local pid=$!
    echo $pid > "$PID_FILE"

    # Wait a moment and check if it started
    sleep 2

    if is_running; then
        echo -e "${GREEN}Server started successfully (PID: $pid)${NC}"
        echo -e "URL: http://localhost:$PORT"
    else
        echo -e "${RED}Failed to start server. Check logs:${NC}"
        tail -20 "$LOG_FILE"
        rm -f "$PID_FILE"
        return 1
    fi
}

stop_server() {
    if ! is_running; then
        echo -e "${YELLOW}Server is not running${NC}"
        rm -f "$PID_FILE"
        return 0
    fi

    echo -e "${YELLOW}Stopping server...${NC}"

    local pid=$(get_pid)
    if [ -n "$pid" ]; then
        kill "$pid" 2>/dev/null
        sleep 1

        # Force kill if still running
        if kill -0 "$pid" 2>/dev/null; then
            kill -9 "$pid" 2>/dev/null
        fi
    fi

    # Also kill any process on the port
    fuser -k "$PORT/tcp" 2>/dev/null

    rm -f "$PID_FILE"
    echo -e "${GREEN}Server stopped${NC}"
}

status_server() {
    if is_running; then
        local pid=$(get_pid)
        echo -e "${GREEN}Server is running${NC}"
        if [ -n "$pid" ]; then
            echo "  PID: $pid"
        fi
        echo "  URL: http://localhost:$PORT"

        # Check API health
        if curl -s "http://localhost:$PORT/api/sync/status" >/dev/null 2>&1; then
            echo -e "  API: ${GREEN}healthy${NC}"
        else
            echo -e "  API: ${RED}not responding${NC}"
        fi
    else
        echo -e "${RED}Server is not running${NC}"
        return 1
    fi
}

restart_server() {
    echo "Restarting server..."
    stop_server
    sleep 1
    start_server
}

show_logs() {
    if [ -f "$LOG_FILE" ]; then
        echo -e "${YELLOW}=== Server Logs (last 50 lines) ===${NC}"
        tail -50 "$LOG_FILE"
    else
        echo -e "${YELLOW}No log file found${NC}"
    fi
}

follow_logs() {
    if [ -f "$LOG_FILE" ]; then
        echo -e "${YELLOW}=== Following server logs (Ctrl+C to exit) ===${NC}"
        tail -f "$LOG_FILE"
    else
        echo -e "${YELLOW}No log file found${NC}"
    fi
}

usage() {
    echo "Usage: $0 {start|stop|status|restart|logs|follow}"
    echo ""
    echo "Commands:"
    echo "  start   - Start the server"
    echo "  stop    - Stop the server"
    echo "  status  - Check if server is running"
    echo "  restart - Restart the server"
    echo "  logs    - Show last 50 lines of logs"
    echo "  follow  - Follow logs in real-time"
}

# Main
case "$1" in
    start)
        start_server
        ;;
    stop)
        stop_server
        ;;
    status)
        status_server
        ;;
    restart)
        restart_server
        ;;
    logs)
        show_logs
        ;;
    follow)
        follow_logs
        ;;
    *)
        usage
        exit 1
        ;;
esac
