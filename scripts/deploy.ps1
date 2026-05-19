# MES Edge AI System - Production Deployment Script (PowerShell)
# Usage: .\scripts\deploy.ps1 [-Environment dev|staging|prod]
#

param(
    [string]$Environment = "dev"
)

$ErrorActionPreference = "Stop"

# Configuration
$ScriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$ProjectRoot = Split-Path -Parent $ScriptDir
$ComposeFile = Join-Path $ProjectRoot "docker-compose.yml"
$EnvFile = Join-Path $ProjectRoot ".env.local"

# Colors
$Red = "`e[31m"
$Green = "`e[32m"
$Yellow = "`e[33m"
$Blue = "`e[34m"
$NC = "`e[0m"

function Write-Info { param($Message) Write-Host "${Blue}[INFO]${NC} $Message" }
function Write-Success { param($Message) Write-Host "${Green}[SUCCESS]${NC} $Message" }
function Write-Warn { param($Message) Write-Host "${Yellow}[WARN]${NC} $Message" }
function Write-LogError { param($Message) Write-Host "${Red}[ERROR]${NC} $Message" }

# Check prerequisites
function Test-Prerequisites {
    Write-Info "Checking prerequisites..."
    
    # Check Docker
    if (-not (Get-Command docker -ErrorAction SilentlyContinue)) {
        Write-LogError "Docker is not installed. Please install Docker first."
        exit 1
    }
    
    # Check Docker Compose
    try {
        docker compose version | Out-Null
    } catch {
        Write-LogError "Docker Compose plugin is not installed."
        exit 1
    }
    
    # Check if Docker daemon is running
    try {
        docker info | Out-Null
    } catch {
        Write-LogError "Docker daemon is not running. Please start Docker first."
        exit 1
    }
    
    Write-Success "Prerequisites check passed"
}

# Check environment file
function Test-EnvFile {
    Write-Info "Checking environment configuration..."
    
    if (-not (Test-Path $EnvFile)) {
        Write-Warn ".env.local not found. Creating from template..."
        $TemplateFile = Join-Path $ProjectRoot ".env.example"
        if (Test-Path $TemplateFile) {
            Copy-Item $TemplateFile $EnvFile
            Write-Warn "Please edit $EnvFile with your actual configuration values"
            Write-Warn "Then run this script again"
            exit 1
        } else {
            Write-LogError ".env.example template not found"
            exit 1
        }
    }
    
    # Load and check JWT secret
    $envContent = Get-Content $EnvFile -Raw
    if ($envContent -match "JWT_SECRET_KEY=change-me-in-production") {
        Write-Warn "JWT_SECRET_KEY is using default value. Please change it for production!"
    }
    
    Write-Success "Environment file check passed"
}

# Create required directories
function New-RequiredDirectories {
    Write-Info "Creating required directories..."
    
    @(
        (Join-Path $ProjectRoot "logs\backend"),
        (Join-Path $ProjectRoot "logs\perception"),
        (Join-Path $ProjectRoot "data\redis"),
        (Join-Path $ProjectRoot "data\influxdb"),
        (Join-Path $ProjectRoot "data\sqlite")
    ) | ForEach-Object {
        New-Item -ItemType Directory -Force -Path $_ | Out-Null
    }
    
    Write-Success "Directories created"
}

# Build images
function Build-Images {
    Write-Info "Building Docker images..."
    
    $env:DOCKER_BUILDKIT = "1"
    docker compose -f $ComposeFile build --parallel
    
    Write-Success "Images built successfully"
}

# Start services
function Start-Services {
    Write-Info "Starting services for environment: $Environment"
    
    # Stop existing services
    Write-Info "Stopping any existing services..."
    docker compose -f $ComposeFile down --timeout 30 2>$null
    
    # Start services
    docker compose -f $ComposeFile up -d
    
    Write-Success "Services started"
}

# Wait for services to be healthy
function Wait-ForHealth {
    Write-Info "Waiting for services to become healthy..."
    
    $maxAttempts = 30
    $attempt = 1
    $services = @("redis", "influxdb", "api", "perception", "worker", "frontend")
    
    while ($attempt -le $maxAttempts) {
        $allHealthy = $true
        
        foreach ($service in $services) {
            $status = docker compose -f $ComposeFile ps $service --format json 2>$null | 
                ConvertFrom-Json | Select-Object -ExpandProperty Health -ErrorAction SilentlyContinue
            
            if ($status -ne "healthy" -and $status -ne "running") {
                $allHealthy = $false
                Write-Info "Waiting for $service... (status: $status)"
            }
        }
        
        if ($allHealthy) {
            Write-Success "All services are healthy"
            return
        }
        
        Start-Sleep -Seconds 5
        $attempt++
    }
    
    Write-LogError "Services failed to become healthy within timeout"
    exit 1
}

# Show service status
function Show-Status {
    Write-Info "Service Status:"
    Write-Host
    docker compose -f $ComposeFile ps
    Write-Host
}

# Print access information
function Show-AccessInfo {
    Write-Host
    Write-Success "Deployment Complete!"
    Write-Host
    Write-Host "${Green}Access URLs:${NC}"
    Write-Host "  Frontend:    http://localhost (or your server IP)"
    Write-Host "  API Docs:    http://localhost:8000/docs"
    Write-Host "  InfluxDB UI: http://localhost:8086 (dev only)"
    Write-Host
    Write-Host "${Green}Useful Commands:${NC}"
    Write-Host "  View logs:   docker compose logs -f [service]"
    Write-Host "  Stop all:    docker compose down"
    Write-Host "  Restart:     docker compose restart [service]"
    Write-Host "  Shell:       docker compose exec [service] sh"
    Write-Host
}

# Main deployment flow
function Main {
    Write-Host "${Green}========================================${NC}"
    Write-Host "${Green}  MES Edge AI System Deployment${NC}"
    Write-Host "${Green}  Environment: $Environment${NC}"
    Write-Host "${Green}========================================${NC}"
    Write-Host
    
    Test-Prerequisites
    Test-EnvFile
    New-RequiredDirectories
    Build-Images
    Start-Services
    Wait-ForHealth
    Show-Status
    Show-AccessInfo
}

# Run main
Main
