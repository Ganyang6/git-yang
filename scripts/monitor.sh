#!/bin/bash
#
# MES Edge AI System - Monitoring Dashboard
# Usage: ./scripts/monitor.sh
#   Interactive monitoring dashboard for system metrics
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
CYAN='\033[0;36m'
NC='\033[0m'

# Clear screen and move cursor to top
clear_screen() {
    printf "\033[2J\033[H"
}

# Print header
print_header() {
    echo -e "${CYAN}╔════════════════════════════════════════════════════════════════╗${NC}"
    echo -e "${CYAN}║${NC}          ${GREEN}MES Edge AI System - Monitoring Dashboard${NC}           ${CYAN}║${NC}"
    echo -e "${CYAN}╚════════════════════════════════════════════════════════════════╝${NC}"
    echo
}

# Print service status
print_services() {
    echo -e "${BLUE}┌─ Service Status ─────────────────────────────────────────────┐${NC}"
    
    local services=("redis" "influxdb" "api" "perception" "worker" "frontend")
    
    for service in "${services[@]}"; do
        local status health
        status=$(docker compose -f "$COMPOSE_FILE" ps "$service" --format "table {{.Status}}" 2>/dev/null | tail -n +2 | tr -d ' ' || echo "stopped")
        
        # Determine color based on status
        local color="$RED"
        if [[ "$status" == *"Up"* && "$status" == *"healthy"* ]]; then
            color="$GREEN"
        elif [[ "$status" == *"Up"* ]]; then
            color="$YELLOW"
        fi
        
        printf "${BLUE}│${NC}  %-12s ${color}%-40s${NC}${BLUE}│${NC}\n" "$service:" "$status"
    done
    
    echo -e "${BLUE}└──────────────────────────────────────────────────────────────┘${NC}"
    echo
}

# Print resource usage
print_resources() {
    echo -e "${BLUE}┌─ Resource Usage ─────────────────────────────────────────────┐${NC}"
    
    # Container stats
    local stats
    stats=$(docker compose -f "$COMPOSE_FILE" stats --no-stream --format "table {{.Name}}\t{{.CPUPerc}}\t{{.MemUsage}}" 2>/dev/null | tail -n +2 || true)
    
    if [[ -n "$stats" ]]; then
        while IFS=$'\t' read -r name cpu mem; do
            printf "${BLUE}│${NC}  %-15s CPU: %-8s MEM: %-20s${BLUE}│${NC}\n" "$name" "$cpu" "$mem"
        done <<< "$stats"
    else
        echo -e "${BLUE}│${NC}  No container stats available                              ${BLUE}│${NC}"
    fi
    
    echo -e "${BLUE}└──────────────────────────────────────────────────────────────┘${NC}"
    echo
}

# Print system metrics
print_system() {
    echo -e "${BLUE}┌─ System Metrics ─────────────────────────────────────────────┐${NC}"
    
    # Load average
    local load
    load=$(uptime | awk -F'load average:' '{print $2}' | xargs)
    printf "${BLUE}│${NC}  Load Average: %-46s${BLUE}│${NC}\n" "$load"
    
    # Memory
    local mem_info
    mem_info=$(free -h 2>/dev/null | awk 'NR==2{printf "%s/%s (%.1f%%)", $3,$2,$3*100/$2}' || echo "N/A")
    printf "${BLUE}│${NC}  Memory:       %-46s${BLUE}│${NC}\n" "$mem_info"
    
    # Disk
    local disk_info
    disk_info=$(df -h "$PROJECT_ROOT" 2>/dev/null | tail -1 | awk '{printf "%s/%s (%s)", $3,$2,$5}' || echo "N/A")
    printf "${BLUE}│${NC}  Disk:         %-46s${BLUE}│${NC}\n" "$disk_info"
    
    echo -e "${BLUE}└──────────────────────────────────────────────────────────────┘${NC}"
    echo
}

# Print recent logs summary
print_logs() {
    echo -e "${BLUE}┌─ Recent Errors (last 5 min) ─────────────────────────────────┐${NC}"
    
    local errors
    errors=$(docker compose -f "$COMPOSE_FILE" logs --since 5m --no-color 2>/dev/null | grep -i "error\|exception\|fatal" | tail -5 || true)
    
    if [[ -n "$errors" ]]; then
        while IFS= read -r line; do
            # Truncate long lines
            if [[ ${#line} -gt 60 ]]; then
                line="${line:0:57}..."
            fi
            printf "${BLUE}│${NC}  ${RED}%-58s${NC}${BLUE}│${NC}\n" "$line"
        done <<< "$errors"
    else
        echo -e "${BLUE}│${NC}  ${GREEN}No errors found in the last 5 minutes${NC}                    ${BLUE}│${NC}"
    fi
    
    echo -e "${BLUE}└──────────────────────────────────────────────────────────────┘${NC}"
    echo
}

# Print API metrics (if available)
print_api_metrics() {
    echo -e "${BLUE}┌─ API Health ─────────────────────────────────────────────────┐${NC}"
    
    local api_status="unknown"
    if curl -sf http://localhost:8000/health &> /dev/null; then
        api_status="${GREEN}healthy${NC}"
    elif curl -sf http://localhost:8000/ &> /dev/null; then
        api_status="${YELLOW}responding${NC}"
    else
        api_status="${RED}unreachable${NC}"
    fi
    
    printf "${BLUE}│${NC}  API Status: %-50b${BLUE}│${NC}\n" "$api_status"
    
    # Try to get some basic stats
    local response_time
    response_time=$(curl -sf -o /dev/null -w "%{time_total}" http://localhost:8000/ 2>/dev/null || echo "N/A")
    if [[ "$response_time" != "N/A" ]]; then
        printf "${BLUE}│${NC}  Response Time: %.3fs%-43s${BLUE}│${NC}\n" "$response_time" ""
    fi
    
    echo -e "${BLUE}└──────────────────────────────────────────────────────────────┘${NC}"
    echo
}

# Print footer with commands
print_footer() {
    echo -e "${CYAN}Commands: [r]efresh [l]ogs [s]hell [q]uit${NC}"
    echo -e "${YELLOW}Press any key to refresh (Ctrl+C to exit)...${NC}"
}

# Handle user input
handle_input() {
    local key
    IFS= read -rs -t 5 -n 1 key || true
    
    case "$key" in
        q|Q)
            echo
            echo -e "${GREEN}Exiting monitor...${NC}"
            exit 0
            ;;
        r|R|'')
            # Refresh
            ;;
        l|L)
            # Show logs
            clear_screen
            echo -e "${BLUE}Showing logs (press 'q' to return)...${NC}"
            docker compose -f "$COMPOSE_FILE" logs -f --tail 100
            ;;
        s|S)
            # Open shell menu
            clear_screen
            echo -e "${BLUE}Select service to shell into:${NC}"
            echo "  1) api"
            echo "  2) perception"
            echo "  3) redis"
            echo "  4) influxdb"
            echo "  q) Cancel"
            echo
            read -rs -n 1 choice
            case "$choice" in
                1) docker compose -f "$COMPOSE_FILE" exec api sh ;;
                2) docker compose -f "$COMPOSE_FILE" exec perception sh ;;
                3) docker compose -f "$COMPOSE_FILE" exec redis sh ;;
                4) docker compose -f "$COMPOSE_FILE" exec influxdb bash ;;
            esac
            ;;
    esac
}

# Main loop
main() {
    # Check if docker compose is running
    if ! docker compose -f "$COMPOSE_FILE" ps &> /dev/null; then
        echo -e "${RED}Error: Docker Compose is not running${NC}"
        echo "Start the system first with: docker compose up -d"
        exit 1
    fi
    
    # Hide cursor
    printf "\033[?25l"
    
    # Cleanup on exit
    trap 'printf "\033[?25h"; clear_screen; exit 0' INT TERM EXIT
    
    while true; do
        clear_screen
        print_header
        print_services
        print_resources
        print_system
        print_api_metrics
        print_logs
        print_footer
        
        handle_input
    done
}

main "$@"
