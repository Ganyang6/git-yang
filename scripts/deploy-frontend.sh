#!/bin/bash
# deploy-frontend.sh — Safe frontend deployment: clean old files first, then copy
#
# Usage:
#   ./scripts/deploy-frontend.sh              # build + deploy to running container
#   ./scripts/deploy-frontend.sh --no-build    # skip npm build, just copy dist
#
# Prevents 404 errors from stale assets being served alongside new HTML.

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
PROJECT_DIR="$(cd "$SCRIPT_DIR/.." && pwd)"
FRONTEND_DIR="$PROJECT_DIR/mes-frontend"
CONTAINER="${MES_FRONTEND_CONTAINER:-mes-frontend}"
NGINX_HTML="/usr/share/nginx/html"

SKIP_BUILD=false
if [ "${1:-}" = "--no-build" ]; then
    SKIP_BUILD=true
fi

echo "=== Deploy Frontend ==="

# 1. Build
if [ "$SKIP_BUILD" = false ]; then
    echo "[1/4] Building frontend..."
    cd "$FRONTEND_DIR"
    npm run build
else
    echo "[1/4] Skipping build (--no-build)"
fi

# 2. Wipe old assets inside container
echo "[2/4] Cleaning old files in container..."
docker exec "$CONTAINER" rm -rf "$NGINX_HTML/assets/" 2>/dev/null || true
docker exec "$CONTAINER" rm -f "$NGINX_HTML/index.html" 2>/dev/null || true

# 3. Copy fresh build
echo "[3/4] Copying new build..."
docker cp "$FRONTEND_DIR/dist/." "$CONTAINER:$NGINX_HTML/"

# 4. Verify
echo "[4/4] Verifying..."
HTTP_CODE=$(docker exec "$CONTAINER" curl -s -o /dev/null -w "%{http_code}" http://localhost 2>/dev/null || \
            curl -s -o /dev/null -w "%{http_code}" http://localhost 2>/dev/null || echo "FAIL")
echo "HTTP status: $HTTP_CODE"

if [ "$HTTP_CODE" = "200" ] || [ "$HTTP_CODE" = "302" ] || [ "$HTTP_CODE" = "301" ]; then
    echo "=== Deploy OK (HTTP $HTTP_CODE) ==="
else
    echo "=== WARNING: Unexpected HTTP status $HTTP_CODE ===" >&2
fi
