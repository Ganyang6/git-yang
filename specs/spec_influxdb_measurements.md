# 技术规范：InfluxDB Measurement 结构

> 版本：1.0 | 状态：已接受 | 角色：后端服务层（写入者）、前端（查询者，通过API间接受益）
>
> 本规范定义了 InfluxDB 中所有 measurement 的名称、tag/field 结构、数据类型、写入频率和保留策略。所有写入 InfluxDB 的模块必须严格遵守此契约。

---

## 1. 配置参数

| 参数 | 值 | 说明 |
|---|---|---|
| Organization | `mes-factory` | InfluxDB 组织名 |
| Bucket (热数据) | `metrics` | 原始指标存储 |
| Bucket (冷数据) | `metrics_longterm` | 降采样历史数据 |
| 热数据 Retention | `30d` | 30天自动过期 |
| 冷数据 Retention | `365d` | 365天自动过期 |
| 写入精度 | 毫秒（ms） | 统一使用毫秒级时间戳 |
| 协议 | InfluxDB 2.x Line Protocol | 通过 InfluxDB Python Client 写入 |

---

## 2. Measurement 详细定义

### 2.1 `pose_landmarks` -- 姿态关键点时序

**写入频率**：30fps x N路摄像头（与帧采集同步）  
**写入者**：感知进程（或动作分类模块转发）  
**数据量估算**：4路 x 30fps x 86400s = ~10,368,000 points/day

**Line Protocol 格式**：
```
pose_landmarks,camera_id=cam_01,landmark_name=LEFT_WRIST avg_x=0.5123,avg_y=0.6234,avg_z=-0.0456,avg_visibility=0.985,sample_count=1 1743561600123
```

**Tag 定义**（索引字段，用于过滤查询）：

| Tag | 类型 | 说明 |
|---|---|---|
| `camera_id` | string | 摄像头标识，如 `cam_01` |
| `landmark_name` | string | 关键点名称，枚举值见 Redis Stream 规范中的 33 点列表 |

**Field 定义**（数据字段，用于聚合计算）：

| Field | 类型 | 单位 | 说明 |
|---|---|---|---|
| `avg_x` | float | 归一化 | 关键点 x 坐标（多帧内均值） |
| `avg_y` | float | 归一化 | 关键点 y 坐标（多帧内均值） |
| `avg_z` | float | 归一化 | 关键点 z 坐标（多帧内均值） |
| `avg_visibility` | float | - | 检测置信度 [0.0, 1.0] |
| `sample_count` | integer | frames | 采样帧数（聚合时使用） |

> 注意：每帧写入 33 个点（每个关键点一行），写入时可将多帧聚合为1秒窗口写入一次以降低写入压力（33 points/s 而非 990 points/s），此时 `sample_count` 为窗口内帧数。

---

### 2.2 `action_classifications` -- 动作分类结果

**写入频率**：1次/秒（滑动窗口分类频率）  
**写入者**：动作分类模块  
**数据量估算**：1 x 86400 = ~86,400 points/day

**Line Protocol 格式**：
```
action_classifications,camera_id=cam_01,station_id=station_03,action=assemble,dominant_region=upper_body confidence=0.89,duration_in_window_ms=500,window_size=30 1743561600123
```

**Tag 定义**：

| Tag | 类型 | 说明 |
|---|---|---|
| `camera_id` | string | 摄像头标识 |
| `station_id` | string | 工位标识 |
| `action` | string | 动作标签，枚举：`reach`/`grasp`/`move`/`assemble`/`release`/`inspect`/`wait`/`idle` |
| `dominant_region` | string | 优势身体区域：`upper_body`/`full_body`/`none` |

**Field 定义**：

| Field | 类型 | 单位 | 说明 |
|---|---|---|---|
| `confidence` | float | - | 分类置信度 [0.0, 1.0] |
| `duration_in_window_ms` | float | ms | 窗口内该动作持续时间 |
| `window_size` | integer | frames | 滑动窗口大小 |

---

### 2.3 `realtime_metrics` -- 实时生产指标

**写入频率**：1次/秒  
**写入者**：指标计算模块  
**数据量估算**：1 x 86400 = ~86,400 points/day（per station）

**Line Protocol 格式**：
```
realtime_metrics,station_id=station_03,shift=morning human_utilization=0.78,oee=0.85,human_machine_sync=0.72,wait_ratio=0.12,current_action="assemble",segment_duration_ms=5200,line_balance_rate=0.88,smoothness_index=3.42,bottleneck_flag=0 1743561600123
```

**Tag 定义**：

| Tag | 类型 | 说明 |
|---|---|---|
| `station_id` | string | 工位标识 |
| `shift` | string | 班次：`morning`/`afternoon`/`night` |

**Field 定义**：

| Field | 类型 | 单位 | 说明 |
|---|---|---|---|
| `human_utilization` | float | - | 人工稼动率 [0.0, 1.0] |
| `oee` | float | - | 设备综合效率 [0.0, 1.0] |
| `human_machine_sync` | float | - | 人机协同率 [0.0, 1.0] |
| `wait_ratio` | float | - | 等待时间占比 [0.0, 1.0] |
| `current_action` | string | - | 当前动作（InfluxDB 2.x field 中 string 类型需加引号） |
| `segment_duration_ms` | float | ms | 当前工序段已持续毫秒数 |
| `line_balance_rate` | float | - | 产线平衡率 [0.0, 1.0]，仅主工位有值 |
| `smoothness_index` | float | - | 平滑指数，值越小越好 |
| `bottleneck_flag` | integer | - | 瓶颈标记：1=当前工位是瓶颈，0=正常 |

---

### 2.4 `segment_events` -- 工序段事件

**写入频率**：事件驱动（~0.5-2次/秒）  
**写入者**：动作分类模块 / 工时聚合模块  
**数据量估算**：~100,000 points/day

**Line Protocol 格式**：
```
segment_events,camera_id=cam_01,station_id=station_03,action=assemble,therblig_symbol=A,shift=morning duration_ms=15450,confidence=0.89,mod_value=5.0,standard_ms=645,is_waste=0 1743561615450
```

**Tag 定义**：

| Tag | 类型 | 说明 |
|---|---|---|
| `camera_id` | string | 摄像头标识 |
| `station_id` | string | 工位标识 |
| `action` | string | 动作标签 |
| `therblig_symbol` | string | Therblig 符号（R/M/G/RL/A/I/UD/AD 等） |
| `shift` | string | 班次 |

**Field 定义**：

| Field | 类型 | 单位 | 说明 |
|---|---|---|---|
| `duration_ms` | float | ms | 工序段持续时间 |
| `confidence` | float | - | 分类置信度 |
| `mod_value` | float | MOD | 对应 MOD 标准工时值 |
| `standard_ms` | float | ms | 标准工时（mod_value x 0.129 x 1000） |
| `is_waste` | integer | - | 是否浪费：1=是，0=否 |

---

### 2.5 `therblig_distribution` -- 动素分布聚合

**写入频率**：5分钟一次  
**写入者**：工时聚合模块  
**数据量估算**：12 x 24 = 288 points/day

**Line Protocol 格式**：
```
therblig_distribution,station_id=station_03,shift=morning,symbol=A reach_pct=15.2,grasp_pct=8.3,move_pct=12.1,assemble_pct=35.6,release_pct=9.8,inspect_pct=7.2,wait_pct=8.5,idle_pct=3.3 1743561600123
```

**Tag 定义**：

| Tag | 类型 | 说明 |
|---|---|---|
| `station_id` | string | 工位标识 |
| `shift` | string | 班次 |
| `symbol` | string | 聚合窗口标识 |

**Field 定义**（每种动素一个 field）：

| Field | 类型 | 单位 | 说明 |
|---|---|---|---|
| `reach_pct` | float | % | 伸手动作占比 |
| `grasp_pct` | float | % | 抓取动作占比 |
| `move_pct` | float | % | 搬运动作占比 |
| `assemble_pct` | float | % | 装配动作占比 |
| `release_pct` | float | % | 释放动作占比 |
| `inspect_pct` | float | % | 检验动作占比 |
| `wait_pct` | float | % | 等待占比 |
| `idle_pct` | float | % | 空闲占比 |

---

### 2.6 `system_health` -- 系统健康指标

**写入频率**：10秒一次  
**写入者**：API 主进程（系统监控组件）  
**数据量估算**：8640 points/day

**Line Protocol 格式**：
```
system_health,service=api cpu_usage=0.45,memory_mb=1024,active_connections=12,request_latency_ms=5.2,error_rate=0.001,uptime_seconds=86400 1743561600123
```

**Tag 定义**：

| Tag | 类型 | 说明 |
|---|---|---|
| `service` | string | 服务名称：`api`/`perception`/`worker`/`redis`/`influxdb` |

**Field 定义**：

| Field | 类型 | 单位 | 说明 |
|---|---|---|---|
| `cpu_usage` | float | - | CPU 使用率 [0.0, 1.0] |
| `memory_mb` | float | MB | 内存使用量 |
| `active_connections` | integer | count | 活跃连接数 |
| `request_latency_ms` | float | ms | 请求平均延迟（API专用） |
| `error_rate` | float | - | 错误率 [0.0, 1.0] |
| `uptime_seconds` | integer | s | 服务运行时长 |
| `pel_count` | integer | count | Redis Stream PEL 积压消息数（仅 redis） |
| `stream_lag_ms` | float | ms | 消息消费延迟（仅 redis） |

---

## 3. 降采样策略

热数据 bucket (`metrics`) 30天后自动过期。过期前通过 InfluxDB Task 执行降采样，将数据写入冷数据 bucket (`metrics_longterm`)。

### 3.1 1分钟降采样

```
-- 对 realtime_metrics 执行每分钟聚合
SELECT mean("human_utilization") AS human_utilization,
       mean("oee") AS oee,
       mean("human_machine_sync") AS human_machine_sync,
       mean("wait_ratio") AS wait_ratio,
       mean("line_balance_rate") AS line_balance_rate
INTO "metrics_longterm"."autogen"."realtime_metrics_1m"
FROM "metrics"."autogen"."realtime_metrics"
GROUP BY time(1m), "station_id", "shift"
```

### 3.2 1小时降采样

```
SELECT mean("human_utilization") AS human_utilization,
       mean("oee") AS oee,
       mean("wait_ratio") AS wait_ratio,
       max("line_balance_rate") AS line_balance_rate
INTO "metrics_longterm"."autogen"."realtime_metrics_1h"
FROM "metrics"."autogen"."realtime_metrics_1m"
GROUP BY time(1h), "station_id", "shift"
```

---

## 4. 常用查询模式

### 4.1 实时查询（前端 WebSocket 推送用）

```python
from influxdb_client import QueryApi

query = '''
from(bucket: "metrics")
  |> range(start: -10s)
  |> filter(fn: (r) => r._measurement == "realtime_metrics")
  |> filter(fn: (r) => r.station_id == "station_03")
  |> last()
'''
```

### 4.2 趋势查询（前端看板图表用）

```python
query = '''
from(bucket: "metrics")
  |> range(start: -1h)
  |> filter(fn: (r) => r._measurement == "realtime_metrics")
  |> filter(fn: (r) => r.station_id == "station_03")
  |> aggregateWindow(every: 1m, fn: mean)
'''
```

### 4.3 工序段历史查询

```python
query = '''
from(bucket: "metrics")
  |> range(start: -8h)
  |> filter(fn: (r) => r._measurement == "segment_events")
  |> filter(fn: (r) => r.station_id == "station_03")
  |> sort(columns: ["_time"])
'''
```

---

## 5. 写入规范

### 5.1 批量写入

所有写入必须使用批量模式（`write_api.write(bucket="metrics", record=batch)`），单次批量不超过 5000 points，写入间隔不超过 1 秒。

### 5.2 精度与格式

- 时间戳：Unix 毫秒（13位整数）
- float 精度：保留4位小数
- string field 值在 Line Protocol 中需加双引号
- tag 值不加引号
- measurement 和 tag 名称使用小写字母 + 下划线

### 5.3 错误处理

写入失败时记录日志并重试（最多3次，指数退避）。连续失败超过 10 次时写入 `mes:system_events` Stream 触发告警。不阻塞主数据流 -- 指标数据允许短暂丢失。

---

## 6. 存储量估算

| Measurement | Points/s | Points/day | 存储估算(30d) |
|---|---|---|---|
| `pose_landmarks` | 132 (聚合后) | 11,395,200 | ~1.5 GB |
| `action_classifications` | 1 | 86,400 | ~15 MB |
| `realtime_metrics` | 1/station | 86,400 | ~15 MB |
| `segment_events` | 1.5 | 129,600 | ~20 MB |
| `therblig_distribution` | 0.003 | 288 | <1 MB |
| `system_health` | 0.1 | 8,640 | ~2 MB |
| **合计** | ~135 | ~11.7M | **~1.6 GB/30d** |

> 注意：pose_landmarks 是存储大户。如果磁盘空间紧张，可降低写入频率（从每帧写入改为每秒聚合写入），或启用 InfluxDB 的压缩功能（默认已启用 TSM 引擎压缩）。
