# 技术规范：Redis Stream 消息格式

> 版本：1.0 | 状态：已接受 | 角色：后端服务层（生产者）、感知进程（生产者）、前端（消费者，通过WebSocket间接受益）
>
> 本规范定义了系统中所有 Redis Stream 的名称、消息字段结构、消费者组配置和可靠性保障机制。所有角色必须严格遵守此契约。

---

## 1. Stream 总览

| Stream Key | 生产者 | 消费者 | 频率 | 消息大小(估) |
|---|---|---|---|---|
| `mes:pose_frames` | 感知进程 | 动作分类模块 | ~120 msg/s (4路x30fps) | ~2 KB |
| `mes:action_events` | 动作分类模块 | 指标计算 / 工时聚合 | ~0.5-2 msg/s | ~0.5 KB |
| `mes:metrics` | 指标计算模块 | WebSocket 推送 / InfluxDB 写入 | 1 msg/s | ~1 KB |
| `mes:analysis_tasks` | API 主进程 | Celery Worker | 按需（用户触发） | ~2 KB |
| `mes:analysis_results` | Celery Worker | WebSocket 推送 | 按需 | ~5 KB |
| `mes:system_events` | 所有模块 | 日志 / 告警 / SSE 推送 | 低频 | ~0.3 KB |

---

## 2. Stream 详细格式

### 2.1 `mes:pose_frames` -- 姿态帧数据

**来源**：感知进程（camera_manager + pose_estimator + hand_estimator），每帧写入一次。

**消费者组**：`cg:action_classifier`（动作分类模块消费）

**XADD 命令**：
```
XADD mes:pose_frames * \
  camera_id "cam_01" \
  timestamp "1743561600.123" \
  frame_id "0000012345" \
  landmark_count "33" \
  pose_score "0.92" \
  hand_count "2" \
  landmarks "<JSON>"
```

**字段定义**：

| 字段 | 类型 | 必填 | 说明 |
|---|---|---|---|
| `camera_id` | string | 是 | 摄像头标识，格式 `cam_XX`，XX为两位数字 |
| `timestamp` | string | 是 | 帧采集时间，Unix epoch 秒，精度到毫秒（小数点后3位） |
| `frame_id` | string | 是 | 全局唯一帧序号，20位零填充递增整数 |
| `landmark_count` | string | 是 | 关键点数量（Pose 33 / Hand 21 per hand） |
| `pose_score` | string | 是 | MediaPipe 检测置信度，范围 [0.0, 1.0] |
| `hand_count` | string | 否 | 检测到的手数量，0/1/2 |
| `hand_landmarks` | string | 否 | 手部关键点 JSON（Phase 8 新增），结构同 landmarks |
| `hand_features` | string | 否 | 手部特征 JSON（Phase 8 新增），含 grip_strength/pinch_distance/finger_spread |
| `landmarks` | string | 是 | 关键点数据 JSON，结构见下方 |

**`landmarks` JSON 结构**（Pose 关键点）：
```json
[
  {
    "name": "NOSE",
    "index": 0,
    "x": 0.5234,
    "y": 0.3121,
    "z": -0.0123,
    "visibility": 0.995
  },
  {
    "name": "LEFT_SHOULDER",
    "index": 11,
    "x": 0.4102,
    "y": 0.3567,
    "z": -0.0891,
    "visibility": 0.980
  }
]
```

Pose 关键点名称枚举（共33个，index 0-32）：
```
NOSE=0, LEFT_EYE_INNER=1, LEFT_EYE=2, LEFT_EYE_OUTER=3,
RIGHT_EYE_INNER=4, RIGHT_EYE=5, RIGHT_EYE_OUTER=6,
LEFT_EAR=7, RIGHT_EAR=8, MOUTH_LEFT=9, MOUTH_RIGHT=10,
LEFT_SHOULDER=11, RIGHT_SHOULDER=12,
LEFT_ELBOW=13, RIGHT_ELBOW=14,
LEFT_WRIST=15, RIGHT_WRIST=16,
LEFT_PINKY=17, RIGHT_PINKY=18,
LEFT_INDEX=19, RIGHT_INDEX=20,
LEFT_THUMB=21, RIGHT_THUMB=22,
LEFT_HIP=23, RIGHT_HIP=24,
LEFT_KNEE=25, RIGHT_KNEE=26,
LEFT_ANKLE=27, RIGHT_ANKLE=28,
LEFT_HEEL=29, RIGHT_HEEL=30,
LEFT_FOOT_INDEX=31, RIGHT_FOOT_INDEX=32
```

**坐标系**：归一化坐标，x/y 范围 [0.0, 1.0]（左上角为原点），z 为相对深度，visibility 为检测置信度。

**MAXLEN 配置**：
```
XADD mes:pose_frames MAXLEN ~ 3600 * ...
```
保留最近3600条消息（约30秒缓冲），防止消费延迟导致内存溢出。

---

### 2.2 `mes:action_events` -- 动作/工序事件

**来源**：动作分类模块（ActionPipeline），工序状态机确认动作切换时写入。

**消费者组**：`cg:metric_calculator`（指标计算模块消费）

**XADD 命令**：
```
XADD mes:action_events * \
  event_id "evt_0042" \
  camera_id "cam_01" \
  station_id "station_03" \
  action "assemble" \
  therblig_symbol "A" \
  therblig_name "assemble" \
  start_time "1743561600.000" \
  end_time "1743561615.450" \
  duration_ms "15450" \
  confidence "0.89" \
  dominant_region "upper_body" \
  shift "morning"
```

**字段定义**：

| 字段 | 类型 | 必填 | 说明 |
|---|---|---|---|
| `event_id` | string | 是 | 全局唯一事件ID，格式 `evt_XXXXXXXX` |
| `camera_id` | string | 是 | 来源摄像头标识 |
| `station_id` | string | 是 | 工位标识 |
| `action` | string | 是 | 动作分类标签，枚举值见下方 |
| `therblig_symbol` | string | 是 | 对应 Therblig 符号 |
| `therblig_name` | string | 是 | 对应 Therblig 名称 |
| `start_time` | string | 是 | 工序段起始时间，Unix epoch 秒 |
| `end_time` | string | 是 | 工序段结束时间，Unix epoch 秒 |
| `duration_ms` | string | 是 | 工序段持续时间（毫秒） |
| `confidence` | string | 是 | 分类置信度，范围 [0.0, 1.0] |
| `dominant_region` | string | 是 | 优势身体区域：`upper_body` / `full_body` / `none` |
| `shift` | string | 是 | 班次：`morning`(06:00-14:00) / `afternoon`(14:00-22:00) / `night`(22:00-06:00) |

**`action` 枚举值**：

| 值 | 含义 | 对应 Therblig |
|---|---|---|
| `reach` | 伸手 | R (3 MOD) |
| `grasp` | 抓取 | G (1 MOD) |
| `move` | 搬运 | M (4 MOD) |
| `assemble` | 装配 | A (5 MOD) |
| `release` | 释放 | RL (1 MOD) |
| `inspect` | 检验 | I (3 MOD) |
| `wait` | 等待（不可避免） | UD (0 MOD, 测量实际) |
| `idle` | 空闲（可避免） | AD (0 MOD, 测量实际) |

**MAXLEN 配置**：
```
XADD mes:action_events MAXLEN ~ 86400 * ...
```
保留最近86400条（约12小时@2msg/s）。

---

### 2.3 `mes:metrics` -- 实时指标

**来源**：指标计算模块，每秒聚合一次写入。

**消费者组**：`cg:websocket_pusher`（WebSocket 推送服务消费）

**XADD 命令**：
```
XADD mes:metrics * \
  station_id "station_03" \
  timestamp "1743561601.000" \
  current_action "assemble" \
  segment_duration_ms "5200" \
  human_utilization "0.78" \
  oee "0.85" \
  human_machine_sync "0.72" \
  wait_ratio "0.12" \
  line_balance_rate "0.88" \
  smoothness_index "3.42" \
  bottleneck_station "station_05" \
  shift_total_seconds "28800" \
  shift_effective_seconds "22464"
```

**字段定义**：

| 字段 | 类型 | 必填 | 说明 |
|---|---|---|---|
| `station_id` | string | 是 | 工位标识 |
| `timestamp` | string | 是 | 指标计算时刻，Unix epoch 秒 |
| `current_action` | string | 是 | 当前正在执行的动作 |
| `segment_duration_ms` | string | 是 | 当前工序段已持续时间（毫秒） |
| `human_utilization` | string | 是 | 人工稼动率，范围 [0.0, 1.0] |
| `oee` | string | 是 | 设备综合效率，范围 [0.0, 1.0] |
| `human_machine_sync` | string | 是 | 人机协同率，范围 [0.0, 1.0] |
| `wait_ratio` | string | 是 | 等待时间占比，范围 [0.0, 1.0] |
| `line_balance_rate` | string | 否 | 产线平衡率（仅主工位计算），范围 [0.0, 1.0] |
| `smoothness_index` | string | 否 | 平滑指数（仅主工位计算），值越小越好 |
| `bottleneck_station` | string | 否 | 当前瓶颈工位标识 |
| `shift_total_seconds` | string | 是 | 当班次已过总秒数 |
| `shift_effective_seconds` | string | 是 | 当班次有效作业秒数 |

**MAXLEN 配置**：
```
XADD mes:metrics MAXLEN ~ 600 * ...
```
保留最近600条（10分钟缓冲）。

---

### 2.4 `mes:analysis_tasks` -- AI分析任务

**来源**：API 主进程，用户发起AI分析请求时写入。

**消费者组**：`cg:celery_worker`（Celery Worker 消费）

**XADD 命令**：
```
XADD mes:analysis_tasks * \
  task_id "tsk_a1b2c3d4" \
  task_type "bottleneck_diagnosis" \
  station_id "station_03" \
  line_id "line_01" \
  time_start "2026-04-02T08:00:00" \
  time_end "2026-04-02T17:00:00" \
  priority "normal" \
  created_at "1743561600.000"
```

**字段定义**：

| 字段 | 类型 | 必填 | 说明 |
|---|---|---|---|
| `task_id` | string | 是 | 任务唯一ID |
| `task_type` | string | 是 | 分析类型：`bottleneck_diagnosis` / `efficiency_analysis` / `therblig_optimization` / `general_chat` |
| `station_id` | string | 否 | 目标工位 |
| `line_id` | string | 否 | 目标产线 |
| `time_start` | string | 否 | 分析时间范围起点（ISO 8601） |
| `time_end` | string | 否 | 分析时间范围终点（ISO 8601） |
| `priority` | string | 是 | 优先级：`low` / `normal` / `high` |
| `created_at` | string | 是 | 任务创建时间，Unix epoch 秒 |

---

### 2.5 `mes:analysis_results` -- AI分析结果

**来源**：Celery Worker，分析完成后写入。

**消费者组**：`cg:ws_notifier`（WebSocket 通知服务消费）

**XADD 命令**：
```
XADD mes:analysis_results * \
  task_id "tsk_a1b2c3d4" \
  status "completed" \
  model_source "deepseek" \
  duration_ms "12500" \
  result_summary "<文本摘要>" \
  report_id "rpt_e5f6g7h8"
```

**字段定义**：

| 字段 | 类型 | 必填 | 说明 |
|---|---|---|---|
| `task_id` | string | 是 | 对应任务ID |
| `status` | string | 是 | 状态：`completed` / `failed` |
| `model_source` | string | 是 | 模型来源：`deepseek` / `ollama` |
| `duration_ms` | string | 是 | 分析耗时（毫秒） |
| `result_summary` | string | 否 | 结果摘要（用于WebSocket推送预览） |
| `report_id` | string | 否 | 完整报告存储ID（写入SQLite后获得） |
| `error_message` | string | 否 | 失败原因（status=failed时） |

---

### 2.6 `mes:system_events` -- 系统事件

**来源**：所有模块，低频写入。

**消费者组**：`cg:sys_monitor`（监控/日志/SSE推送消费）

**XADD 命令**：
```
XADD mes:system_events * \
  event_type "camera_connected" \
  source "perception" \
  level "info" \
  camera_id "cam_01" \
  message "Camera cam_01 reconnected after 5s timeout" \
  timestamp "1743561600.000"
```

**`event_type` 枚举值**：

| 类别 | event_type | 说明 |
|---|---|---|
| 摄像头 | `camera_connected` | 摄像头连接成功 |
| 摄像头 | `camera_disconnected` | 摄像头断开 |
| 摄像头 | `camera_error` | 摄像头异常 |
| 分类器 | `classifier_error` | 分类器异常 |
| 系统 | `redis_reconnected` | Redis 重连成功 |
| 系统 | `influxdb_write_failed` | InfluxDB 写入失败 |
| 系统 | `model_hotswap` | ONNX 模型热更新完成 |
| 告警 | `bottleneck_alert` | 瓶颈工位告警 |
| 告警 | `oee_below_threshold` | OEE 低于阈值告警 |

---

## 3. 消费者组配置

### 3.1 创建消费者组

```python
import redis

r = redis.Redis(host="redis", port=6379, decode_responses=True)

# 创建消费者组（$ 表示从最新消息开始消费）
groups = [
    ("mes:pose_frames", "cg:action_classifier"),
    ("mes:action_events", "cg:metric_calculator"),
    ("mes:metrics", "cg:websocket_pusher"),
    ("mes:analysis_tasks", "cg:celery_worker"),
    ("mes:analysis_results", "cg:ws_notifier"),
    ("mes:system_events", "cg:sys_monitor"),
]

for stream, group in groups:
    try:
        r.xgroup_create(stream, group, id="$", mkstream=True)
    except redis.ResponseError as e:
        if "BUSYGROUP" in str(e):
            pass  # 消费者组已存在
        else:
            raise
```

### 3.2 消费模式

所有消费者使用阻塞读取（`XREADGROUP BLOCK`），超时 5 秒：

```python
def consume_loop(stream: str, group: str, consumer: str):
    while True:
        messages = r.xreadgroup(
            groupname=group,
            consumername=consumer,
            streams={stream: ">"},
            count=10,
            block=5000,
        )
        for stream_name, msg_list in messages:
            for msg_id, fields in msg_list:
                try:
                    process_message(fields)
                    r.xack(stream, group, msg_id)
                except Exception:
                    # 处理失败，消息留在 PEL 中等待 XCLAIM
                    logger.exception("Failed to process %s", msg_id)
```

### 3.3 PEL（Pending Entries List）监控与恢复

```python
def reclaim_pending(stream: str, group: str, min_idle_ms: int = 60000):
    """重新认领闲置超过 min_idle_ms 的消息。"""
    pending = r.xpending_range(stream, group, min="-", max="+", count=100)
    reclaimed = 0
    for entry in pending:
        if entry["idle"] >= min_idle_ms:
            result = r.xclaim(
                stream, group, "recovery_worker",
                min_idle_time=min_idle_ms,
                message_ids=[entry["message_id"]],
            )
            reclaimed += len(result)
    return reclaimed
```

---

## 4. 可靠性保障

### 4.1 消息持久化

Redis 配置 AOF 持久化，确保断电后消息不丢失：

```conf
appendonly yes
appendfsync everysec
```

### 4.2 幂等性设计

每条消息包含 `frame_id` 或 `event_id` 全局唯一标识，消费端在处理前做去重检查：

```python
processed = r.sadd(f"processed:{stream}", message_id)
if not processed:
    logger.info("Duplicate message %s, skipping", message_id)
    r.xack(stream, group, message_id)
    return
# 设置 TTL 避免集合无限增长
r.expire(f"processed:{stream}", 3600)
```

### 4.3 背压控制

当 PEL 中积压消息超过阈值时，感知进程应自动降频：

```python
pel_count = r.xpending_range("mes:pose_frames", "cg:action_classifier", "-", "+", count=1)
if pel_count and pel_count["count"] > 300:  # >10秒缓冲
    # 跳帧：每3帧只处理1帧
    frame_skip_counter = (frame_skip_counter + 1) % 3
    if frame_skip_counter != 0:
        continue
```

### 4.4 MAXLEN 内存保护

所有 Stream 设置 `MAXLEN ~`（近似裁剪），确保 Redis 内存不超过配置上限：

| Stream | MAXLEN | 对应缓冲时间 |
|---|---|---|
| `mes:pose_frames` | ~3600 | 30秒 |
| `mes:action_events` | ~86400 | ~12小时 |
| `mes:metrics` | ~600 | 10分钟 |
| `mes:analysis_tasks` | ~1000 | 队列缓冲 |
| `mes:analysis_results` | ~1000 | 队列缓冲 |
| `mes:system_events` | ~10000 | 系统日志缓冲 |

---

## 5. 命名规范

- Stream Key：`mes:` 前缀 + 下划线分隔的小写名词，如 `mes:pose_frames`
- 消费者组：`cg:` 前缀 + 下划线分隔的消费者名称，如 `cg:action_classifier`
- 消费者名称：`worker_` + 主机名或实例编号，如 `worker_edge_01`
- 消息字段：下划线分隔的小写名词，如 `camera_id`、`duration_ms`
- 所有字段值均为字符串（Redis Stream 的 Hash field 约束）
