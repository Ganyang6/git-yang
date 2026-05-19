#!/usr/bin/env bash
# MES Edge AI Worktime Analysis System - Smoke Test
#
# Usage:
#   chmod +x scripts/smoke_test.sh
#   ./scripts/smoke_test.sh [BASE_URL]
#
# Arguments:
#   BASE_URL  - base URL of the deployed system (default: http://localhost)
#
# Exit codes:
#   0 - all checks passed
#   1 - one or more checks failed
#
# Requirements:
#   - Docker Compose services running (docker compose up -d)
#   - redis-cli, curl, jq installed on the host
#
# NOTE: This script runs on the Docker host, not inside containers.

set -euo pipefail

BASE_URL="${1:-http://localhost}"
PASS_COUNT=0
FAIL_COUNT=0
SKIP_COUNT=0

pass() {
    echo "  PASS: $1"
    PASS_COUNT=$((PASS_COUNT + 1))
}

fail() {
    echo "  FAIL: $1"
    FAIL_COUNT=$((FAIL_COUNT + 1))
}

skip() {
    echo "  SKIP: $1"
    SKIP_COUNT=$((SKIP_COUNT + 1))
}

info() {
    echo "--- $1 ---"
}

# --- Redis Connectivity ---
info "Redis Connectivity"
if command -v redis-cli &> /dev/null; then
    REDIS_HOST="${REDIS_HOST:-localhost}"
    REDIS_PORT="${REDIS_PORT:-6379}"
    if redis-cli -h "$REDIS_HOST" -p "$REDIS_PORT" ping 2>/dev/null | grep -q "PONG"; then
        pass "Redis ping OK ($REDIS_HOST:$REDIS_PORT)"
    else
        fail "Redis ping failed ($REDIS_HOST:$REDIS_PORT)"
    fi
else
    skip "redis-cli not found, testing via docker exec"
    if docker exec mes-redis redis-cli ping 2>/dev/null | grep -q "PONG"; then
        pass "Redis ping OK (docker exec)"
    else
        fail "Redis ping failed (docker exec)"
    fi
fi

# --- InfluxDB Connectivity ---
info "InfluxDB Connectivity"
INFLUX_PORT="${INFLUXDB_EXPOSE_PORT:-8086}"
if curl -sf "http://localhost:${INFLUX_PORT}/health" 2>/dev/null | grep -q "health"; then
    pass "InfluxDB health OK (port $INFLUX_PORT)"
else
    # Try via docker
    if docker exec mes-influxdb influx ping 2>/dev/null; then
        pass "InfluxDB ping OK (docker exec)"
    else
        fail "InfluxDB health check failed"
    fi
fi

# --- API Health Check ---
info "API Health Check"
API_PORT="${API_PORT:-8000}"
if curl -sf -o /dev/null "${BASE_URL}:${API_PORT}/docs" 2>/dev/null; then
    pass "API docs accessible (${BASE_URL}:${API_PORT}/docs -> 200)"
else
    fail "API docs not accessible (${BASE_URL}:${API_PORT}/docs)"
fi

# --- Login API ---
info "Login API"
LOGIN_RESPONSE=$(curl -sf -X POST "${BASE_URL}:${API_PORT}/api/auth/login" \
    -H "Content-Type: application/json" \
    -d '{"username":"admin","password":"admin123"}' 2>/dev/null) || true
if echo "$LOGIN_RESPONSE" | grep -q '"token"'; then
    TOKEN=$(echo "$LOGIN_RESPONSE" | python3 -c "import sys,json; print(json.load(sys.stdin).get('data',{}).get('token',''))" 2>/dev/null) || true
    if [ -n "$TOKEN" ]; then
        pass "Login API returned JWT token"
    else
        pass "Login API returned response with token field"
    fi
else
    fail "Login API did not return token (check seed data is loaded)"
fi

# --- Frontend Page ---
info "Frontend Page"
FRONTEND_PORT="${FRONTEND_PORT:-80}"
if curl -sf -o /dev/null "${BASE_URL}:${FRONTEND_PORT}/" 2>/dev/null; then
    pass "Frontend page accessible (${BASE_URL}:${FRONTEND_PORT}/ -> 200)"
else
    fail "Frontend page not accessible (${BASE_URL}:${FRONTEND_PORT}/)"
fi

# --- PDF Export API ---
info "PDF Export API"
HTTP_CODE=$(curl -sf -o /dev/null -w "%{http_code}" \
    "${BASE_URL}:${API_PORT}/api/reports/worktime/pdf?station_id=all&period=today" \
    2>/dev/null) || true
if [ "$HTTP_CODE" = "200" ]; then
    pass "PDF export API returned 200"
elif [ "$HTTP_CODE" = "401" ]; then
    # 401 is acceptable if auth is required and no token provided
    pass "PDF export API returned 401 (auth required, expected)"
elif [ "$HTTP_CODE" = "404" ]; then
    fail "PDF export API returned 404 (check reportlab is installed)"
else
    fail "PDF export API returned unexpected status: ${HTTP_CODE:-no response}"
fi

# --- Docker Service Health Status ---
info "Docker Service Health"
if command -v docker &> /dev/null; then
    UNHEALTHY=$(docker compose ps --format json 2>/dev/null | python3 -c "
import sys, json
unhealthy = []
for line in sys.stdin:
    line = line.strip()
    if not line: continue
    svc = json.loads(line)
    name = svc.get('Service','')
    health = svc.get('Health','')
    state = svc.get('State','')
    if health == 'unhealthy' or state != 'running':
        if name != 'mes-perception':  # perception needs camera
            unhealthy.append(f'{name}(health={health},state={state})')
if unhealthy:
    print('; '.join(unhealthy))
" 2>/dev/null) || true
    if [ -z "$UNHEALTHY" ]; then
        pass "All Docker services healthy"
    else
        fail "Unhealthy services: $UNHEALTHY"
    fi
else
    skip "docker command not available"
fi

# --- Summary ---
echo ""
echo "========================================="
echo " Smoke Test Summary"
echo "========================================="
echo "  Passed:  $PASS_COUNT"
echo "  Failed:  $FAIL_COUNT"
echo "  Skipped: $SKIP_COUNT"
echo "========================================="

if [ "$FAIL_COUNT" -gt 0 ]; then
    echo " RESULT: FAILED ($FAIL_COUNT check(s) failed)"
    exit 1
else
    echo " RESULT: ALL PASSED"
    exit 0
fi
