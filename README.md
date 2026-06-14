# 基于边缘AI的作业工时测定系统

> **Edge AI Worktime Analysis System** — 将计算机视觉与工业工程方法相结合，从操作视频中自动识别工人动作并计算标准工时，帮助制造企业实现生产工时数字化管理，发现瓶颈工位，提升产线效率。
>
> v1.0.0

---

## 项目概述

本项目将计算机视觉与工业工程（IE）方法相结合，用于制造业产线的工时测定与效率分析。系统采用 **MediaPipe** 人体姿态估计与动作识别技术，从操作视频中自动识别工人的操作动素（Therblig），并基于 **MOD 法**（Modular Arrangement of Predetermined Time Standard）计算标准工时。

系统提供 **工位管理、视频分析、工时测定、产线平衡分析、AI 智能分析及多维度报表分析** 等功能，可在边缘计算设备上离线部署。

---

## 技术栈

| 层级 | 技术 | 用途 |
|------|------|------|
| 后端框架 | Python 3.11 / FastAPI | RESTful API 服务 |
| 前端框架 | Vue 3 / Vite / TypeScript | 单页应用与交互看板 |
| 关系数据库 | SQLite (SQLAlchemy ORM) | 结构化业务数据存储 |
| 时序数据库 | InfluxDB 2.7 | 指标时序数据存储 |
| 消息队列 | Redis 7 + Redis Streams | 消息总线与流式计算 |
| 任务队列 | Celery | 异步任务处理 |
| AI 推理 | MediaPipe Holistic | 人体姿态估计与动作分类 |
| AI 大模型 | DeepSeek API | ECRS 改善建议生成 |
| 可视化 | ECharts | 图表渲染（山积图、雷达图等） |
| 容器化 | Docker Compose (6 服务) | 多服务编排部署 |
| 认证鉴权 | JWT / bcrypt | 用户身份认证 |

---

## 系统架构

系统采用前后端分离的微服务架构，各服务通过 Docker Compose 统一编排部署：

```
用户浏览器 ─→ Frontend (Nginx) ─→ API (FastAPI)
                                        │
                    ┌───────────────────┼───────────────────┐
                    ▼                   ▼                   ▼
               SQLite             InfluxDB              Redis
            (业务数据)           (时序指标)          (消息队列/缓存)
                                                           │
                                                           ▼
                                              ┌─────────────────────┐
                                              │   Perception 服务    │
                                              │ MediaPipe 姿态估计    │
                                              └─────────────────────┘
                                                           │
                                              ┌─────────────────────┐
                                              │  Celery Worker      │
                                              │ Therblig 映射/聚合   │
                                              │ AI 分析/PDF 生成     │
                                              └─────────────────────┘
```

### 核心数据流

```
视频上传 → Perception 服务 (MediaPipe 逐帧分析)
    ↓
动作分段 (ProcessSegment) 写入
    ↓
后台聚合 → 工时记录 (WorktimeRecord) 生成
    ├── Therblig 动素分解
    ├── MOD 法标准工时计算
    └── 效率计算
    ↓
前端展示 / AI 分析 (DeepSeek ECRS) / PDF 导出
```

### Docker 服务组成

| 服务名 | 容器名 | 职责 |
|--------|--------|------|
| **redis** | mes-redis | 消息总线、缓存、Celery Broker |
| **influxdb** | mes-influxdb | 时序指标存储 |
| **api** | mes-api | FastAPI 主服务 |
| **perception** | mes-perception | MediaPipe 感知处理 |
| **worker** | mes-worker | Celery 异步任务处理 |
| **frontend** | mes-frontend | Vue 3 前端 + Nginx |

---

## 功能模块

### 1. 工位管理（Station）

工位是系统的数据基础，所有模块统一从 Station 表读取工位信息。

- 工位 CRUD（增删改查）
- 字段：编号、操作人、产线、班次
- 同一产线同班次下工位编号唯一

### 2. 视频分析（Video Analysis）

核心输入端，实现从操作视频到动作分段的全自动处理。

- 支持 MP4/AVI/MOV/MKV 格式（最大 500MB）
- 文件魔数自动检测容器格式
- SSE 实时推送处理进度
- 识别的动作标签: reach（伸手）、grasp（抓取）、move（移动）、assemble（组装）、release（释放）、inspect（检查）、use（使用工具）、hold（握持）、wait（等待）、idle（空闲）

### 3. 生产工时看板（Dashboard）

产线实时运行状态的集中监控视图。

- **KPI 指标卡**：人力利用率 (HUR)、标准工时达成率、产线平衡率 (LBR)
- **工位时间线**：按时间轴展示各工位活动状态
- **WebSocket 实时推送**，支持 LIVE / OFFLINE 状态指示
- 支持今日、本周、本月时间范围过滤

### 4. 工时分析（Worktime Analysis）

对动作分段数据进行深入的工业工程分析。

- **Therblig 动素分解**：展示各动素的耗时占比
- **MOD 法标准工时**：1 MOD = 0.129 秒
- **效率计算**：`效率 = 标准工时 / 实际工时`
- **AI 分析**：调用 DeepSeek 大模型，基于 IE 准则生成 ECRS 改善建议
- **Waste 分析**：识别非增值动素（等待、空闲、握持、检查等）
- 支持工时校准（管理员权限）和 PDF 导出

### 5. 产线平衡分析（Line Balance）

核心分析模块，帮助 IE 工程师发现产线瓶颈并进行优化。

- **平衡率 (LBR)**：85% 以上为优
- **平滑指数 (SI)**：量化工位间工时偏差
- **节拍时间 (Takt Time)**：`可用时间 / 需求量`
- **瓶颈工位识别** + 损失产能计算（按件/按日）
- **山积图 (Yamazumi Chart)**：增值/非增值工时构成可视化
- **ECRS 改善建议清单**：取消、合并、重排、简化
- **What-If 仿真**：模拟调整工位节拍后的平衡率变化

### 6. 报表分析（Reports）

多维度生产数据统计与可视化。

- 产量趋势图（月/周）
- 客户排名、产品类别占比
- 平衡率雷达图
- 工时箱线图（中位数、四分位数、异常值）
- 工位时间密集度热力图
- PDF 导出

### 7. 系统管理

- **订单管理**：生产订单 CRUD，关联客户管理
- **客户管理**：客户基础信息、分类与等级体系
- **库存管理**：物料台账、安全库存、入库/出库流水
- **设备管理**：设备台账、OEE 追踪

---

## 快速开始

### 环境要求

| 项目 | 要求 |
|------|------|
| 操作系统 | Ubuntu 22.04 / 24.04 LTS |
| 内存 | ≥ 4 GB |
| 磁盘 | ≥ 20 GB |
| CPU | 双核及以上 (x86_64) |
| 网络 | 首次安装需联网（后续可离线运行） |

### 一键部署

```bash
# 1. 解压安装包
unzip mes-system-v1.0.zip && cd mes-system-v1.0

# 2. 运行一键部署脚本
sudo bash setup.sh

# 3. 打开浏览器访问
# http://localhost
```

> **离线部署**：将 `mes-system-v1.0/` 目录拷贝至 U 盘，在目标机器上解压后执行 `sudo bash setup.sh` 即可。

### 演示账号

| 账号 | 密码 | 权限 |
|------|------|------|
| admin | 12345678 | 管理员（全部权限） |

### 手动部署（无 Docker）

```bash
# ─── 后端 ───
cd mes-backend
pip install -r requirements.txt -i https://mirrors.aliyun.com/pypi/simple/
python -m uvicorn app.main:app --host 0.0.0.0 --port 8000

# ─── 前端（需 Node.js） ───
cd mes-frontend
npm install
npm run build
npx serve dist -l 3000

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
├── mes-backend/               # 后端服务 (FastAPI)
│   ├── app/
│   │   ├── main.py            # FastAPI 入口
│   │   ├── api/               # REST API 路由
│   │   ├── models/            # SQLAlchemy 数据模型
│   │   ├── schemas/           # Pydantic 校验 schema
│   │   ├── services/          # 业务逻辑层
│   │   └── core/              # 配置、数据库、安全
│   ├── requirements.txt
│   └── config.yaml
├── mes-frontend/              # 前端服务 (Vue 3)
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

## 常见问题

### 查看日志

```bash
sudo docker compose logs -f        # 所有服务日志
sudo docker compose logs -f api    # 只看后端日志
```

### 停止系统

```bash
sudo docker compose down
```

---

## 许可

本项目仅供学习和评估使用。商业使用请联系版权方获取授权。

*© 2025 Edge AI Worktime Analysis System. All rights reserved.*
