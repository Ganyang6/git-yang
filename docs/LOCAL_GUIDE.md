# MES 边缘AI作业工时测定系统 -- 本机使用说明

> 适用环境: 本机 Windows 11 家庭中文版 (Build 26100) / 16 GB RAM / Docker Desktop 29.3.1 / WSL2 Ubuntu 24.04

---

## 一、前置条件 (已就绪)

本机已安装完成以下组件, 无需重复操作:

- WSL2 Ubuntu 24.04 LTS (Running)
- Docker Desktop 29.3.1 + Compose v5.1.1
- Docker 镜像加速器 (docker.1ms.run + docker.xuanyuan.me)
- 3 个项目镜像已构建完成:
  - mes-backend (1.29 GB)
  - mes-perception (1.2 GB)
  - mes-frontend (76.1 MB)
- 环境配置文件 `.env.local` 已生成 (JWT_SECRET_KEY 已设置)

---

## 二、启动系统

打开 PowerShell, 在项目目录下执行:

```powershell
cd "d:\analyze ai"

# 启动全部服务 (首次启动约 30-60 秒)
docker compose --env-file .env.local up -d

# 查看服务状态, 等待全部变成 healthy/running
docker compose ps
```

如果不需要接入摄像头 (演示 PPT、测试功能), 可以跳过 perception 服务以节省 1.5 GB 内存:

```powershell
# 演示模式: 不启动摄像头感知
docker compose --env-file .env.local up -d redis influxdb api worker beat frontend
```

### 服务启动顺序与依赖

```
redis, influxdb (基础服务, 无依赖)
    |
    v
api (依赖 redis + influxdb)
    |
    v
frontend (依赖 api)
perception (依赖 redis, 需要摄像头)
worker (依赖 redis)
    |
    v
beat (依赖 redis + worker)
```

---

## 三、访问系统

浏览器打开以下地址:

| 入口 | 地址 | 用途 |
|------|------|------|
| **系统前端** | http://localhost | 登录后使用系统全部功能 |
| **API 文档** | http://localhost:8000/docs | Swagger 接口文档, 可在线调试 |
| InfluxDB 管理 | http://localhost:8086 | 时序数据库管理 (仅本机可访问) |

### 登录

- 用户名: `admin`
- 密码: `changeme`

登录后进入 Dashboard 仪表盘页面。

---

## 四、加载演示数据

首次启动后, 系统只有管理员账号, 没有业务数据。加载演示数据:

```powershell
docker exec mes-api python -m scripts.seed_demo_data
```

加载后会有预置的订单、客户、库存、设备、工时等数据, Dashboard 和各功能页面都能看到内容。

---

## 五、停止与重启

```powershell
# 停止所有服务 (保留数据)
docker compose down

# 停止并清除数据卷 (谨慎, 会丢失所有业务数据)
docker compose down -v

# 重启单个服务 (修改配置后)
docker compose restart api

# 查看实时日志
docker compose logs -f api       # API 日志
docker compose logs -f worker    # Celery Worker 日志
docker compose logs -f           # 全部服务日志
```

---

## 六、功能说明

### 6.1 仪表盘 (Dashboard)

首页自动展示。包含产量统计、良品率、OEE、工位状态时间线。数据通过 SSE 实时更新。

### 6.2 工时分析

侧边栏点击"工时分析"。展示各工位工时统计、动素分布图表 (18 种动素)、工时趋势。

### 6.3 产线平衡

侧边栏点击"产线平衡"。展示各工位负荷均衡、瓶颈诊断、ECRS 动素优化建议。

### 6.4 AI 分析

侧边栏点击"AI 分析"。基于 DeepSeek 大模型的智能对话分析。

使用前需要配置 API Key:

1. 编辑 `d:\analyze ai\.env.local`
2. 在 `DEEPSEEK_API_KEY=` 后填入你的 DeepSeek API Key
3. 重启服务: `docker compose restart api worker`
4. 刷新页面即可使用

留空则 AI 功能禁用, 其他功能不受影响。

### 6.5 业务管理模块

| 模块 | 侧边栏入口 | 功能 |
|------|-----------|------|
| 订单管理 | 订单管理 | 订单增删改查, 按状态/优先级筛选 |
| 客户管理 | 客户管理 | 客户信息管理, 关联订单统计 |
| 库存管理 | 库存管理 | 物料查询, 入库/出库操作, 低库存预警 |
| 设备管理 | 设备管理 | 设备台账, 状态统计 |
| 报告中心 | 报告中心 | 导出工时分析 PDF、产线平衡 PDF |

---

## 七、摄像头接入 (比赛现场)

比赛现场需要接入真实摄像头进行动作识别时:

### 7.1 Windows 端准备

需要安装 usbipd-win 将 USB 摄像头桥接到 WSL2:

```powershell
# 1. 安装 usbipd-win (管理员 PowerShell)
winget install --interactive --exact dorssel.usbipd-win

# 2. 列出可用 USB 设备
usbipd list

# 3. 绑定摄像头 (替换为实际 BUSID)
usbipd bind --busid <BUSID>

# 4. 附加到 WSL
usbipd attach --wsl --busid <BUSID>
```

### 7.2 启动感知服务

```powershell
# 启动全部服务 (包含 perception)
docker compose --env-file .env.local up -d
```

### 7.3 修改摄像头配置

编辑 `d:\analyze ai\mes-backend\config.yaml`:

```yaml
cameras:
  - device_id: 0
    name: "Camera_0"
    enabled: true
    resolution_width: 1280
    resolution_height: 720
    fps: 30
    backend: "auto"
```

修改后重启: `docker compose restart perception`

### 7.4 数据流

```
USB 摄像头
    |
    v
mes-perception (MediaPipe 姿态检测 + 动作分类)
    |
    v  (Redis Stream)
mes-api (业务逻辑 + 工时统计)
    |
    v
InfluxDB (时序存储) + SQLite (业务数据)
    |
    v
前端页面 (实时展示)
```

---

## 八、内存管理

本机 16 GB RAM, Docker 服务内存分配:

| 服务 | 内存上限 | 说明 |
|------|---------|------|
| Windows 系统 | ~4 GB | 含 WSL2 开销 |
| redis | 600 MB | 消息总线 |
| influxdb | 1 GB | 时序数据库 |
| api | 2 GB | API 主进程 |
| perception | 1.5 GB | 视频感知 (可关闭) |
| worker | 1 GB | Celery 异步任务 |
| beat | 128 MB | 定时调度 |
| frontend | 256 MB | Nginx |
| 合计 | ~10 GB | 预留 6 GB 给系统和浏览器 |

如果系统卡顿:

1. 先关闭 perception (不接摄像头时): `docker compose stop perception`
2. 关闭浏览器不需要的标签页
3. 检查任务管理器中其他占用内存的程序

---

## 九、配置文件速查

| 文件 | 路径 | 用途 |
|------|------|------|
| 环境变量 | `d:\analyze ai\.env.local` | 端口、密钥、API Key 等 |
| 摄像头配置 | `d:\analyze ai\mes-backend\config.yaml` | 摄像头参数、姿态检测参数 |
| Docker 编排 | `d:\analyze ai\docker-compose.yml` | 服务定义、资源限制 |
| 环境变量模板 | `d:\analyze ai\docker\.env.template` | 所有可配置变量的说明 |

修改 `.env.local` 或 `config.yaml` 后需要重启对应服务。

修改 `docker-compose.yml` 后需要: `docker compose down && docker compose --env-file .env.local up -d`

---

## 十、常见问题

### Q: 浏览器打不开 localhost

确认 Docker Desktop 正在运行 (系统托盘有鲸鱼图标), 且服务已启动: `docker compose ps`

### Q: 前端页面空白或 502

API 服务可能还在启动中。等待 30 秒后刷新页面。检查: `docker compose logs api`

### Q: 登录失败, 提示密码错误

确认 API 服务正常运行。默认账号 admin/changeme。如果之前加载过演示数据, 使用演示数据中的账号。

### Q: Dashboard 没有数据

需要先加载演示数据: `docker exec mes-api python -m scripts.seed_demo_data`

### Q: AI 分析功能报错或无响应

编辑 `.env.local`, 填入有效的 DEEPSEEK_API_KEY, 然后 `docker compose restart api worker`。

### Q: 内存不够, 系统很卡

关闭 perception 服务 (不接摄像头时): `docker compose stop perception`, 可释放约 1.5 GB。

### Q: 修改了代码, 如何更新

后端修改:
```powershell
docker compose build api worker beat
docker compose up -d api worker beat
```

前端修改:
```powershell
docker compose build frontend
docker compose up -d frontend
```

### Q: 如何彻底重置系统

```powershell
docker compose down -v          # 停止并删除所有数据
docker compose --env-file .env.local up -d   # 重新启动
docker exec mes-api python -m scripts.seed_demo_data  # 重新加载演示数据
```

---

## 十一、比赛演示建议

### 演示流程

1. 提前 15 分钟到达, 启动系统: `docker compose --env-file .env.local up -d`
2. 加载演示数据: `docker exec mes-api python -m scripts.seed_demo_data`
3. 浏览器打开 http://localhost, 确认各页面正常
4. 演示时展示: Dashboard -> 工时分析 -> 产线平衡 -> AI 分析 (如有 API Key)
5. 如需展示视频感知, 提前接好摄像头并测试 perception 服务

### 备用方案

- 如果现场网络不好, 提前下载好 Docker 镜像 (docker save/load)
- 如果投影仪只有 HDMI, 准备 Type-C/HDMI 转接头
- 如果电脑突然重启, Docker Desktop 会自动启动, 手动 `docker compose up -d` 即可恢复
