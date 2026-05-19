# MES 边缘AI作业工时测定系统 -- 使用说明

## 1. 系统概述

本系统是一套面向制造现场的边缘AI作业工时测定平台，基于视频感知自动识别工人动作，进行动素分析、工时统计和产线平衡优化。系统采用 Docker Compose 一键部署，包含 6 个微服务。

## 2. 环境要求

| 项目 | 最低要求 |
|------|---------|
| 操作系统 | Windows 11 (WSL2) / Linux |
| 内存 | 16 GB RAM |
| Docker | Docker Engine 24.0+ / Docker Desktop 4.28+ |
| Docker Compose | V2 (docker compose 子命令) |
| 摄像头 | USB 摄像头 (perception 服务需要, 演示模式可选) |

## 3. 快速启动

### 3.1 首次部署

```bash
# 1. 克隆项目后进入根目录
cd /path/to/mes-project

# 2. 创建环境配置文件
cp docker/.env.template .env.local

# 3. 生成 JWT 密钥并填入 .env.local
python -c "import secrets; print(secrets.token_hex(32))"
# 将输出的字符串填入 .env.local 的 JWT_SECRET_KEY=

# 4. 构建镜像
docker compose --env-file .env.local build

# 5. 启动全部服务
docker compose --env-file .env.local up -d

# 6. 等待服务就绪 (约 30-60 秒)
docker compose ps
```

### 3.2 后续启动/停止

```bash
# 启动
docker compose --env-file .env.local up -d

# 停止
docker compose down

# 查看日志
docker compose logs -f           # 全部服务
docker compose logs -f api       # 仅 API
docker compose logs -f worker    # 仅 Celery Worker

# 重启单个服务
docker compose restart api
```

### 3.3 环境变量说明 (.env.local)

| 变量 | 默认值 | 说明 |
|------|--------|------|
| API_PORT | 8000 | API 服务端口 |
| FRONTEND_PORT | 80 | 前端页面端口 |
| INFLUXDB_EXPOSE_PORT | 8086 | InfluxDB 管理界面端口 (仅 localhost) |
| INFLUXDB_ADMIN_USER | admin | InfluxDB 初始化管理员用户名 |
| INFLUXDB_ADMIN_PASSWORD | mes-admin-2026 | InfluxDB 初始化管理员密码 |
| INFLUXDB_TOKEN | (空) | InfluxDB API Token (首次登录后在 UI 中创建) |
| JWT_SECRET_KEY | (必填) | JWT 签名密钥, >= 32 字节随机字符串 |
| DEEPSEEK_API_KEY | (空) | DeepSeek API 密钥, 留空则禁用 AI 分析功能 |
| CAMERA_DEVICE | /dev/video0 | 摄像头设备路径 |
| CAMERA_ID | 0 | 摄像头索引 |

## 4. 访问系统

服务启动后：

| 入口 | 地址 | 说明 |
|------|------|------|
| **前端页面** | http://localhost | 系统主界面 |
| **API 文档** | http://localhost:8000/docs | Swagger 交互式 API 文档 |
| **API 备用文档** | http://localhost:8000/redoc | ReDoc 格式 API 文档 |
| InfluxDB 管理界面 | http://localhost:8086 | 时序数据管理 (仅本地访问) |

## 5. 登录与权限

### 5.1 默认账号

系统内置管理员账号：

- 用户名: `admin`
- 默认密码: `changeme` (生产环境务必修改)

可通过环境变量 `DEFAULT_ADMIN_PASSWORD` 在启动时设置自定义初始密码。

### 5.2 登录方式

在前端登录页面输入用户名密码即可。登录成功后系统颁发 JWT Token，前端自动存储并在后续请求中携带。

### 5.3 权限等级

| 角色 | 权限 |
|------|------|
| admin | 全部权限 |
| engineer | 数据查看、AI分析、报告导出 |
| viewer | 只读数据查看 |

## 6. 功能模块说明

### 6.1 Dashboard (仪表盘)

访问路径: 前端首页

展示系统全局关键指标，包括产量统计、良品率、OEE、工位状态时间线等实时数据。数据通过 WebSocket/SSE 实时推送。

### 6.2 Worktime Analysis (工时分析)

访问路径: 侧边栏 -> 工时分析

核心功能模块。展示各工位、各工序的工时统计、动素分布、工时趋势图表。

### 6.3 Line Balance (产线平衡)

访问路径: 侧边栏 -> 产线平衡

展示产线各工位的负荷均衡情况、瓶颈工位诊断。支持 ECRS 动素优化建议。

### 6.4 AI Analysis (AI 分析)

访问路径: 侧边栏 -> AI 分析

基于 DeepSeek 大模型的智能分析功能。支持：
- 对话式工时分析提问
- 异步深度分析任务 (提交后后台处理，完成后通知)
- SSE 流式输出分析结果

注意: 需要在 .env.local 中配置有效的 DEEPSEEK_API_KEY 才能使用此功能。

### 6.5 Orders (订单管理)

访问路径: 侧边栏 -> 订单管理

订单的增删改查，支持按状态、优先级筛选，支持分页。

### 6.6 Customers (客户管理)

访问路径: 侧边栏 -> 客户管理

客户信息的增删改查，包含客户统计数据。

### 6.7 Inventory (库存管理)

访问路径: 侧边栏 -> 库存管理

物料库存查询，支持入库/出库操作，低库存预警。

### 6.8 Equipment (设备管理)

访问路径: 侧边栏 -> 设备管理

设备台账管理，设备状态统计。

### 6.9 Reports (报告导出)

访问路径: 侧边栏 -> 报告中心

支持导出 PDF 报告：
- 工时分析报告
- 产线平衡报告

## 7. API 接口总览

API 基础路径: `http://localhost:8000/api/`

| 模块 | 路径 | 说明 |
|------|------|------|
| 认证 | /api/auth/login | 登录获取 JWT |
| 认证 | /api/auth/me | 获取当前用户信息 |
| 仪表盘 | /api/dashboard/kpi | 关键指标 |
| 仪表盘 | /api/dashboard/ai-context | AI 上下文数据 |
| 工位 | /api/stations/timeline | 工位时间线 |
| 工时 | /api/worktime/summary | 工时汇总 |
| 工时 | /api/worktime/therblig-distribution | 动素分布 |
| 工时 | /api/worktime/trend | 工时趋势 |
| 产线平衡 | /api/line-balance/summary | 产线平衡概览 |
| 产线平衡 | /api/line-balance/bottleneck-diagnosis | 瓶颈诊断 |
| AI | /api/ai/chat | AI 对话 |
| AI | /api/ai/chat/stream | SSE 流式对话 |
| AI | /api/ai/tasks | 异步任务列表 |
| 订单 | /api/orders/ | 订单 CRUD |
| 客户 | /api/customers/ | 客户 CRUD |
| 库存 | /api/inventory/ | 库存查询与出入库 |
| 设备 | /api/equipment/ | 设备 CRUD |
| 报告 | /api/reports/worktime/pdf | 工时 PDF 导出 |
| 报告 | /api/reports/line-balance/pdf | 产线平衡 PDF 导出 |
| 异常 | /api/anomaly/events | 异常事件列表 |
| 实时事件 | /api/sse/events | SSE 实时数据推送 |

完整接口文档请访问 http://localhost:8000/docs

## 8. 服务架构

| 服务 | 容器名 | 内存限制 | 说明 |
|------|--------|---------|------|
| redis | mes-redis | 600 MB | 消息总线 + 缓存 + Celery Broker |
| influxdb | mes-influxdb | 1 GB | 时序数据存储, 30 天数据保留 |
| api | mes-api | 2 GB | FastAPI 主进程, 处理业务 API |
| perception | mes-perception | 1.5 GB | 视频采集 + MediaPipe 姿态/手势检测 |
| worker | mes-worker | 1 GB | Celery 异步任务处理 (AI 分析等) |
| beat | mes-beat | 128 MB | Celery Beat 周期任务调度 |
| frontend | mes-frontend | 256 MB | Nginx 静态文件服务 + API 反向代理 |

数据流: 摄像头 -> perception -> Redis Stream -> api -> InfluxDB/SQLite -> 前端

## 9. 配置文件

### 9.1 摄像头配置 (config.yaml)

文件路径: `mes-backend/config.yaml`

```yaml
cameras:
  - device_id: 0          # 摄像头设备索引
    name: "Camera_0"
    enabled: true
    resolution_width: 1280
    resolution_height: 720
    fps: 30
    backend: "auto"       # auto / v4l2 / gstreamer

pose:
  model_complexity: 1     # 0=Lite, 1=Full, 2=Heavy
  smooth: true            # 平滑处理
  min_detection_confidence: 0.5
  min_tracking_confidence: 0.5

buffer:
  max_queue_size: 10      # 帧缓冲队列大小
  drop_old_frames: true   # 丢弃旧帧保证实时性
```

修改后需重启 perception 服务: `docker compose restart perception`

## 10. 演示模式

如果不需要接入真实摄像头 (例如演示 PPT 或测试前端功能)，可以不启动 perception 服务：

```bash
# 只启动核心服务 (不含摄像头感知)
docker compose --env-file .env.local up -d redis influxdb api worker beat frontend
```

系统会加载预置的演示数据，仪表盘和报告页面可以正常查看。

### 加载演示数据

API 服务首次启动时会自动创建管理员账号。如需加载完整的演示业务数据 (订单、客户、库存等)：

```bash
docker exec mes-api python -m scripts.seed_demo_data
```

## 11. 健康检查

### 11.1 冒烟测试脚本

项目提供了自动化的冒烟测试脚本:

```bash
chmod +x scripts/smoke_test.sh
./scripts/smoke_test.sh
```

该脚本会检查: Redis 连通性、InfluxDB 连通性、API 文档可访问性、登录 API、前端页面、PDF 导出、Docker 服务健康状态。

### 11.2 手动检查

```bash
# 检查所有服务状态
docker compose ps

# 检查 API 是否正常
curl http://localhost:8000/docs

# 测试登录
curl -X POST http://localhost:8000/api/auth/login \
  -H "Content-Type: application/json" \
  -d '{"username":"admin","password":"changeme"}'

# 检查前端
curl http://localhost/
```

## 12. 数据持久化

系统使用 Docker 命名卷持久化数据：

| 卷名 | 对应数据 |
|------|---------|
| redis_data | Redis AOF 持久化文件 |
| influxdb_data | InfluxDB 时序数据 |
| sqlite_data | SQLite 业务数据库 (mes.db) |

数据不会随容器删除而丢失。如需彻底清除数据：

```bash
docker compose down -v    # 删除容器和卷
```

## 13. 日志

| 服务 | 日志位置 (容器内) | 宿主机映射 |
|------|------------------|-----------|
| api | /app/logs/ | ./logs/backend/ |
| worker | /app/logs/ | ./logs/worker/ |
| beat | /app/logs/ | ./logs/beat/ |

查看实时日志:

```bash
docker compose logs -f api
docker compose logs -f worker
```

## 14. 常见问题

**Q: 前端页面能打开但 API 请求 404**
A: 确保 api 服务已完全启动。`docker compose ps` 确认 mes-api 状态为 running 且 health 为 healthy。

**Q: AI 分析功能不可用**
A: 检查 .env.local 中 DEEPSEEK_API_KEY 是否已填写有效值。留空则 AI 功能禁用。

**Q: perception 服务一直 unhealthy**
A: perception 服务需要摄像头设备。如无摄像头，可不启动该服务 (见第 10 节演示模式)。

**Q: 登录失败**
A: 确认 API 服务已加载初始数据。默认账号 admin/changeme。检查 JWT_SECRET_KEY 是否已正确设置。

**Q: 内存不足**
A: 系统至少需要 16 GB RAM。可在 docker-compose.yml 中调低各服务的 memory limits，但可能影响性能。

**Q: 如何修改端口**
A: 编辑 .env.local 中的 API_PORT 和 FRONTEND_PORT，然后 `docker compose up -d` 重启。
