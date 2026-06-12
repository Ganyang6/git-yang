# 面向中小型离散加工企业的管理系统

> **MES Edge AI Worktime Analysis System**  
> 面向中小型离散加工企业的轻量级 MES 系统，基于边缘 AI 技术实现作业工时的自动化测定与分析。  
> v1.0.0

---

## 项目介绍

本项目面向**中小型离散加工企业**，在边缘计算设备上部署 AI 视觉分析引擎，实时捕捉操作人员的肢体动作并自动归类为 Therblig 基本动作要素（伸手、抓取、移动、组装、检查等），从而**自动测算单件工时**，替代传统的人工秒表测时法。

系统由 6 个 Docker 微服务构成，支持离线部署，适用于没有稳定互联网连接的车间环境。

### 设计目标

| 目标 | 说明 |
|------|------|
| 🎯 **低成本** | 无需昂贵 GPU 服务器，单台边缘盒子即可运行 |
| 🔌 **易部署** | 一键脚本启动，U 盘拷贝即装即用 |
| 📊 **可视化** | 生产看板、质量统计、报表系统开箱即用 |
| 🧩 **可扩展** | 微服务架构，模块可独立升级替换 |

---

## 技术栈

| 层级 | 技术 | 用途 |
|------|------|------|
| **后端框架** | Python 3.12 + FastAPI | REST API 服务 |
| **ORM** | SQLAlchemy + SQLite | 关系数据存储 |
| **前端** | Vue 3 + Element Plus + ECharts | 管理界面与可视化图表 |
| **AI 引擎** | MediaPipe (CPU/GPU) | 人体姿态估计与动作分类 |
| **消息队列** | Redis Streams | 异步任务与事件流 |
| **时序存储** | InfluxDB | 工时与传感器时序数据 |
| **容器编排** | Docker Compose (6 服务) | 服务生命周期管理 |

---

## 功能特性

### 📹 工时采集

- 通过视频捕捉作业人员肢体动作
- MediaPipe 姿态估计 → 关节点坐标 → Therblig 动作分类
- 记录工时要素并上传至服务端汇总

### 🔄 动作要素分析

基于 Therblig 理论对操作动作进行分类：

| 类别 | 动作要素 | 说明 |
|------|----------|------|
| 有效 | 伸手、抓取、移动、组装、松开 | 创造价值的加工动作 |
| 辅助 | 寻找、选择、检查、定位 | 必要的辅助动作 |
| 无效 | 持住、等待、休息、迟延 | 应消除的浪费动作 |

### 🏭 生产看板

- 产线概览：当日产量、在线工位、异常告警
- 产能统计：日/周/月趋势图
- 异常预警：工时超标、动作异常自动推送

### ✅ 质量管理

- 质检记录录入与跟踪
- 良品率实时统计
- 不良原因分类分析

### 📈 报表系统

- 订单完成率报表
- 综合良品率
- 按时交货率
- Excel 导出


## 快速部署

### 环境要求

| 项目 | 要求 |
|------|------|
| **操作系统** | Ubuntu 22.04 / 24.04 LTS |
| **内存** | ≥ 4 GB |
| **磁盘** | ≥ 20 GB |
| **CPU** | 双核及以上 (x86_64) |
| **网络** | 首次安装需联网（后续可离线运行） |

### 一键部署（推荐）

```bash
# 1. 解压安装包
unzip mes-system-v1.0.zip && cd mes-system-v1.0

# 2. 运行一键部署脚本
sudo bash setup.sh

# 3. 打开浏览器访问
# http://localhost
```

> **离线部署**：将整个 `mes-system-v1.0/` 目录拷贝至 U 盘，在目标机器上解压后执行 `sudo bash setup.sh` 即可。首次启动后所有服务均可离线运行。

### 演示账号

| 账号 | 密码 | 权限 |
|------|------|------|
| admin | 12345678 | 管理员（全部权限） |

### 手动部署（无 Docker）

如不想使用 Docker，可单独启动各组件：

```bash
# ─── 后端 ───
cd mes-backend
pip install -r requirements.txt -i https://mirrors.aliyun.com/pypi/simple/
python -m uvicorn app.main:app --host 0.0.0.0 --port 8000

# ─── 前端（需 Node.js） ───
cd mes-frontend
npm install
npm run build
npx serve dist -l 3000   # 用 3000 端口，无需 root 权限

# ─── 额外需要启动的服务 ───
# Redis:   redis-server
# InfluxDB: influxd
```

---

## 项目结构

```
mes-system-v1.0/
├── docker-compose.yml         # Docker Compose 编排文件
├── setup.sh                   # 一键部署脚本（入口）
├── .env.example               # 环境变量模板
├── secrets/                   # 密钥与证书文件
│   └── jwt_secret.key
├── mes-backend/               # 后端服务
│   ├── app/
│   │   ├── main.py            # FastAPI 入口
│   │   ├── api/               # REST API 路由
│   │   ├── models/            # 数据模型
│   │   ├── schemas/           # Pydantic 校验
│   │   ├── services/          # 业务逻辑
│   │   └── core/              # 配置、数据库、安全
│   ├── requirements.txt
│   └── config.yaml
├── mes-frontend/              # 前端服务
│   ├── src/
│   │   ├── views/             # 页面组件
│   │   ├── components/        # 通用组件
│   │   ├── router/            # 路由配置
│   │   └── utils/             # 工具函数
│   └── dist/                  # 构建产物（生产部署用）
└── images/                    # 预构建 Docker 镜像 (.tar.gz)
    ├── mes-api.tar.gz
    ├── mes-frontend.tar.gz
    ├── mes-perception.tar.gz
    ├── mes-worker.tar.gz
    ├── redis.tar.gz
    └── influxdb.tar.gz
```

---

## 架构图（Docker 服务）

```
┌────────────────────────────────────────────────────┐
│                   用户浏览器                         │
└──────────────▲────────────────────────────────────┘
               │ HTTP
┌──────────────┴──────────────┐
│    Frontend (Nginx)         │  端口 80
│    Vue 3 构建产物           │  → 反向代理 API
└──────────────┬──────────────┘
               │
┌──────────────┴──────────────┐
│     API (FastAPI)           │  端口 8000
│     主业务逻辑              │
│     JWT 认证                │
└──┬────────────┬──────────┬──┘
   │            │          │
   ▼            ▼          ▼
┌──────┐  ┌──────────┐  ┌──────────┐
│Redis │  │ InfluxDB │  │ SQLite   │
│队列/ │  │ 时序数据  │  │ 关系数据  │
│缓存  │  │          │  │          │
└──┬───┘  └──────────┘  └──────────┘
   │
   │ Streams
   ▼
┌──────────────┐  ┌──────────────────┐
│  Worker      │  │  Perception      │
│ (Celery)     │  │ (MediaPipe)      │
│ 任务处理     │  │ AI 推理引擎      │
└──────────────┘  └──────────────────┘
```

### 6 个 Docker 服务

| 服务名 | 角色 | 技术 | 说明 |
|--------|------|------|------|
| **redis** | 缓存 & 消息队列 | Redis | 任务队列、Session 缓存 |
| **influxdb** | 时序数据库 | InfluxDB 2.x | 工时数据、传感器数据 |
| **api** | 主后端服务 | FastAPI | 业务 API、认证、报表 |
| **perception** | AI 推理引擎 | MediaPipe | 人体姿态估计、动作分类 |
| **worker** | 异步任务处理 | Celery + Redis | 后台计算、数据聚合 |
| **frontend** | 前端 & 反向代理 | Nginx | 静态资源，API 反代 |

---

## 常见问题

### Q: 如何查看日志？

```bash
sudo docker compose logs -f        # 所有服务日志
sudo docker compose logs -f api    # 只看后端日志
```

### Q: 如何停止系统？

```bash
sudo docker compose down
```

---

## 许可

本项目仅供学习和评估使用。商业使用请联系版权方获取授权。

---

*© 2025 MES Edge AI Worktime Analysis System. All rights reserved.*
