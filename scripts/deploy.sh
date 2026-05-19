#!/bin/bash
#
# MES Edge AI System - Production Deployment Script
# Usage: ./scripts/deploy.sh [environment]
#   environment: dev (default) | staging | prod
#

set -euo pipefail

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

# Configuration
ENVIRONMENT="${1:-dev}"
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(dirname "$SCRIPT_DIR")"
COMPOSE_FILE="$PROJECT_ROOT/docker-compose.yml"
ENV_FILE="$PROJECT_ROOT/.env.local"

# Logging functions
log_info() { echo -e "${BLUE}[INFO]${NC} $1"; }
log_success() { echo -e "${GREEN}[SUCCESS]${NC} $1"; }
log_warn() { echo -e "${YELLOW}[WARN]${NC} $1"; }
log_error() { echo -e "${RED}[ERROR]${NC} $1"; }

# Check if running as root (not recommended for Docker)
check_root() {
    if [[ $EUID -eq 0 ]]; then
        log_warn "Running as root. This is not recommended for Docker operations."
        read -p "Continue anyway? (y/N) " -n 1 -r
        echo
        if [[ ! $REPLY =~ ^[Yy]$ ]]; then
            exit 1
        fi
    fi
}

# Check prerequisites
check_prerequisites() {
    log_info "Checking prerequisites..."
    
    # Check Docker
    if ! command -v docker &> /dev/null; then
        log_error "Docker is not installed. Please install Docker first."
        exit 1
    fi
    
    # Check Docker Compose
    if ! docker compose version &> /dev/null; then
        log_error "Docker Compose plugin is not installed."
        exit 1
    fi
    
    # Check if Docker daemon is running
    if ! docker info &> /dev/null; then
        log_error "Docker daemon is not running. Please start Docker first."
        exit 1
    fi
    
    log_success "Prerequisites check passed"
}

# Check environment file
check_env_file() {
    log_info "Checking environment configuration..."
    
    if [[ ! -f "$ENV_FILE" ]]; then
        log_warn ".env.local not found. Creating from template..."
        if [[ -f "$PROJECT_ROOT/.env.example" ]]; then
            cp "$PROJECT_ROOT/.env.example" "$ENV_FILE"
            log_warn "Please edit $ENV_FILE with your actual configuration values"
            log_warn "Then run this script again"
            exit 1
        else
            log_error ".env.example template not found"
            exit 1
        fi
    fi
    
    # Source the env file to check required variables
    set -a
    source "$ENV_FILE"
    set +a
    
    # Check critical secrets
    if [[ "${JWT_SECRET_KEY:-}" == "change-me-in-production" ]]; then
        log_warn "JWT_SECRET_KEY is using default value. Please change it for production!"
    fi
    
    log_success "Environment file check passed"
}

# Create required directories
create_directories() {
    log_info "Creating required directories..."
    
    mkdir -p "$PROJECT_ROOT/logs/backend"
    mkdir -p "$PROJECT_ROOT/logs/perception"
    mkdir -p "$PROJECT_ROOT/data/redis"
    mkdir -p "$PROJECT_ROOT/data/influxdb"
    mkdir -p "$PROJECT_ROOT/data/sqlite"
    
    log_success "Directories created"
}

# Pull latest images (optional)
pull_images() {
    if [[ "${PULL_IMAGES:-false}" == "true" ]]; then
        log_info "Pulling latest base images..."
        docker compose -f "$COMPOSE_FILE" pull
    fi
}

# Build images
build_images() {
    log_info "Building Docker images..."
    
    export DOCKER_BUILDKIT=1
    docker compose -f "$COMPOSE_FILE" build --parallel
    
    log_success "Images built successfully"
}

# Start services
start_services() {
    log_info "Starting services for environment: $ENVIRONMENT"
    
    # Stop existing services gracefully
    log_info "Stopping any existing services..."
    docker compose -f "$COMPOSE_FILE" down --timeout 30 || true
    
    # Start services
    docker compose -f "$COMPOSE_FILE" up -d
    
    log_success "Services started"
}

# Wait for services to be healthy
wait_for_health() {
    log_info "Waiting for services to become healthy..."
    
    local max_attempts=30
    local attempt=1
    
    while [[ $attempt -le $max_attempts ]]; do
        local all_healthy=true
        
        # Check each service
        for service in redis influxdb api perception worker frontend; do
            local status
            status=$(docker compose -f "$COMPOSE_FILE" ps "$service" --format json 2>/dev/null | grep -o '"Health":"[^"]*"' | cut -d'"' -f4 || echo "unknown")
            
            if [[ "$status" != "healthy" && "$status" != "running" ]]; then
                all_healthy=false
                log_info "Waiting for $service... (status: $status)"
            fi
        done
        
        if [[ "$all_healthy" == "true" ]]; then
            log_success "All services are healthy"
            return 0
        fi
        
        sleep 5
        ((attempt++))
    done
    
    log_error "Services failed to become healthy within timeout"
    return 1
}

# Show service status
show_status() {
    log_info "Service Status:"
    echo
    docker compose -f "$COMPOSE_FILE" ps
    echo
    
    log_info "Resource Usage:"
    docker compose -f "$COMPOSE_FILE" stats --no-stream 2>/dev/null || true
}

# Print access information
print_access_info() {
    echo
    log_success "Deployment Complete!"
    echo
    echo -e "${GREEN}Access URLs:${NC}"
    echo -e "  Frontend:    http://localhost (or your server IP)"
    echo -e "  API Docs:    http://localhost:8000/docs"
    echo -e "  InfluxDB UI: http://localhost:8086 (dev only)"
    echo
    echo -e "${GREEN}Useful Commands:${NC}"
    echo -e "  View logs:   docker compose logs -f [service]"
    echo -e "  Stop all:    docker compose down"
    echo -e "  Restart:     docker compose restart [service]"
    echo -e "  Shell:       docker compose exec [service] sh"
    echo
}

# Main deployment flow
main() {
    echo -e "${GREEN}========================================${NC}"
    echo -e "${GREEN}  MES Edge AI System Deployment${NC}"
    echo -e "${GREEN}  Environment: $ENVIRONMENT${NC}"
    echo -e "${GREEN}========================================${NC}"
    echo
    
    check_root
    check_prerequisites
    check_env_file
    create_directories
    pull_images
    build_images
    start_services
    wait_for_health
    show_status
    print_access_info
}

# Run main function
main "$@"
