# MES Edge AI System - 运维手册

## 快速开始

### 1. 环境准备

```bash
# 复制环境配置模板
cp .env.example .env.local

# 编辑配置（必须修改 JWT_SECRET_KEY）
nano .env.local
```

### 2. 一键部署

```bash
# Linux/macOS
./scripts/deploy.sh

# Windows (PowerShell)
.\scripts\deploy.ps1
```

### 3. 验证部署

```bash
# 健康检查
./scripts/health-check.sh

# 监控面板
./scripts/monitor.sh
```

---

## 目录结构

```
.
├── docker-compose.yml      # 6 容器编排配置
├── .env.local              # 环境变量（不提交到 Git）
├── .env.example            # 环境变量模板
├── scripts/                # 运维脚本
│   ├── deploy.sh           # 部署脚本
│   ├── deploy.ps1          # Windows 部署脚本
│   ├── health-check.sh     # 健康检查
│   ├── backup.sh           # 数据备份
│   └── monitor.sh          # 监控面板
├── docker/
│   └── nginx.conf          # Nginx 反向代理配置
├── data/                   # 持久化数据（自动创建）
│   ├── redis/              # Redis 数据
│   ├── influxdb/           # InfluxDB 数据
│   └── sqlite/             # SQLite 数据库
└── logs/                   # 日志目录（自动创建）
    ├── backend/            # 后端日志
    └── perception/         # 感知进程日志
```

---

## 服务架构

| 服务 | 端口 | 内存限制 | 说明 |
|------|------|----------|------|
| redis | - | 512MB | 消息总线 + 缓存 |
| influxdb | 8086 | 1GB | 时序数据库 |
| api | 8000 | 2GB | FastAPI 主服务 |
| perception | - | 1.5GB | 摄像头 + MediaPipe |
| worker | - | 1GB | Celery 异步任务 |
| frontend | 80 | 256MB | Nginx 静态服务 |

**总内存预算**: ~6.2GB（适合 8GB 边缘盒子）

---

## 常用命令

### 服务管理

```bash
# 启动所有服务
docker compose up -d

# 停止所有服务
docker compose down

# 重启单个服务
docker compose restart api

# 查看服务状态
docker compose ps

# 查看资源使用
docker compose stats
```

### 日志查看

```bash
# 查看所有服务日志
docker compose logs -f

# 查看特定服务日志
docker compose logs -f api

# 查看最近 100 行
docker compose logs --tail 100 api

# 查看最近 5 分钟的日志
docker compose logs --since 5m
```

### 进入容器

```bash
# 进入 API 容器
docker compose exec api sh

# 进入感知容器
docker compose exec perception sh

# Redis CLI
docker compose exec redis redis-cli

# InfluxDB Shell
docker compose exec influxdb influx
```

---

## 备份与恢复

### 自动备份

```bash
# 执行完整备份（包含 SQLite、Redis、InfluxDB、配置）
./scripts/backup.sh

# 备份保存位置: ./backups/backup_YYYYMMDD_HHMMSS.tar.gz
```

### 手动备份

```bash
# 备份 SQLite
docker compose cp api:/app/data/mes.db ./backup/mes.db

# 备份 Redis
docker compose exec redis redis-cli BGSAVE
docker compose cp redis:/data/dump.rdb ./backup/redis.rdb

# 备份 InfluxDB
docker compose exec influxdb influx backup /backup

# 备份视频文件
cp -r data/videos/* ./backup/videos/
```

### 数据恢复

```bash
# 恢复 SQLite
docker compose cp ./backup/mes.db api:/app/data/mes.db

# 恢复 Redis（需要停止服务）
docker compose down
docker compose cp ./backup/redis.rdb redis:/data/dump.rdb
docker compose up -d

# 恢复视频文件
cp -r ./backup/videos/* data/videos/
```

---

## 视频文件回放

### 视频回放模式

系统支持用视频文件替代摄像头进行 AI 感知分析，适用于演示和对比试验。

### 配置步骤

1. **准备视频文件**：放入 `data/videos/` 目录
2. **编辑 `.env.local`**：
   ```bash
   VIDEO_MODE=true
   VIDEO_PATH=/app/data/videos/your_video.mp4
   STATION_ID=WS-01
   ```
3. **重启服务**：`docker compose down && docker compose --env-file .env.local up -d`

### 视频格式支持

支持 mp4、avi、mov、mkv 等格式（OpenCV 默认支持）。

### 监控回放进度

```bash
docker compose logs -f perception
```

日志会显示每帧处理进度和统计信息。

### 循环播放

在 config.yaml 中设置 `loop: true`，或设置环境变量 `LOOP=true`。

---

## 故障排查

### 服务无法启动

```bash
# 1. 检查日志
docker compose logs --tail 50 [service]

# 2. 检查配置
docker compose config

# 3. 检查端口占用
netstat -tlnp | grep 8000
```

### 内存不足

```bash
# 查看内存使用
docker compose stats

# 调整内存限制（编辑 docker-compose.yml）
services:
  api:
    deploy:
      resources:
        limits:
          memory: 1.5G  # 从 2G 调低
```

### 数据库连接失败

```bash
# 检查 SQLite 文件权限
ls -la data/sqlite/

# 检查 Redis 连接
docker compose exec api python -c "import redis; r = redis.from_url('redis://redis:6379'); print(r.ping())"

# 检查 InfluxDB 连接
docker compose exec api python -c "import influxdb_client; print('ok')"
```

### 摄像头无法识别

```bash
# 列出可用摄像头设备
ls -la /dev/video*

# 检查设备权限
sudo usermod -aG video $USER

# 修改 docker-compose.yml 中的设备映射
devices:
  - /dev/video0:/dev/video0
```

---

## 安全加固

### 1. 修改默认密钥

编辑 `.env.local`：

```bash
# 生成强密钥
python -c "import secrets; print(secrets.token_hex(32))"

# 更新配置
JWT_SECRET_KEY=your-generated-key-here
```

### 2. 限制 InfluxDB 暴露

生产环境删除端口映射：

```yaml
services:
  influxdb:
    # 删除或注释掉 ports 部分
    # ports:
    #   - "8086:8086"
```

### 3. 配置防火墙

```bash
# 仅开放必要端口
sudo ufw allow 80/tcp    # HTTP
sudo ufw allow 443/tcp   # HTTPS (如果使用)
sudo ufw allow 8000/tcp  # API (如需直接访问)
```

---

## 性能监控

### 关键指标

| 指标 | 告警阈值 | 检查命令 |
|------|----------|----------|
| API 响应时间 | > 500ms | curl -w "%{time_total}" http://localhost:8000/ |
| 内存使用 | > 85% | docker compose stats |
| 磁盘使用 | > 90% | df -h |
| 服务健康 | unhealthy | ./scripts/health-check.sh |

### 日志监控

```bash
# 实时监控错误
./scripts/monitor.sh

# 或使用命令行
docker compose logs -f | grep -i error
```

---

## 更新部署

### 代码更新

```bash
# 1. 拉取最新代码
git pull origin main

# 2. 重新构建并部署
./scripts/deploy.sh
```

### 仅更新配置

```bash
# 修改 .env.local 后，重启服务
docker compose down
docker compose up -d
```

---

## CI/CD 集成

GitHub Actions 已配置以下工作流：

- **frontend-ci.yml**: 前端构建检查
- **backend-ci.yml**: 后端单元测试 + 代码检查
- **release.yml**: 自动发版

配置 Secrets：
- `DEPLOY_HOST`: 服务器 IP
- `DEPLOY_USER`: SSH 用户名
- `DEPLOY_SSH_KEY`: SSH 私钥
- `FRONTEND_DEPLOY_PATH`: 部署路径

---

## 联系与支持

遇到问题？

1. 查看日志: `docker compose logs -f`
2. 运行健康检查: `./scripts/health-check.sh`
3. 检查系统资源: `docker compose stats`
