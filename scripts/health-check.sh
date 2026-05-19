#!/bin/bash
#
# MES Edge AI System - Health Check Script
# Usage: ./scripts/health-check.sh
#   Returns exit code 0 if all healthy, 1 otherwise
#

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(dirname "$SCRIPT_DIR")"
COMPOSE_FILE="$PROJECT_ROOT/docker-compose.yml"

# Colors
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m'

log_info() { echo -e "${BLUE}[INFO]${NC} $1"; }
log_success() { echo -e "${GREEN}[OK]${NC} $1"; }
log_warn() { echo -e "${YELLOW}[WARN]${NC} $1"; }
log_error() { echo -e "${RED}[FAIL]${NC} $1"; }

# Check if docker compose is running
check_compose_running() {
    if ! docker compose -f "$COMPOSE_FILE" ps &> /dev/null; then
        log_error "Docker Compose is not running"
        return 1
    fi
    return 0
}

# Check individual service health
check_service_health() {
    local service=$1
    local status
    
    status=$(docker compose -f "$COMPOSE_FILE" ps "$service" --format json 2>/dev/null | grep -o '"Health":"[^"]*"' | cut -d'"' -f4 || echo "unknown")
    
    case "$status" in
        "healthy")
            log_success "$service is healthy"
            return 0
            ;;
        "running")
            log_warn "$service is running (no health check defined)"
            return 0
            ;;
        "unhealthy")
            log_error "$service is unhealthy"
            return 1
            ;;
        "starting")
            log_warn "$service is still starting"
            return 1
            ;;
        *)
            log_error "$service status: $status"
            return 1
            ;;
    esac
}

# Check API endpoint
check_api_endpoint() {
    local url="${API_URL:-http://localhost:8000}"
    
    if curl -sf "$url/health" &> /dev/null || curl -sf "$url/" &> /dev/null; then
        log_success "API endpoint is responding"
        return 0
    else
        log_error "API endpoint is not responding"
        return 1
    fi
}

# Check Redis connectivity
check_redis() {
    if docker compose -f "$COMPOSE_FILE" exec -T redis redis-cli ping 2>/dev/null | grep -q "PONG"; then
        log_success "Redis is responding"
        return 0
    else
        log_error "Redis is not responding"
        return 1
    fi
}

# Check InfluxDB
check_influxdb() {
    if docker compose -f "$COMPOSE_FILE" exec -T influxdb influx ping 2>/dev/null | grep -q "OK"; then
        log_success "InfluxDB is responding"
        return 0
    else
        log_error "InfluxDB is not responding"
        return 1
    fi
}

# Check disk space
check_disk_space() {
    local threshold=90
    local usage
    
    usage=$(df "$PROJECT_ROOT" | tail -1 | awk '{print $5}' | sed 's/%//')
    
    if [[ $usage -lt $threshold ]]; then
        log_success "Disk usage: ${usage}% (threshold: ${threshold}%)"
        return 0
    else
        log_error "Disk usage critical: ${usage}% (threshold: ${threshold}%)"
        return 1
    fi
}

# Check memory usage
check_memory() {
    local mem_info
    mem_info=$(free -m 2>/dev/null | awk 'NR==2{printf "%.1f", $3*100/$2}')
    
    if [[ -n "$mem_info" ]]; then
        log_info "Memory usage: ${mem_info}%"
    fi
    return 0
}

# Main health check
main() {
    echo -e "${BLUE}========================================${NC}"
    echo -e "${BLUE}  MES System Health Check${NC}"
    echo -e "${BLUE}========================================${NC}"
    echo
    
    local overall_status=0
    
    # Check if compose is running
    if ! check_compose_running; then
        exit 1
    fi
    
    echo -e "${BLUE}--- Service Health ---${NC}"
    for service in redis influxdb api perception worker frontend; do
        if ! check_service_health "$service"; then
            overall_status=1
        fi
    done
    echo
    
    echo -e "${BLUE}--- Endpoint Checks ---${NC}"
    if ! check_api_endpoint; then
        overall_status=1
    fi
    
    if ! check_redis; then
        overall_status=1
    fi
    
    if ! check_influxdb; then
        overall_status=1
    fi
    echo
    
    echo -e "${BLUE}--- System Resources ---${NC}"
    check_disk_space || overall_status=1
    check_memory
    echo
    
    # Summary
    echo -e "${BLUE}========================================${NC}"
    if [[ $overall_status -eq 0 ]]; then
        echo -e "${GREEN}  All checks passed!${NC}"
    else
        echo -e "${RED}  Some checks failed!${NC}"
    fi
    echo -e "${BLUE}========================================${NC}"
    
    exit $overall_status
}

main "$@"
