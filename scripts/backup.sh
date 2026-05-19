#!/bin/bash
#
# MES Edge AI System - Backup Script
# Usage: ./scripts/backup.sh [backup_dir]
#   backup_dir: optional, defaults to ./backups/YYYYMMDD_HHMMSS
#

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(dirname "$SCRIPT_DIR")"
COMPOSE_FILE="$PROJECT_ROOT/docker-compose.yml"

# Configuration
BACKUP_BASE_DIR="${1:-$PROJECT_ROOT/backups}"
TIMESTAMP=$(date +%Y%m%d_%H%M%S)
BACKUP_DIR="$BACKUP_BASE_DIR/backup_$TIMESTAMP"
RETENTION_DAYS=30

# Colors
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m'

log_info() { echo -e "${BLUE}[INFO]${NC} $1"; }
log_success() { echo -e "${GREEN}[SUCCESS]${NC} $1"; }
log_warn() { echo -e "${YELLOW}[WARN]${NC} $1"; }
log_error() { echo -e "${RED}[ERROR]${NC} $1"; }

# Create backup directory
setup_backup_dir() {
    mkdir -p "$BACKUP_DIR"
    log_info "Backup directory: $BACKUP_DIR"
}

# Backup SQLite database
backup_sqlite() {
    log_info "Backing up SQLite database..."
    
    local db_container="api"
    local db_path="/app/data/mes.db"
    local backup_file="$BACKUP_DIR/mes.db"
    
    # Check if container is running
    if docker compose -f "$COMPOSE_FILE" ps "$db_container" &> /dev/null; then
        # Copy database from container
        docker compose -f "$COMPOSE_FILE" cp "$db_container:$db_path" "$backup_file"
        
        # Verify backup
        if [[ -f "$backup_file" ]]; then
            local size
            size=$(du -h "$backup_file" | cut -f1)
            log_success "SQLite backup completed: $size"
        else
            log_error "SQLite backup failed"
            return 1
        fi
    else
        # Container not running, try to backup from volume directly
        local volume_path="$PROJECT_ROOT/data/sqlite/mes.db"
        if [[ -f "$volume_path" ]]; then
            cp "$volume_path" "$backup_file"
            log_success "SQLite backup completed from volume"
        else
            log_warn "SQLite database not found, skipping"
        fi
    fi
}

# Backup Redis data
backup_redis() {
    log_info "Backing up Redis data..."
    
    local backup_file="$BACKUP_DIR/redis.rdb"
    
    # Trigger BGSAVE and wait
    if docker compose -f "$COMPOSE_FILE" exec -T redis redis-cli BGSAVE &> /dev/null; then
        sleep 2
        
        # Copy RDB file
        docker compose -f "$COMPOSE_FILE" cp "redis:/data/dump.rdb" "$backup_file" 2>/dev/null || true
        
        if [[ -f "$backup_file" ]]; then
            log_success "Redis backup completed"
        else
            log_warn "Redis backup may have failed (RDB file not found)"
        fi
    else
        log_warn "Redis backup skipped (container not running)"
    fi
}

# Backup InfluxDB
backup_influxdb() {
    log_info "Backing up InfluxDB data..."
    
    local backup_dir="$BACKUP_DIR/influxdb"
    mkdir -p "$backup_dir"
    
    # InfluxDB 2.x backup command
    if docker compose -f "$COMPOSE_FILE" exec -T influxdb influx backup \
        --bucket metrics \
        --token "${INFLUXDB_TOKEN:-}" \
        "/backup" 2>/dev/null; then
        
        docker compose -f "$COMPOSE_FILE" cp "influxdb:/backup" "$backup_dir"
        log_success "InfluxDB backup completed"
    else
        # Fallback: backup volume directly
        local volume_path="$PROJECT_ROOT/data/influxdb"
        if [[ -d "$volume_path" ]]; then
            tar czf "$backup_dir/influxdb_volume.tar.gz" -C "$volume_path" .
            log_success "InfluxDB backup completed from volume"
        else
            log_warn "InfluxDB backup skipped (not available)"
        fi
    fi
}

# Backup configuration files
backup_configs() {
    log_info "Backing up configuration files..."
    
    local config_dir="$BACKUP_DIR/configs"
    mkdir -p "$config_dir"
    
    # Backup config files
    cp "$PROJECT_ROOT/.env.local" "$config_dir/" 2>/dev/null || log_warn ".env.local not found"
    cp "$PROJECT_ROOT/mes-backend/config.yaml" "$config_dir/" 2>/dev/null || true
    cp "$PROJECT_ROOT/docker-compose.yml" "$config_dir/" 2>/dev/null || true
    
    # Backup nginx config
    if [[ -d "$PROJECT_ROOT/docker" ]]; then
        cp -r "$PROJECT_ROOT/docker" "$config_dir/" 2>/dev/null || true
    fi
    
    log_success "Configuration backup completed"
}

# Create backup manifest
create_manifest() {
    local manifest="$BACKUP_DIR/MANIFEST.txt"
    
    cat > "$manifest" << EOF
MES Edge AI System Backup
==========================
Timestamp: $(date -Iseconds)
Hostname: $(hostname)
Backup Directory: $BACKUP_DIR

Contents:
EOF
    
    find "$BACKUP_DIR" -type f -exec ls -lh {} \; >> "$manifest"
    
    log_info "Backup manifest created"
}

# Compress backup
compress_backup() {
    log_info "Compressing backup..."
    
    local archive="$BACKUP_DIR.tar.gz"
    
    tar czf "$archive" -C "$BACKUP_BASE_DIR" "backup_$TIMESTAMP"
    
    # Remove uncompressed directory
    rm -rf "$BACKUP_DIR"
    
    local size
    size=$(du -h "$archive" | cut -f1)
    log_success "Backup compressed: $archive ($size)"
}

# Cleanup old backups
cleanup_old_backups() {
    log_info "Cleaning up backups older than $RETENTION_DAYS days..."
    
    local count=0
    while IFS= read -r file; do
        rm -f "$file"
        ((count++))
    done < <(find "$BACKUP_BASE_DIR" -name "backup_*.tar.gz" -mtime +$RETENTION_DAYS 2>/dev/null)
    
    if [[ $count -gt 0 ]]; then
        log_info "Removed $count old backup(s)"
    else
        log_info "No old backups to remove"
    fi
}

# Main backup flow
main() {
    echo -e "${GREEN}========================================${NC}"
    echo -e "${GREEN}  MES System Backup${NC}"
    echo -e "${GREEN}========================================${NC}"
    echo
    
    setup_backup_dir
    backup_configs
    backup_sqlite
    backup_redis
    backup_influxdb
    create_manifest
    compress_backup
    cleanup_old_backups
    
    echo
    echo -e "${GREEN}========================================${NC}"
    echo -e "${GREEN}  Backup completed successfully!${NC}"
    echo -e "${GREEN}========================================${NC}"
}

main "$@"
