#!/bin/bash
# start.sh — One-command startup script for VecQuery Intelligence on macOS
#
# This script:
#   1. Checks that Ollama is running and has the required models
#   2. Checks that the DATABASE_URL is set in backend/.env
#   3. Starts the FastAPI backend in the background
#   4. Starts the Vite frontend dev server in the background
#   5. Waits for both to be ready
#   6. Opens the browser to http://localhost:5173
#   7. Traps Ctrl+C to cleanly shut down both processes
#
# Usage:
#   chmod +x vecquery/start.sh
#   ./vecquery/start.sh

set -e  # Exit on any error

# ---------------------------------------------------------------------------
# Colors for output
# ---------------------------------------------------------------------------
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
BOLD='\033[1m'
NC='\033[0m' # No Color

# ---------------------------------------------------------------------------
# Helper functions
# ---------------------------------------------------------------------------

log_info() {
    echo -e "${BLUE}ℹ${NC}  $1"
}

log_success() {
    echo -e "${GREEN}✓${NC}  $1"
}

log_error() {
    echo -e "${RED}✗${NC}  $1"
}

log_warn() {
    echo -e "${YELLOW}⚠${NC}  $1"
}

# ---------------------------------------------------------------------------
# Pre-flight checks
# ---------------------------------------------------------------------------

echo ""
echo -e "${BOLD}VecQuery Intelligence — Startup${NC}"
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo ""

log_info "Running pre-flight checks..."
echo ""

# Check 1: Ollama running
log_info "Checking Ollama..."
if ! curl -s http://localhost:11434/api/tags > /dev/null 2>&1; then
    log_error "Ollama is not running"
    echo ""
    echo "  Start Ollama with:"
    echo "    ${BOLD}ollama serve${NC}"
    echo ""
    exit 1
fi
log_success "Ollama is running"

# Check 2: Required models
log_info "Checking Ollama models..."
MODELS=$(curl -s http://localhost:11434/api/tags | grep -o '"name":"[^"]*"' | cut -d'"' -f4)

if ! echo "$MODELS" | grep -q "nomic-embed-text"; then
    log_error "nomic-embed-text model not found"
    echo ""
    echo "  Pull it with:"
    echo "    ${BOLD}ollama pull nomic-embed-text${NC}"
    echo ""
    exit 1
fi
log_success "nomic-embed-text model found"

if ! echo "$MODELS" | grep -q "llama3.1"; then
    log_error "llama3.1:8b model not found"
    echo ""
    echo "  Pull it with:"
    echo "    ${BOLD}ollama pull llama3.1:8b${NC}"
    echo ""
    exit 1
fi
log_success "llama3.1:8b model found"

# Check 3: DATABASE_URL in .env
log_info "Checking DATABASE_URL..."
if [ ! -f "vecquery/backend/.env" ]; then
    log_error "vecquery/backend/.env not found"
    echo ""
    echo "  Create it with:"
    echo "    ${BOLD}echo 'DATABASE_URL=postgresql://...' > vecquery/backend/.env${NC}"
    echo ""
    exit 1
fi

if ! grep -q "^DATABASE_URL=" vecquery/backend/.env; then
    log_error "DATABASE_URL not set in vecquery/backend/.env"
    echo ""
    echo "  Add your Supabase connection string:"
    echo "    ${BOLD}DATABASE_URL=postgresql://postgres:[PASSWORD]@db.[PROJECT].supabase.co:5432/postgres${NC}"
    echo ""
    exit 1
fi
log_success "DATABASE_URL is set"

# Check 4: Python venv exists
log_info "Checking Python virtual environment..."
if [ ! -d "vecquery/backend/venv" ]; then
    log_error "Python venv not found at vecquery/backend/venv"
    echo ""
    echo "  Create it with:"
    echo "    ${BOLD}python3 -m venv vecquery/backend/venv${NC}"
    echo "    ${BOLD}vecquery/backend/venv/bin/pip install -r vecquery/backend/requirements.txt${NC}"
    echo ""
    exit 1
fi
log_success "Python venv found"

# Check 5: Node modules installed
log_info "Checking Node modules..."
if [ ! -d "vecquery/frontend/node_modules" ]; then
    log_warn "Node modules not found — installing now..."
    cd vecquery/frontend
    npm install
    cd ../..
fi
log_success "Node modules ready"

echo ""
log_success "All pre-flight checks passed"
echo ""

# ---------------------------------------------------------------------------
# Start services
# ---------------------------------------------------------------------------

# Trap Ctrl+C to kill background processes
trap 'echo ""; log_info "Shutting down..."; kill $BACKEND_PID $FRONTEND_PID 2>/dev/null; exit 0' INT TERM

log_info "Starting FastAPI backend on port 8000..."
vecquery/backend/venv/bin/uvicorn main:app --host 0.0.0.0 --port 8000 --app-dir vecquery/backend > /tmp/vecquery-backend.log 2>&1 &
BACKEND_PID=$!

# Wait for backend to be ready
for i in {1..30}; do
    if curl -s http://localhost:8000/ > /dev/null 2>&1; then
        log_success "Backend ready at http://localhost:8000"
        break
    fi
    if [ $i -eq 30 ]; then
        log_error "Backend failed to start after 30 seconds"
        echo ""
        echo "  Check logs:"
        echo "    ${BOLD}tail -f /tmp/vecquery-backend.log${NC}"
        echo ""
        kill $BACKEND_PID 2>/dev/null
        exit 1
    fi
    sleep 1
done

log_info "Starting Vite frontend on port 5173..."
cd vecquery/frontend
npm run dev > /tmp/vecquery-frontend.log 2>&1 &
FRONTEND_PID=$!
cd ../..

# Wait for frontend to be ready
for i in {1..30}; do
    if curl -s http://localhost:5173/ > /dev/null 2>&1; then
        log_success "Frontend ready at http://localhost:5173"
        break
    fi
    if [ $i -eq 30 ]; then
        log_error "Frontend failed to start after 30 seconds"
        echo ""
        echo "  Check logs:"
        echo "    ${BOLD}tail -f /tmp/vecquery-frontend.log${NC}"
        echo ""
        kill $BACKEND_PID $FRONTEND_PID 2>/dev/null
        exit 1
    fi
    sleep 1
done

echo ""
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo -e "${GREEN}${BOLD}✓ VecQuery Intelligence is running${NC}"
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo ""
echo "  Frontend:  ${BOLD}http://localhost:5173${NC}"
echo "  Backend:   ${BOLD}http://localhost:8000${NC}"
echo "  API Docs:  ${BOLD}http://localhost:8000/docs${NC}"
echo ""
echo "  Backend logs:  ${BOLD}tail -f /tmp/vecquery-backend.log${NC}"
echo "  Frontend logs: ${BOLD}tail -f /tmp/vecquery-frontend.log${NC}"
echo ""
echo "  Press ${BOLD}Ctrl+C${NC} to stop both servers"
echo ""

# Open browser (macOS only)
sleep 2
open http://localhost:5173 2>/dev/null || true

# Wait for Ctrl+C
wait
