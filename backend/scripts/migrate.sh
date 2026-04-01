#!/usr/bin/env bash
#
# migrate.sh — Safe Alembic migration wrapper
# Kills the API server first to prevent metadata lock deadlocks,
# runs the migration, then reminds you to restart.
#
set -euo pipefail

RED="\033[0;31m"
GREEN="\033[0;32m"
YELLOW="\033[0;33m"
RESET="\033[0m"

echo -e "${YELLOW}Migration Safety Check${RESET}"
echo ""

# Check if API is running on port 8000
API_PIDS=$(lsof -ti :8000 2>/dev/null || true)
if [[ -n "$API_PIDS" ]]; then
    echo -e "  ${RED}API is running on port 8000 (PIDs: $API_PIDS)${RESET}"
    echo -e "  Migrations MUST NOT run while the API is connected."
    echo -e "  This prevents metadata lock deadlocks."
    echo ""
    read -rp "  Kill API and proceed? [y/N]: " CONFIRM
    if [[ "$CONFIRM" =~ ^[Yy] ]]; then
        echo "$API_PIDS" | xargs kill -9 2>/dev/null || true
        sleep 1
        echo -e "  ${GREEN}API killed.${RESET}"
    else
        echo "  Aborted. Stop the API first, then retry."
        exit 1
    fi
else
    echo -e "  ${GREEN}API not running — safe to migrate.${RESET}"
fi

echo ""

# Check for stale DB connections
STALE=$(docker exec lat_mysql sh -c 'echo "SELECT COUNT(*) FROM information_schema.processlist WHERE user=\"lat_user\" AND command=\"Query\" AND time > 30;" | mysql -u root -plat_root_password 2>/dev/null' 2>/dev/null | tail -1 || echo "0")
if [[ "$STALE" -gt 0 ]] 2>/dev/null; then
    echo -e "  ${RED}$STALE stale DB connections detected.${RESET}"
    echo -e "  These will block ALTER TABLE operations."
    read -rp "  Restart MySQL to clear them? [y/N]: " RESTART_DB
    if [[ "$RESTART_DB" =~ ^[Yy] ]]; then
        docker restart lat_mysql
        echo "  Waiting for MySQL to recover..."
        sleep 15
        echo -e "  ${GREEN}MySQL restarted.${RESET}"
    else
        echo -e "  ${YELLOW}Proceeding anyway — migration may hang.${RESET}"
    fi
fi

echo ""

# Activate venv and run migration
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
BACKEND_DIR="$(cd "$SCRIPT_DIR/.." && pwd)"
cd "$BACKEND_DIR"

if [[ -f .venv/bin/activate ]]; then
    source .venv/bin/activate
fi

echo "Running: alembic upgrade head"
echo ""
alembic upgrade head

echo ""
echo -e "${GREEN}Migration complete.${RESET}"
echo -e "Restart the API: ${YELLOW}source .venv/bin/activate && uvicorn app.main:app --port 8000${RESET}"
