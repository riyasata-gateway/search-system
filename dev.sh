#!/usr/bin/env bash
# dev.sh — start the full PharmaWatch local dev stack with one command
set -euo pipefail

BLUE='\033[0;34m'
GREEN='\033[0;32m'
RED='\033[0;31m'
YELLOW='\033[1;33m'
NC='\033[0m'

log()  { echo -e "${BLUE}[PharmaWatch]${NC} $*"; }
ok()   { echo -e "${GREEN}[OK]${NC} $*"; }
warn() { echo -e "${YELLOW}[WARN]${NC} $*"; }
err()  { echo -e "${RED}[ERR]${NC} $*" >&2; }

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

API_PID="" WORKER_PID="" FRONTEND_PID=""

cleanup() {
    echo ""
    log "Shutting down..."
    [[ -n "$FRONTEND_PID" ]] && kill "$FRONTEND_PID" 2>/dev/null && log "Stopped frontend (PID $FRONTEND_PID)"
    [[ -n "$WORKER_PID"   ]] && kill "$WORKER_PID"   2>/dev/null && log "Stopped worker  (PID $WORKER_PID)"
    [[ -n "$API_PID"      ]] && kill "$API_PID"       2>/dev/null && log "Stopped API     (PID $API_PID)"
    ok "All processes stopped. Bye!"
    exit 0
}
trap cleanup INT TERM

# ── Pre-flight checks ─────────────────────────────────────────────────────────
log "Checking prerequisites..."

if [[ ! -x ".venv/bin/python" ]]; then
    err ".venv not found. Run:"
    err "  python3 -m venv .venv && .venv/bin/pip install -r requirements.txt"
    exit 1
fi
ok "Python venv found."

if [[ ! -d "frontend/node_modules" ]]; then
    log "frontend/node_modules missing — running npm install..."
    (cd frontend && npm install)
    ok "npm install done."
else
    ok "frontend/node_modules present."
fi

# ── Infrastructure ────────────────────────────────────────────────────────────
DOCKER_AVAILABLE=false
if docker info >/dev/null 2>&1; then
    DOCKER_AVAILABLE=true
fi

if $DOCKER_AVAILABLE; then
    log "Starting infrastructure containers (db, redis, qdrant)..."
    docker compose up -d db redis qdrant
    ok "Infra containers started."

    log "Waiting for Postgres to be ready..."
    until docker exec pharmawatch_db pg_isready -U pharmawatch -q 2>/dev/null; do
        echo -n "."
        sleep 1
    done
    echo ""
    ok "Postgres ready (Docker)."
else
    warn "Docker not running — skipping container startup."
    warn "Checking for locally running services..."

    # Check Postgres
    if pg_isready -h localhost -q 2>/dev/null; then
        ok "Postgres is running locally."
    else
        err "Postgres is not running. Start Docker Desktop or a local Postgres instance."
        exit 1
    fi

    # Check Redis (optional — only needed for Celery)
    REDIS_UP=false
    if python3 -c "import socket; s=socket.create_connection(('localhost',6379),1); s.close()" 2>/dev/null; then
        REDIS_UP=true
        ok "Redis is running locally."
    else
        warn "Redis is not reachable on port 6379 — Celery worker will be skipped."
        warn "Start Redis locally or via Docker to enable background tasks."
    fi
fi

# ── Migrations ────────────────────────────────────────────────────────────────
log "Running Alembic migrations..."
.venv/bin/alembic upgrade head
ok "Migrations applied."

# ── API ───────────────────────────────────────────────────────────────────────
log "Starting FastAPI on http://localhost:8000 ..."
.venv/bin/uvicorn main:app --reload --port 8000 &
API_PID=$!
ok "API started (PID $API_PID)."

# ── Celery worker (only if Redis available) ───────────────────────────────────
START_WORKER=false
if $DOCKER_AVAILABLE; then
    START_WORKER=true
elif [[ "${REDIS_UP:-false}" == "true" ]]; then
    START_WORKER=true
fi

if $START_WORKER; then
    log "Starting Celery worker..."
    .venv/bin/celery -A workers.celery_app worker --loglevel=warning --concurrency=2 &
    WORKER_PID=$!
    ok "Worker started (PID $WORKER_PID)."
else
    warn "Celery worker skipped (Redis unavailable)."
fi

# ── Frontend ──────────────────────────────────────────────────────────────────
log "Starting React dev server on http://localhost:3000 ..."
(cd frontend && npm run dev) &
FRONTEND_PID=$!
ok "Frontend started (PID $FRONTEND_PID)."

# ── Banner ────────────────────────────────────────────────────────────────────
echo ""
echo -e "${GREEN}┌─────────────────────────────────────────────────────┐${NC}"
echo -e "${GREEN}│          PharmaWatch dev stack is running            │${NC}"
echo -e "${GREEN}├─────────────────────────────────────────────────────┤${NC}"
echo -e "${GREEN}│  App      →  ${BLUE}http://localhost:3000${GREEN}                   │${NC}"
echo -e "${GREEN}│  API      →  ${BLUE}http://localhost:8000${GREEN}                   │${NC}"
echo -e "${GREEN}│  Swagger  →  ${BLUE}http://localhost:8000/docs${GREEN}              │${NC}"
echo -e "${GREEN}│                                                      │${NC}"
echo -e "${GREEN}│  Press Ctrl+C to stop all processes                  │${NC}"
echo -e "${GREEN}└─────────────────────────────────────────────────────┘${NC}"
echo ""

wait
