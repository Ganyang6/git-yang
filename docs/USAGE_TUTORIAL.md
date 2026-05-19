# MES 边缘AI作业工时测定系统 -- 使用教程

> 本教程面向团队成员，介绍如何在这台电脑上启动和使用系统。
> 系统运行环境：Windows 11 + WSL2 + Docker Compose，内存 16GB。

---

## 一、启动系统

### 1.1 打开 WSL2 终端

任选一种方式：

**方式 A（推荐）**：按 `Win` 键，输入 `Ubuntu`，点击 Ubuntu 应用图标。

**方式 B**：打开 Windows Terminal（按 Win 输入 `terminal`），选择或新建 Ubuntu 标签页。

**方式 C**：打开 PowerShell 或 CMD，输入 `wsl` 回车。

### 1.2 进入项目目录

```bash
cd "/mnt/d/analyze ai"
```

注意路径用引号包起来，因为有空格。

### 1.3 一键启动

```bash
docker compose --env-file .env.local up -d
```

这会启动 7 个服务：

| 服务 | 作用 | 内存限制 | 启动端口 |
|------|------|---------|---------|
| redis | 消息队列 + 缓存 | 600MB | 仅内部 |
| influxdb | 时序数据库（存工时数据） | 1GB | 8086（本地） |
| api | 后端 API 服务 | 2GB | 8000 |
| perception | 摄像头感知（AI 姿态识别） | 1.5GB | 无 |
| worker | 异步任务处理（AI 分析等） | 1GB | 无 |
| beat | 定时任务调度 | 128MB | 无 |
| frontend | 前端网页（Nginx） | 256MB | 80 |

首次启动需要约 2-3 分钟（拉取镜像、健康检查）。
后续启动约 30 秒。

### 1.4 检查状态

```bash
docker compose ps
```

所有服务的 STATUS 列应显示 `healthy` 或 `running`。如果有 `unhealthy` 或 `restarting`，看日志排查：

```bash
docker compose logs api      # 看 API 日志
docker compose logs perception  # 看感知日志
docker compose logs frontend   # 看前端日志
```

### 1.5 停止系统

```bash
docker compose down          # 停止所有容器（数据保留）
docker compose down -v       # 停止并删除数据卷（慎用！会清空数据库）
```

---

## 二、访问系统

### 2.1 打开浏览器

在 Windows 浏览器（Chrome/Edge）中访问：

```
http://localhost
```

这会打开前端页面，自动跳转到登录页。

### 2.2 登录

| 项目 | 值 |
|------|-----|
| 用户名 | `admin` |
| 密码 | `changeme` |

登录成功后会进入仪表盘（Dashboard）。

> 注意：这是开发环境的默认密码。如果密码不对，检查 `.env.local` 中是否设置了 `DEFAULT_ADMIN_PASSWORD`。

### 2.3 后台 API 文档

如果需要查看或调试 API，访问：

```
http://localhost:8000/docs
```

这是 FastAPI 自动生成的交互式 API 文档（Swagger UI），可以直接在网页上测试每个接口。

---

## 三、系统功能介绍

系统共 10 个页面，通过左侧导航栏切换：

### 3.1 仪表盘（Dashboard）

系统首页，展示关键指标概览：
- 当日产量、工时统计
- 产线平衡率
- 设备运行状态
- 最近订单动态

### 3.2 工时分析（WorktimeAnalysis）

核心功能页面，展示 AI 识别出的作业工时数据：
- 按工站、班次、日期筛选工时记录
- 每条记录包含：作业人员、工站、开始/结束时间、动作分类、有效/无效判定
- 动素分析数据（伸手、搬运、装配等 17 种动素的时长和占比）
- 支持导出 PDF 报告

### 3.3 产线平衡（LineBalance）

分析各工站的负荷均衡情况：
- 产线平衡率柱状图
- 各工站标准工时 vs 实际工时对比
- 瓶颈工站识别
- ECRS 改善建议（取消、合并、重排、简化）

### 3.4 AI 分析（AiAnalysis）

AI 智能分析功能：
- 工时优化建议（基于 ECRS 原则）
- 产线改善方案生成
- 对话式问答（向 AI 提问关于工时、产线、动素的问题）
- 异步任务：复杂分析会以后台任务形式执行，可在页面上查看进度

> 注意：AI 功能需要配置 DeepSeek API Key 才能使用。如果没配置，页面会提示 API Key 缺失。

### 3.5 订单管理（Orders）

生产订单管理：
- 查看订单列表（订单号、客户、产品、数量、状态）
- 筛选：按状态（已完成/进行中/待生产）、客户、日期
- 订单详情

### 3.6 客户管理（Customers）

客户信息管理：
- 客户列表（名称、联系人、电话、城市、等级）
- 客户类型区分（战略客户/普通客户/VIP）

### 3.7 库存管理（Inventory）

物料库存管理：
- 库存物料列表（编码、名称、规格、数量、安全库存）
- 出入库记录

### 3.8 设备管理（Equipment）

设备运行监控：
- 设备列表（名称、型号、车间、状态）
- OEE（设备综合效率）指标
- 设备状态：运行中 / 空闲 / 维修 / 故障

### 3.9 报表（Reports）

数据报表导出：
- PDF 格式报表导出
- 按时间段生成工时汇总报表

### 3.10 登录页（Login）

系统登录入口，JWT 认证。

---

## 四、摄像头感知功能

### 4.1 硬件要求

- USB 摄像头（任何普通 webcam 都行）
- 摄像头需被 WSL2 识别

### 4.2 检查摄像头

```bash
# 在 WSL2 中检查摄像头设备
ls /dev/video*
```

如果能看到 `/dev/video0`，说明摄像头已挂载。

### 4.3 启动感知服务

如果不需要摄像头（只看已有数据和演示功能），可以跳过这一步。

摄像头感知服务（perception）会随 Docker Compose 一起启动。它会：
1. 通过摄像头采集视频帧（30fps）
2. 用 MediaPipe 进行人体姿态估计（33 个骨骼关键点）
3. 用手部检测识别手部动作
4. 将检测结果发布到 Redis Stream
5. 下游消费者自动进行动作分类和工时计算

### 4.4 常见问题

- **摄像头不被 WSL2 识别**：需要在 Windows 的 Device Manager 中确认摄像头驱动正常，然后重启 WSL2（`wsl --shutdown` 后重新打开）
- **perception 容器一直 restarting**：说明摄像头没挂载成功。可以先停止它：`docker compose stop perception`，不影响其他功能
- **没有实体摄像头**：系统仍然可以正常使用，只是不会有实时感知数据。可以用演示数据来展示功能。

---

## 五、演示数据

系统默认数据库是空的，需要导入演示数据才能看到完整的图表和功能。

### 5.1 导入演示数据

```bash
# 进入 API 容器
docker compose exec api bash

# 运行演示数据填充脚本
python -m scripts.seed_demo_data

# 退出容器
exit
```

演示数据包含：
- 8 家客户（含战略客户和普通客户）
- 30+ 生产订单
- 8 台设备（不同状态）
- 8 种库存物料
- 500+ 工序段数据（3+ 天跨度的多工站数据）
- 50+ 工时记录
- 100+ 动素明细

### 5.2 刷新页面

导入数据后，在浏览器中刷新 `http://localhost`，仪表盘和各页面就会显示数据了。

---

## 六、常用操作

### 6.1 查看实时日志

```bash
# 所有服务日志
docker compose logs -f

# 只看某个服务
docker compose logs -f api
docker compose logs -f worker
```

`Ctrl + C` 退出日志查看。

### 6.2 重启某个服务

```bash
docker compose restart api       # 重启 API
docker compose restart frontend  # 重启前端
```

### 6.3 重新构建镜像（代码有更新时）

```bash
docker compose build api         # 重新构建 API
docker compose build frontend    # 重新构建前端
docker compose up -d             # 用新镜像重启
```

### 6.4 进入容器内部调试

```bash
docker compose exec api bash     # 进入 API 容器
docker compose exec worker bash  # 进入 Worker 容器
```

### 6.5 清空所有数据重来

```bash
docker compose down -v           # 删除所有容器和数据卷
docker compose --env-file .env.local up -d  # 重新启动（数据库会重新创建）
# 然后重新导入演示数据（见第五章）
```

---

## 七、端口说明

| 端口 | 服务 | 用途 |
|------|------|------|
| 80 | frontend | 前端网页（浏览器访问入口） |
| 8000 | api | 后端 API + 文档 |
| 8086 | influxdb | InfluxDB 管理界面（仅本地） |

> 所有端口都绑定在 localhost（127.0.0.1），外部网络无法直接访问。

---

## 八、快速启动清单

每次要用系统时，按这个顺序操作：

1. 打开 WSL2 终端（`Win + R` -> `wsl`）
2. `cd "/mnt/d/analyze ai"`
3. `docker compose --env-file .env.local up -d`
4. 等 30 秒让所有服务启动
5. 浏览器打开 `http://localhost`
6. 用 admin / changeme 登录

用完了：

1. WSL2 终端里 `docker compose down`
2. 关掉浏览器就行

---

## 九、故障排除

| 问题 | 原因 | 解决方法 |
|------|------|---------|
| 浏览器打不开 localhost | Docker 没启动或前端没启动 | 检查 `docker compose ps`，看 frontend 是否 healthy |
| 登录密码不对 | 修改过环境变量 | 检查 `.env.local` 中的 `DEFAULT_ADMIN_PASSWORD` |
| 页面空白或报错 | API 服务异常 | `docker compose logs api` 看日志 |
| 图表没数据 | 没导入演示数据 | 参照第五章导入 |
| perception 一直 restarting | 摄像头没挂载 | `docker compose stop perception` 跳过 |
| 内存不足 | 7 个服务总共需要约 6.5GB | 关掉其他程序，或停掉不需要的服务（如 `docker compose stop perception beat`） |
| 端口被占用 | 80 或 8000 端口被其他程序占用 | 修改 `.env.local` 中的 `FRONTEND_PORT` 和 `API_PORT` |

---

## 十、系统架构简图

```
[摄像头] --> [perception] --Redis Stream--> [api] --> [SQLite + InfluxDB]
                                                |
                                           [worker] (异步AI任务)
                                                |
                                           [beat] (定时调度)
                                                |
                                          [frontend] (浏览器)
```

- **perception**：采集视频 -> MediaPipe 识别 -> 发到 Redis
- **api**：接收数据 -> 动作分类 -> 工时计算 -> 存数据库 -> 返回给前端
- **worker**：处理耗时任务（AI 分析、PDF 生成等）
- **frontend**：Vue3 单页应用，通过 API 与后端通信

---

## 十一、视频文件回放模式

### 11.1 背景与用途

比赛环境不一定有合适的工位和摄像头。视频回放模式允许你录制操作视频后回放分析，实现可重复的对比试验。

系统支持 mp4、avi、mov、mkv 等格式（OpenCV 默认支持）。

### 11.2 准备视频文件

将视频文件放入 `data/videos/` 目录：

```bash
# 将视频文件复制到 videos 目录
cp /path/to/your/video.mp4 data/videos/assembly_line.mp4
```

### 11.3 配置环境变量

编辑 `.env.local`：

```bash
# 启用视频回放模式
VIDEO_MODE=true

# 设置视频路径（容器内的路径，不要改）
VIDEO_PATH=/app/data/videos/assembly_line.mp4

# 设置工站 ID
STATION_ID=WS-01
```

### 11.4 启动系统

```bash
# 停止现有服务（如果有）
docker compose down

# 重新启动
docker compose --env-file .env.local up -d
```

### 11.5 查看视频回放进度

```bash
# 查看 perception 日志
docker compose logs -f perception
```

日志会显示：
- 视频信息（分辨率、FPS、总帧数、时长）
- 每秒处理进度
- 每轮播放结束统计（处理帧数、姿态检测帧数、FPS）
- 是否启用循环播放

### 11.6 配置项说明

| 配置项 | 说明 | 示例值 |
|--------|------|--------|
| VIDEO_MODE | 是否启用视频回放 | `true` / `false` |
| VIDEO_PATH | 视频文件路径（容器内） | `/app/data/videos/assembly_line.mp4` |
| STATION_ID | 工站标识 | `WS-01` |

### 11.7 config.yaml 视频配置示例

也可以通过 `config.yaml` 配置视频源（与 camera 互斥）：

```yaml
# 注释掉摄像头配置，使用视频文件
# cameras:
#   - device_id: 0
#     name: "Camera_0"
#     enabled: true

# 视频文件配置
cameras:
  - video_path: "/app/data/videos/assembly_line.mp4"
    name: "Video_WS01"
    station_id: "WS-01"
    enabled: true
    loop: false          # true = 循环播放
```

### 11.8 对比试验操作流程

1. **录制视频**：在工位录制标准操作视频（建议 1-3 分钟）
2. **导入视频**：将视频放入 `data/videos/` 目录
3. **配置参数**：设置 VIDEO_PATH 和 STATION_ID
4. **启动回放**：启动 Docker Compose，系统自动处理视频
5. **查看结果**：通过前端 Dashboard 和工时分析页面查看结果
6. **对比分析**：修改工艺后重新录制视频，对比两次结果

### 11.9 循环播放

如果需要在演示时持续播放，可以：

1. 设置 `loop: true`（在 config.yaml 中）
2. 或在 docker-compose.yml 中设置环境变量：
   ```yaml
   environment:
     - LOOP=true
   ```

### 11.10 常见问题

| 问题 | 原因 | 解决方法 |
|------|------|--------|
| 视频文件找不到 | 路径不对或 volume 未挂载 | 确认 `data/videos/` 目录存在且有视频文件 |
| 视频处理完没数据 | Redis 连接失败 | 检查 Redis 服务是否正常 `docker compose ps redis` |
| 内存不足 | 视频文件太大 | 降低视频分辨率或帧率 |
| 无法识别姿态 | 视频中人太小/光线差 | 录制时确保人物占画面 1/3 以上 |

