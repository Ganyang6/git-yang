# MES Edge AI Worktime Analysis System

MES（边缘 AI 作业工时测定系统）- 完整生产线工时分析与平衡诊断系统。

## 系统架构

```
┌─────────────┐    ┌─────────────┐    ┌─────────────┐
│  Frontend   │    │     API     │    │  Perception │
│  Vue 3 SPA  │◄──►│  FastAPI    │◄──►│  MediaPipe  │
│  (Nginx)    │    │  (Uvicorn)  │    │  (Camera)   │
└─────────────┘    └──────┬──────┘    └──────┬──────┘
                          │                   │
                    ┌─────▼──────┐      ┌─────▼──────┐
                    │   Redis    │◄─────│  Streams   │
                    │  (Streams) │      └────────────┘
                    └─────┬──────┘
                          │
                    ┌─────▼──────┐    ┌─────────────┐
                    │  Celery    │    │  InfluxDB   │
                    │  Worker    │    │  Metrics    │
                    └────────────┘    └─────────────┘
```

## 技术栈

- **Backend**: Python 3.12 + FastAPI
- **Frontend**: Node.js 22 + Vue 3 + Vitest
- **Database**: InfluxDB 2.0 (时序数据) + SQLite (业务数据)
- **Queue/Cache**: Redis Streams
- **AI**: MediaPipe (姿态识别) + ONNX (动作分类)
- **Container**: Docker Compose + WSL2

## 快速启动

### Docker Compose（推荐）

```bash
# 1. 创建 Secrets 文件
mkdir -p secrets
openssl rand -base64 32 > secrets/jwt_secret.key
openssl rand -base64 32 > secrets/influxdb_token.key
openssl rand -base64 32 > secrets/deepseek_api_key.key
openssl rand -base64 16 > secrets/redis_password.key
openssl rand -base64 16 > secrets/influxdb_admin_password.key

# 2. 启动所有服务
docker compose up -d

# 3. 查看日志
docker compose logs -f
```

### 本地开发

```bash
# Backend
cd mes-backend
pip install -r requirements.txt
uvicorn app.main:app --reload --port 8000

# Frontend
cd mes-frontend
npm install
npm run dev
```

## 项目结构

```
mes-edge-ai/
├── docker-compose.yml          # 生产环境 Compose 配置
├── Dockerfile.frontend         # 前端多阶段构建
├── Dockerfile.backend          # Backend 多阶段构建
├── Dockerfile.perception       # 感知层 Dockerfile
├── mes-backend/               # Backend 应用代码
│   ├── app/
│   │   ├── api/              # API 路由
│   │   ├── core/             # 核心模块（config, enums, redis）
│   │   ├── models/           # 数据模型 & Schemas
│   │   └── services/         # 业务逻辑（分类器、聚合器）
│   ├── requirements.txt
│   └── README.md
├── mes-frontend/             # Frontend 应用代码
│   ├── nginx.conf            # Nginx envsubst 模板
│   └── README.md
├── secrets/                  # Docker Secrets（gitignored）
│   ├── jwt_secret.key
│   ├── influxdb_token.key
│   ├── deepseek_api_key.key
│   ├── redis_password.key
│   └── influxdb_admin_password.key
└── README.md                 # 本文件
```

## Secrets 配置

敏感信息通过 Docker Secrets 管理，[详见 mes-backend/README.md](./mes-backend/README.md) 中的 Secrets 配置说明。

## 环境变量参考

| 变量 | 说明 | 默认值 |
|------|------|--------|
| `JWT_SECRET_KEY` | JWT 签名密钥 | 无（必须设置） |
| `REDIS_URL` | Redis 连接 | `redis://:password@redis:6379/0` |
| `MES_DB_URL` | 数据库路径 | `sqlite:////app/data/mes.db` |
| `INFLUXDB_URL` | InfluxDB 连接 | `http://influxdb:8086` |
| `CELERY_BROKER_URL` | Celery Broker | `redis://:password@redis:6379/0` |
| `UPLOAD_MAX_SIZE` | 上传大小限制（MB） | `500` |
| `REDIS_PASSWORD` | Redis 密码 | `mes-redis-2026` |

## 服务端口

| 服务 | 端口 | 说明 |
|------|------|------|
| Frontend (Nginx) | 80 | Web 入口 |
| API (FastAPI) | 8000 (内网) | REST API |
| Redis | 6379 (内网) | 消息总线 |
| InfluxDB | 8086 (内网) | 时序数据库 |
| 开发-前端 | 5173 | Vite 开发服务器 |
| 开发-后端 | 8000 | Uvicorn 热重载 |

## 相关文档

- [mes-backend/README.md](./mes-backend/README.md) - Backend 详细文档
- [Docker Compose 配置](./docker-compose.yml) - 生产部署配置

## Local setup

Follow the project docs (not included in this minimal repository).
