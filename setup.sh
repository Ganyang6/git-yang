#!/bin/bash
# MES Edge AI Worktime Analysis System - 一键部署脚本
# One-Click Deployment Script
# 版本: 1.0.0 | 适用: Ubuntu 22.04/24.04 LTS

set -e

GREEN='\033[0;32m'
YELLOW='\033[1;33m'
RED='\033[0;31m'
NC='\033[0m'

info()  { echo -e "${GREEN}[INFO]${NC} $1"; }
warn()  { echo -e "${YELLOW}[WARN]${NC} $1"; }
error() { echo -e "${RED}[ERROR]${NC} $1"; }

echo ""
echo "=========================================="
echo "  MES Edge AI Worktime Analysis System"
echo "  MES 边缘AI作业工时测定系统 v1.0.0"
echo "=========================================="
echo ""

# ─── 1. 检查 Docker / Check Docker ───────────────────────────
info "检查 Docker 环境... / Checking Docker environment..."

if ! command -v docker &> /dev/null; then
    warn "Docker 未安装。"
    warn "Docker not found."
    echo ""
    echo "  ⚠  离线环境请手动安装 Docker："
    echo "    sudo dpkg -i /path/to/docker-packages/*.deb"
    echo "  ⚠  For offline install, manually install Docker packages."
    echo "     Then re-run this script."
    echo ""
    echo "  ⚠  或连接网络自动安装 (阿里云镜像):"
    echo "  ⚠  Or connect to internet for auto install:"
    echo ""
    read -p "  ➜  是否联网安装 Docker? (y/N): " -n 1 -r
    echo ""
    if [[ $REPLY =~ ^[Yy]$ ]]; then
        info "正在安装 Docker... / Installing Docker..."
        curl -fsSL https://mirrors.aliyun.com/docker-ce/linux/ubuntu/gpg | sudo apt-key add -
        sudo add-apt-repository -y "deb [arch=amd64] https://mirrors.aliyun.com/docker-ce/linux/ubuntu $(lsb_release -cs) stable"
        sudo apt-get update -qq && sudo apt-get install -y -qq docker-ce docker-ce-cli containerd.io docker-compose-plugin
        sudo systemctl start docker
        sudo usermod -aG docker $USER
        info "Docker 安装完成！请重新登录以使组权限生效。"
        info "Docker installed! Please log out and back in for group permissions."
        warn "重新登录后再次执行本脚本即可完成部署。"
        warn "Please re-login and re-run this script."
        exit 0
    else
        error "请手动安装 Docker 后重试。"
        error "Please install Docker manually and re-run."
        exit 1
    fi
fi

info "Docker OK: $(docker --version)"

# ─── 2. 检查 docker compose ────────────────────────────────────
if ! docker compose version &> /dev/null 2>&1; then
    warn "docker compose 未安装 / docker compose plugin not found"
    warn "请安装 docker-compose-plugin 后重试。"
    error "Install docker-compose-plugin and re-run."
    exit 1
fi

info "Docker Compose OK: $(docker compose version)"

# ─── 3. 加载预打包镜像 / Load prebuilt images ─────────────────
info "加载 Docker 镜像... / Loading Docker images..."
IMAGES_DIR="images"

if [ -d "$IMAGES_DIR" ]; then
    COUNT=0
    for img in "$IMAGES_DIR"/*.tar.gz; do
        if [ -f "$img" ]; then
            docker load < "$img" && \
                info "已加载 / Loaded: $(basename "$img")"
            COUNT=$((COUNT + 1))
        fi
    done
    if [ "$COUNT" -eq 0 ]; then
        warn "images/ 目录下未找到 .tar.gz 镜像文件。"
        warn "No .tar.gz image files found in images/ directory."
    else
        info "共加载 $COUNT 个镜像 / Total $COUNT images loaded."
    fi
else
    warn "images/ 目录不存在，跳过镜像加载。"
    warn "images/ directory not found, skipping image load."
fi

# ─── 4. 准备配置 / Prepare configuration ──────────────────────
if [ ! -f ".env" ] && [ -f ".env.example" ]; then
    cp .env.example .env
    info "已从 .env.example 创建 .env 配置 / Created .env from .env.example"
fi

# ─── 5. 启动系统 / Start the system ────────────────────────────
info "启动系统... / Starting system..."
sudo docker compose up -d || {
    error "docker compose 启动失败！请检查配置 / docker compose 启动失败! Check config"
    sudo docker compose logs
    exit 1
}

# ─── 6. 等待服务就绪 / Wait for services to be ready ──────────
info "等待服务就绪... / Waiting for services..."
SERVICE_READY=false
for i in $(seq 1 12); do
    if curl -sf http://127.0.0.1:8000/health > /dev/null 2>&1; then
        SERVICE_READY=true
        break
    fi
    info "尝试 $i/12 ... / Attempt $i/12"
    sleep 5
done

echo ""
echo "=========================================="
echo "  MES 边缘AI作业工时测定系统 v1.0.0"
echo "  MES Edge AI Worktime Analysis System"
echo "=========================================="
echo ""

if [ "$SERVICE_READY" = true ]; then
    info "✅ 系统已就绪！ / System is ready!"
    echo ""
    echo "  🌐 访问地址 / Access URL: http://localhost"
    echo "  🔑 演示账号 / Demo account: admin"
    echo "  🔒 默认密码 / Default password: 12345678"
else
    warn "⚠️  部分服务可能尚未就绪，请稍候检查容器状态。"
    warn "Some services may still be starting. Check container status:"
    echo ""
    echo "  sudo docker compose ps"
    echo "  sudo docker compose logs -f"
    echo ""
    echo "  🌐 访问地址 / Access URL: http://localhost"
    echo "  🔑 演示账号 / Demo account: admin"
fi
echo ""
echo "  📋 常用命令 / Useful commands:"
echo "    查看日志 / View logs:    sudo docker compose logs -f"
echo "    停止系统 / Stop:         sudo docker compose down"
echo "    重启系统 / Restart:      sudo docker compose restart"
echo "=========================================="
