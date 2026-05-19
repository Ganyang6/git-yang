# 技术规范：指标计算公式

> 版本：1.0 | 状态：已接受 | 角色：后端服务层（计算者）、前端（展示者）、总设计师（规则设计者）
>
> 本规范定义了系统中所有生产指标的数学公式、输入数据源、计算周期和判定阈值。所有指标计算模块和前端看板必须严格遵守此契约。

---

## 1. 符号约定

| 符号 | 含义 | 数据类型 | 来源 |
|---|---|---|---|
| T_total | 统计周期内总时间 | ms | 配置（班次时长） |
| T_effective | 有效作业时间（非等待非空闲） | ms | `segment_events` 聚合 |
| T_wait | 等待时间 | ms | `segment_events` 中 action=wait 的 sum |
| T_idle | 空闲时间 | ms | `segment_events` 中 action=idle 的 sum |
| T_work | 人工作业时间（含装配/检验/搬运等） | ms | `segment_events` 聚合 |
| T_machine | 设备运行时间 | ms | PLC 信号 / 设备状态流 |
| T_overlap | 人机并行作业时间 | ms | T_work 与 T_machine 的交集 |
| N_stations | 工位数量 | integer | 配置 |
| D_i | 第 i 个工位的平均工序时间 | ms | `segment_events` 按 station_id 聚合 |
| t_mod | MOD 标准工时 | ms | Therblig 映射表 x 0.129s x 1000 |
| t_actual | 实测工时 | ms | `segment_events` 中 duration_ms |

---

## 2. 工时类指标

### 2.1 人工稼动率 (Human Utilization Rate)

**定义**：工人在岗时间内有效作业的比例，反映人力资源利用效率。

```
HUR = T_effective / T_total

其中：
  T_effective = T_total - T_wait - T_idle
  T_total = 统计周期总秒数 x 1000
```

**计算周期**：每秒更新一次（滚动窗口，窗口大小 = 班次开始至今）

**输入**：`mes:action_events` Stream（或 SQLite `process_segments` 表）

**阈值**：
- 目标值：>= 0.85
- 告警值：< 0.70
- 正常范围：[0.70, 1.00]
- 异常范围：[0.00, 0.50]（可能存在摄像头遮挡或系统故障）

**示例**：
```
T_total = 28800s x 1000 = 28,800,000 ms  (8小时班次)
T_wait = 3,456,000 ms (12%)
T_idle = 1,152,000 ms (4%)
T_effective = 28,800,000 - 3,456,000 - 1,152,000 = 24,192,000 ms
HUR = 24,192,000 / 28,800,000 = 0.84 (84%)
```

### 2.2 作业效率 (Work Efficiency)

**定义**：单个工序的标准工时与实际工时之比，反映操作熟练度。

```
Eff = t_mod / t_actual

其中：
  t_mod = sum(therblig.mod_value for seg in segments) x 0.129 x 1000
  t_actual = sum(seg.duration_ms for seg in segments)
```

**计算周期**：每次工序段关闭时重新聚合

**输入**：SQLite `process_segments` + `therblig_details` 表

**阈值**：
- 目标值：>= 0.90
- 告警值：< 0.75
- 上限封顶：1.00（实际工时低于标准工时视为100%，避免效率>100%的误导）
- 计算时使用：`Eff_clamped = min(Eff, 1.0)`

**MOD 标准工时对照表**：

| Action Label | Therblig Symbol | MOD Value | 标准时间(ms) |
|---|---|---|---|
| reach | R | 3.0 | 387.0 |
| grasp | G | 1.0 | 129.0 |
| move | M | 4.0 | 516.0 |
| assemble | A | 5.0 | 645.0 |
| release | RL | 1.0 | 129.0 |
| inspect | I | 3.0 | 387.0 |
| wait | UD | 0.0 | 0.0 (测量实际) |
| idle | AD | 0.0 | 0.0 (测量实际) |

---

## 3. 设备类指标

### 3.1 设备综合效率 (OEE - Overall Equipment Effectiveness)

**定义**：设备可用率、性能率和质量率的乘积，反映设备综合效率。

```
OEE = A x P x Q

其中：
  A = T_machine / T_planned     (可用率 Availability)
  P = T_effective_machine / T_machine  (性能率 Performance)
  Q = N_good / N_total          (质量率 Quality)
```

**各分量定义**：

| 分量 | 公式 | 说明 |
|---|---|---|
| A (可用率) | T_machine / T_planned | T_planned = 计划生产时间（班次时长 - 计划停机时间） |
| P (性能率) | T_effective_machine / T_machine | T_effective_machine = 设备实际有效运行时间 |
| Q (质量率) | N_good / N_total | N_good = 合格品数，N_total = 总产出数 |

**计算周期**：每秒更新（可用率和性能率基于时间），每工序段更新（质量率基于产量）

**输入**：PLC 信号（设备状态）、`mes:action_events`（人工有效时间）、质检系统（合格/不良品数）

**阈值**：
- 世界级标准：>= 0.85
- 良好：>= 0.75
- 一般：>= 0.60
- 告警：< 0.60

**边界条件**：
- T_planned = 0 时，OEE = 0（班次尚未开始或全部为计划停机）
- N_total = 0 时，Q = 1.0（尚无产出，假设全部合格）

---

## 4. 协同类指标

### 4.1 人机协同率 (Human-Machine Synchronization Rate)

**定义**：人工作业时间与设备运行时间重叠的比例，反映人机并行效率。

```
HMSR = T_overlap / max(T_work, T_machine)

其中：
  T_work = 等于 T_effective（人工有效作业时间）
  T_machine = 设备运行时间（PLC 信号）
  T_overlap = T_work 与 T_machine 的时间交集
```

**时间交集计算方法**：

将 T_work 和 T_machine 分别视为时间段集合，计算重叠部分：

```python
def compute_overlap(work_intervals, machine_intervals):
    """
    work_intervals: List[(start_ts, end_ts)] 人工有效作业时间段
    machine_intervals: List[(start_ts, end_ts)] 设备运行时间段
    返回重叠时间（ms）
    """
    # 合并相邻/重叠区间
    def merge(intervals):
        if not intervals:
            return []
        sorted_ivs = sorted(intervals)
        merged = [sorted_ivs[0]]
        for s, e in sorted_ivs[1:]:
            if s <= merged[-1][1]:
                merged[-1] = (merged[-1][0], max(merged[-1][1], e))
            else:
                merged.append((s, e))
        return merged

    work = merge(work_intervals)
    machine = merge(machine_intervals)
    overlap = 0

    for ws, we in work:
        for ms, me in machine:
            os = max(ws, ms)
            oe = min(we, me)
            if os < oe:
                overlap += oe - os
    return overlap
```

**计算周期**：每秒更新（基于当前工序段和设备状态）

**阈值**：
- 目标值：>= 0.70
- 告警值：< 0.50

---

## 5. 产线平衡类指标

### 5.1 产线平衡率 (Line Balance Rate)

**定义**：各工位工时之和与（最大工位工时 x 工位数）之比，反映产线各工位负荷均衡程度。

```
LBR = sum(D_i for i in 1..N) / (max(D_i) x N_stations)

其中：
  D_i = 第 i 个工位在统计周期内的平均单次工序时间
  N_stations = 产线工位总数
```

**计算周期**：每5分钟更新

**输入**：SQLite `process_segments` 表，按 `station_id` 分组聚合

**阈值**：
- 优秀：>= 0.90
- 良好：>= 0.85
- 一般：>= 0.75
- 告警：< 0.75（需启动ECRS改善分析）

**示例**：
```
工位1: D_1 = 45000 ms (45s)
工位2: D_2 = 38000 ms (38s)
工位3: D_3 = 52000 ms (52s)
工位4: D_4 = 41000 ms (41s)

sum(D_i) = 45000 + 38000 + 52000 + 41000 = 176000
max(D_i) = 52000
N_stations = 4

LBR = 176000 / (52000 x 4) = 176000 / 208000 = 0.846 (84.6%)
```

### 5.2 平滑指数 (Smoothness Index)

**定义**：各工位工时方差的平方根，反映产线负荷的离散程度。

```
SI = sqrt(sum((D_i - D_avg)^2 for i in 1..N))

其中：
  D_avg = sum(D_i) / N_stations
```

**阈值**：
- 优秀：SI < 5000 ms
- 良好：SI < 8000 ms
- 告警：SI >= 10000 ms

**示例**（续上例）：
```
D_avg = 176000 / 4 = 44000 ms
SI = sqrt((45000-44000)^2 + (38000-44000)^2 + (52000-44000)^2 + (41000-44000)^2)
   = sqrt(1000000 + 36000000 + 64000000 + 9000000)
   = sqrt(110000000)
   = 10488 ms (需改善)
```

### 5.3 瓶颈指数 (Bottleneck Index)

**定义**：单工位工时与平均工时之比，识别负荷最高的工位。

```
BI_i = D_i / D_avg

其中 D_avg 为所有工位平均工时。
```

**判定规则**：

| BI_i 范围 | 判定 | 建议动作 |
|---|---|---|
| BI_i >= 1.30 | 严重瓶颈 | 立即启动ECRS分析 |
| 1.20 <= BI_i < 1.30 | 瓶颈 | 关注并记录 |
| 0.80 <= BI_i < 1.20 | 正常 | 无需动作 |
| BI_i < 0.80 | 轻载 | 考虑合并工序或重新分配 |

---

## 6. 等待分析指标

### 6.1 等待时间占比 (Wait Ratio)

**定义**：等待时间占统计周期总时间的比例。

```
WR = T_wait / T_total
```

### 6.2 等待类型分解

等待时间按原因分为三类，通过规则引擎自动分类：

| 等待类型 | 识别规则 | 说明 |
|---|---|---|
| `equipment_wait` | 设备 OEE < 0.60 且人工在岗 | 设备故障/换型等待 |
| `material_wait` | 人工有取件动作但无物料信号 | 物料短缺等待 |
| `instruction_wait` | 等待期间无设备运行且无取件动作 | 调度/指令等待 |

**分类算法**：
```python
def classify_wait(segment, context):
    """
    segment: 当前等待工序段
    context: 包含当前OEE、设备状态、物料信号等上下文
    """
    if context.oee < 0.60 and context.worker_present:
        return "equipment_wait"
    elif context.reach_action_before_wait and not context.material_available:
        return "material_wait"
    else:
        return "instruction_wait"
```

### 6.3 帕累托分析

对等待原因按时间从高到低排序，计算累计占比：

```
sorted_waits = sort(wait_causes, by=duration, descending=True)
cumulative_pct[i] = sum(sorted_waits[0:i+1]) / T_wait

帕累托分类：
  - 前 20% 的原因 -> 关键少数（优先改善）
  - 后 80% 的原因 -> 次要多数（后续改善）
```

---

## 7. 班次汇总指标

### 7.1 班次工时汇总 (Shift Summary)

在班次结束时（或按需查询时）生成汇总：

```
ShiftSummary {
    shift: "morning" | "afternoon" | "night"
    date: "2026-04-02"
    total_seconds: 28800               // 班次总时长
    effective_seconds: 24192           // 有效作业时长
    utilization: 0.84                  // 人工稼动率
    oee: 0.85                          // 设备综合效率
    sync_rate: 0.72                    // 人机协同率
    wait_ratio: 0.12                   // 等待占比
    total_operations: 156              // 完成工序数
    avg_efficiency: 0.88               // 平均作业效率
    standard_time_hours: 8.2           // 标准工时合计(小时)
    waste_ratio: 0.16                  // 浪费占比(wait+idle)
    line_balance_rate: 0.88            // 产线平衡率（如适用）
    bottleneck_station: "station_05"   // 瓶颈工位
}
```

### 7.2 班次判定规则

```
班次判定（基于时间的小时部分 hour）：
  morning:   06:00 <= hour < 14:00
  afternoon: 14:00 <= hour < 22:00
  night:     hour < 06:00 OR hour >= 22:00
```

---

## 8. 计算实现规范

### 8.1 滚动窗口

所有实时指标使用滚动窗口计算，窗口起始点为班次开始时间（非固定回溯窗口），确保整个班次的数据一致性。

### 8.2 数值精度

- 中间计算使用 Python float（IEEE 754 双精度，约15位有效数字）
- 输出时保留4位小数（round(value, 4)）
- 百分比存储为小数（0.84 而非 84%），前端负责格式化展示

### 8.3 缺失数据处理

- 摄像头未检测到人时（连续IDLE），不计入有效作业时间
- 设备PLC信号缺失时，OEE计算中使用 `A = 0`，不进行估算
- 质检数据缺失时，Q 默认为 `1.0`
- 所有缺失情况写入 `mes:system_events` Stream

### 8.4 线程安全

指标计算在独立线程中运行，与API主线程通过Redis Stream解耦。写入InfluxDB时使用连接池，不共享SQLAlchemy Session。
