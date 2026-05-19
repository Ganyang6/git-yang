# 感知底座模块 (Perception Foundation)

边缘AI作业工时测定系统的第一阶段核心模块，负责视频数据采集与人体姿态识别。

## 功能特性

### 1. 多摄像头实时采集 (`camera_manager.py`)
- 自动检测可用摄像头
- 配置驱动的参数管理（分辨率、帧率、设备ID）
- 多线程采集，支持热插拔
- 自动重连机制

### 2. 33个人体关键点提取 (`pose_estimator.py`)
- 基于 MediaPipe Pose
- 支持 0/Lite, 1/Full, 2/Heavy 三种模型复杂度
- 关键点平滑处理
- 实时可视化支持

### 3. 帧缓冲队列 (`frame_buffer.py`)
- 线程安全的 FIFO 队列
- 可配置队列大小
- 支持丢弃旧帧模式（保证实时性）
- 端到端延迟统计

### 4. 配置驱动系统 (`config.py` + `config.yaml`)
- 统一配置管理
- 支持 YAML 配置文件
- 默认参数开箱即用

## 验收标准

| 指标 | 标准 | 说明 |
|------|------|------|
| 帧率 | >= 30 FPS | 单摄像头稳定运行 |
| 关键点 | 33 个 | MediaPipe 标准输出 |
| 延迟 | < 33ms | 端到端延迟 |
| 队列 | 实时输出 | 数据进入内存队列 |

## 快速开始

### 1. 安装依赖

```bash
cd mes-backend
pip install -r requirements.txt
```

### 2. 检测摄像头

```bash
python main.py --detect-cameras
```

### 3. 运行实时演示

```bash
python main.py --camera-id 0
```

### 4. 运行性能测试

```bash
python main.py --test-only
```

### 5. 运行验收测试

```bash
python test_validation.py
```

## 配置说明

编辑 `config.yaml`:

```yaml
cameras:
  - device_id: 0
    name: "Camera_0"
    enabled: true
    resolution_width: 1280
    resolution_height: 720
    fps: 30

pose:
  model_complexity: 1      # 0=Lite, 1=Full, 2=Heavy
  smooth: true
  min_detection_confidence: 0.5
  min_tracking_confidence: 0.5

buffer:
  max_queue_size: 10
  drop_old_frames: true

performance:
  target_fps: 30
  max_latency_ms: 33.0
  num_landmarks: 33
```

## MediaPipe 33个关键点

| 编号 | 名称 | 描述 |
|------|------|------|
| 0-10 | Face | 面部 |
| 11-22 | Upper Body | 上半身（肩膀、手臂、手腕） |
| 23-32 | Lower Body | 下半身（髋、膝、踝、脚） |

详细定义见 `pose_estimator.py` 中的 `LandmarkName` 枚举。

## API 使用示例

```python
from camera_manager import CameraManager
from pose_estimator import PoseEstimator
from frame_buffer import FrameBuffer

# 创建组件
camera_manager = CameraManager()
camera = camera_manager.add_camera(device_id=0, resolution=(1280, 720), fps=30)
pose_estimator = PoseEstimator()
frame_buffer = FrameBuffer()

# 打开摄像头
camera.open()

# 采集和处理
ret, frame = camera._cap.read()
pose_result = pose_estimator.estimate(frame)
frame_data = frame_buffer.put(frame, pose_result, camera_id=0)

# 获取结果
latency = frame_buffer.calculate_latency(frame_data)
print(f"检测到 {len(pose_result.landmarks)} 个关键点")
print(f"延迟: {latency:.2f}ms")
```

## 项目结构

```
mes-backend/
├── config.py           # 配置管理
├── config.yaml        # 配置文件
├── camera_manager.py   # 摄像头管理
├── pose_estimator.py   # 姿态识别
├── frame_buffer.py     # 帧缓冲队列
├── main.py             # 主程序入口
├── test_validation.py  # 验收测试
└── requirements.txt   # 依赖列表
```

## 下一步

第二阶段将基于此底座实现：
- 动作分类与工序自动分割
- 人机协作指标计算
- 生产线平衡与瓶颈诊断

---

# Secrets 配置说明

敏感信息通过 Docker Secrets 管理，文件位于 `secrets/` 目录（gitignored，不跟踪）。

## 必需 Secrets 文件

| Secret | 文件 | Docker Compose |
|--------|------|----------------|
| JWT 签名密钥 | `secrets/jwt_secret.key` | `jwt_secret` |
| InfluxDB Token | `secrets/influxdb_token.key` | `influxdb_token` |
| DeepSeek API Key | `secrets/deepseek_api_key.key` | `deepseek_api_key` |
| Redis 密码 | `secrets/redis_password.key` | `redis_password` |
| InfluxDB 管理员密码 | `secrets/influxdb_admin_password.key` | `influxdb_admin_password` |

## 创建 Secrets 文件

```bash
# 生成随机密钥（推荐）
openssl rand -base64 32 > secrets/jwt_secret.key
openssl rand -base64 32 > secrets/influxdb_token.key
openssl rand -base64 32 > secrets/deepseek_api_key.key
openssl rand -base64 16 > secrets/redis_password.key
openssl rand -base64 16 > secrets/influxdb_admin_password.key
```

## Secrets 加载机制

`app/core/config.py` 中的 `_env_or_file()` 函数支持 Docker Secrets 规范：
- 优先读取 `JWT_SECRET_KEY` 环境变量
- 如果未设置，尝试读取 `JWT_SECRET_KEY_FILE` 指向的文件
- 如果都未设置，使用空字符串（启动时会记录警告）

# 环境变量参考

## 必需变量

| 变量 | 说明 | 默认值 |
|------|------|--------|
| `JWT_SECRET_KEY` | JWT HMAC-SHA256 签名密钥 | 无（必须设置） |
| `REDIS_URL` | Redis 连接 URL | `redis://:password@redis:6379/0` |
| `MES_DB_URL` | SQLite 数据库路径 | `sqlite:////app/data/mes.db` |

## 可选变量

| 变量 | 说明 | 默认值 |
|------|------|--------|
| `DEEPSEEK_API_KEY` | DeepSeek API 密钥 | `""` |
| `DEEPSEEK_API_URL` | DeepSeek API 地址 | `""` |
| `INFLUXDB_URL` | InfluxDB 连接 URL | `http://influxdb:8086` |
| `INFLUXDB_TOKEN` | InfluxDB 认证令牌 | `""` |
| `INFLUXDB_ORG` | InfluxDB 组织名 | `mes-factory` |
| `INFLUXDB_BUCKET` | InfluxDB 存储桶 | `metrics` |
| `CELERY_BROKER_URL` | Celery 消息代理 URL | `redis://:password@redis:6379/0` |
| `CELERY_RESULT_BACKEND` | Celery 结果后端 URL | `redis://:password@redis:6379/1` |
| `UPLOAD_MAX_SIZE` | Nginx 上传大小限制（MB） | `500` |
| `REDIS_PASSWORD` | Redis 密码 | `mes-redis-2026` |

## 配置加载优先级

1. `config.yaml` 文件配置（最高优先级）
2. 环境变量（通过 `os.environ.get()`）
3. Docker Secrets 文件（通过 `*_FILE` 环境变量）
4. 默认值（最低优先级）

# Docker Compose 启动指南

## 前置条件

- Docker Engine 24+ 和 Docker Compose v2
- WSL2（Windows 环境）

## 快速启动

```bash
# 1. 克隆项目并进入目录
cd mes-edge-ai

# 2. 创建 Secrets 文件
mkdir -p secrets
openssl rand -base64 32 > secrets/jwt_secret.key
openssl rand -base64 32 > secrets/influxdb_token.key
openssl rand -base64 32 > secrets/deepseek_api_key.key
openssl rand -base64 16 > secrets/redis_password.key
openssl rand -base64 16 > secrets/influxdb_admin_password.key

# 3. 可选：创建 .env.local 覆盖默认配置
cp .env.example .env.local   # 如果存在
vim .env.local               # 根据需要修改

# 4. 启动所有服务
docker compose up -d

# 5. 查看日志
docker compose logs -f

# 6. 停止所有服务
docker compose down
```

## 服务说明

| 服务 | 端口 | 说明 |
|------|------|------|
| `redis` | 6379 | 消息总线 + 缓存 + Celery Broker |
| `influxdb` | 8086 | 时序数据存储 |
| `api` | 8000 | FastAPI 主进程 |
| `perception` | - | 摄像头采集 + MediaPipe 检测 |
| `worker` | - | Celery 异步任务处理 |
| `beat` | - | Celery 定时任务调度 |
| `frontend` | 80 | Nginx 静态文件服务器 + 反向代理 |

## 常用命令

```bash
# 查看所有服务状态
docker compose ps

# 重启单个服务
docker compose restart api

# 查看特定服务日志
docker compose logs -f api

# 重建镜像后启动
docker compose up -d --build

# 清理所有数据（危险！将删除数据库）
docker compose down -v
```
