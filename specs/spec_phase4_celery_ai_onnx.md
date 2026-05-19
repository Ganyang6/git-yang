# Phase 4 技术规范: Celery + AI + ONNX

> 版本: v1.0 | 日期: 2026-04-03 | 状态: 待评审
> 作者: AI研究团队 (GitHub搜索 + web深度研究 + 微信公众号搜索)

---

## 1. 范围与目标

本规范覆盖 Phase 4 的三大核心技术集成，不含数字孪生和多产线扩展。

| 技术域 | 当前状态 | Phase 4 目标 |
|--------|---------|-------------|
| 异步任务 | 无Celery, AI同步调用阻塞API | Celery worker + 任务队列 + Beat定时任务 |
| AI推理 | DeepSeek API同步代理, 无本地降级 | API + Ollama本地降级 + SSE流式 |
| 动作分类 | 基于规则(关节角度启发式) | ONNX模型增强/替代, ST-GCN/TCN |

---

## 2. Celery + FastAPI 边缘部署

### 2.1 版本与依赖

**Celery**: v5.6.3 (2025-03-26), Python >= 3.9, BSD-3-Clause

安装:
```
pip install "celery[redis]"==5.6.3
```

关键依赖树:
- celery 5.6.3 -> kombu (消息抽象层)
- celery[redis] -> redis-py (broker传输)
- 不需要单独安装eventlet/gevent (除非使用协程池)

### 2.2 Pool选择: solo (1GB RAM)

| Pool | 内存 | 并发 | 适用场景 |
|------|------|------|---------|
| prefork (默认) | 高 (子进程复制) | 多进程并行 | CPU密集、通用 |
| **solo** | **最低 (~50-100MB)** | **单线程顺序** | **调试、边缘设备** |
| gevent | 低 (协程) | 高并发协程 | IO密集 |
| eventlet | 低 | 高并发协程 | IO密集 |

**选择 solo 的理由**:
- 1GB RAM环境, 无多余内存支撑子进程复制
- 任务内部可用 ProcessPoolExecutor/ThreadPoolExecutor 进行内联并行
- 无子进程创建开销, 任务启动延迟最低
- 支持水平扩展 (多Worker实例代替垂直并发)

**预估内存**: 基础Worker 30-60MB, 加载模块后 50-100MB, 任务执行期间额外占用取决于任务本身

### 2.3 配置方案

```python
# celery_app.py
from celery import Celery

celery = Celery(
    "mes_worker",
    broker=os.getenv("CELERY_BROKER_URL", "redis://redis:6379/0"),
    backend=os.getenv("CELERY_RESULT_BACKEND", "redis://redis:6379/1"),
    include=["app.tasks"]
)

celery.conf.update(
    # 序列化 (安全优先)
    task_serializer="json",
    result_serializer="json",
    accept_content=["json"],  # 严格拒绝pickle, 防RCE攻击

    # 结果过期
    result_expires=3600,  # 1小时自动清理, 防Redis内存膨胀

    # 内存保护
    worker_max_tasks_per_child=500,        # 每500任务重启, 防内存泄漏
    worker_max_memory_per_child=300_000,   # 超过300MB自动重启 (KB)
    worker_eta_task_limit=1000,            # v5.6.0+, 限制ETA任务内存

    # 时区
    timezone="Asia/Shanghai",
    enable_utc=True,
)
```

**启动命令**:
```bash
celery -A app.celery_app worker --pool=solo --loglevel=info
```

### 2.4 序列化安全

| 方式 | 安全性 | 性能 | 跨语言 |
|------|--------|------|--------|
| **JSON (推荐)** | 安全 | 良好 | 支持 |
| Pickle | RCE风险 | 最快 | 仅Python |
| msgpack | 安全 | 最快(二进制) | 部分支持 |

**安全警告**: 即使设置 JSON 序列化, 攻击者仍可直接向 Redis 写入 pickle 消息。需通过 Redis ACL 限制访问。

### 2.5 结果后端模式

本系统采用**混合模式**:
- AI分析任务: 需要 Redis backend (任务提交后需查询状态/结果)
- 通知/日志任务: fire-and-forget (ignore_result=True)
- Broker/Backend 使用 Redis 不同数据库隔离 (db0/db1)

### 2.6 长任务处理 (DeepSeek API 10-30s)

| 配置项 | 建议值 | 说明 |
|--------|--------|------|
| soft_time_limit | 45 | 软限制, 抛 SoftTimeLimitExceeded |
| hard_time_limit | 60 | 硬限制, SIGKILL |
| max_retries | 3 | API失败重试次数 |
| retry_backoff | True | 指数退避 (2s, 4s, 8s) |
| retry_backoff_max | 30 | 最大退避30s |
| retry_jitter | True | 随机抖动防惊群 |

**任务链模式**: AI分析 -> 指标计算 -> 通知推送, 使用 Celery Canvas (chain/group/chord)

### 2.7 Celery Beat 定时任务

| 任务 | 频率 | 说明 |
|------|------|------|
| 数据聚合统计 | 每小时 | 从InfluxDB聚合工时数据 |
| 模型健康检查 | 每5分钟 | 检查ONNX模型文件完整性 |
| Redis/InfluxDB连接检查 | 每分钟 | 基础设施心跳 |
| 过期数据清理 | 每天凌晨2点 | 清理Redis结果/InfluxDB过期measurement |

Beat 建议**作为单独进程**运行 (不嵌入 worker), 内存开销约 20-30MB。在 docker-compose 中可用同一镜像不同命令启动。

### 2.8 Docker Compose 集成

```yaml
# worker 服务 (替代当前 tail -f /dev/null 占位)
worker:
  build:
    context: .
    dockerfile: Dockerfile.backend
  command: celery -A app.core.celery_app worker --pool=solo --loglevel=info
  depends_on:
    redis:
      condition: service_healthy
  environment:
    - CELERY_BROKER_URL=redis://redis:6379/0
    - CELERY_RESULT_BACKEND=redis://redis:6379/1
  volumes:
    - ./logs:/app/logs  # 结构化日志
    - ./models:/app/models  # ONNX模型文件
  deploy:
    resources:
      limits:
        memory: 1G
        cpus: "1.0"
  healthcheck:
    test: ["CMD", "python", "-c", "import celery; print('ok')"]
    interval: 30s
    timeout: 10s
    retries: 3
```

### 2.9 优雅关闭

在 Docker 中确保 Worker 能完成当前任务后再退出:
```bash
# SIGTERM -> warm shutdown (完成当前任务, 拒绝新任务)
# SIGKILL -> 立即终止
stop_grace_period: 60s  # docker-compose.yml
```

### 2.10 监控

推荐 **Prometheus Exporter** (比 Flower 轻量):
- `celery-exporter` 项目提供 /metrics 端点
- 与现有 InfluxDB 监控栈集成
- 关键指标: 任务执行时间、队列长度、成功率、Worker内存

### 2.11 参考仓库

| 仓库 | 说明 |
|------|------|
| [celery/celery](https://github.com/celery/celery) | 官方仓库, 48k+ stars |
| [pravendra93/fast-celery-app-ex](https://github.com/pravendra93/fast-celery-app-ex) | 最小化生产就绪示例, FastAPI+Celery+Redis |
| [kennyngdev/celery-fastapi-integration](https://github.com/kennyngdev/celery-fastapi-integration) | RabbitMQ+Redis混合模式, 分离Dockerfile |
| [Madi-S/fastapi-celery-template](https://github.com/Madi-S/fastapi-celery-template) | Docker Compose模板 |
| [TestDriven.io Celery+FastAPI教程](https://testdriven.io/courses/fastapi-celery/docker/) | 6服务架构权威指南 |

---

## 3. DeepSeek API + Ollama 本地降级

### 3.1 DeepSeek API v1 详情

**Base URL**: `https://api.deepseek.com` (完全兼容 OpenAI 格式)

| 模型 | 上下文 | 最大输出 | 输入价格(缓存命中) | 输入价格(缓存未命中) | 输出价格 |
|------|--------|---------|-------------------|-------------------|---------|
| deepseek-chat (V3.2) | 128K | 8K | 0.2元/百万token | 2元/百万token | 3元/百万token |
| deepseek-reasoner (R1) | 128K | 64K | 0.2元/百万token | 2元/百万token | 3元/百万token |

**USD定价**: deepseek-chat 输入$0.27/百万token, 输出$1.10/百万token (比GPT-5便宜约80%)

**功能支持**: JSON Output, Tool Calls, 对话前缀续写(Beta), FIM补全(Beta, 仅chat)

**速率限制**: 不限制并发量, 高流量时排队等待, 10分钟超时。流式请求持续返回 `: keep-alive` SSE注释。

**成本估算**:
- 轻度 (个人): ~$2.5/月
- 中度 (团队): ~$25/月
- 重度 (产品): ~$246/月

### 3.2 Ollama 本地部署

**Docker镜像**: `ollama/ollama` (官方, 约4GB) 或 `alpine/ollama` (70MB, CPU-only)

**CPU-Only 模式** (本系统无GPU):
```bash
docker run -d \
  --memory="4g" \
  --memory-swap="4g" \
  --memory-swappiness=0 \
  --cpus=2 \
  -p 11434:11434 \
  -v ollama:/root/.ollama \
  -e OLLAMA_MAX_LOADED_MODELS=1 \
  -e OLLAMA_NUM_PARALLEL=1 \
  -e OLLAMA_KEEP_ALIVE=5m \
  -e OLLAMA_GPU_LAYERS=0 \
  --name ollama ollama/ollama
```

**关键环境变量**:

| 变量 | 说明 | 建议值 |
|------|------|--------|
| OLLAMA_MAX_LOADED_MODELS | 同时加载模型上限 | 1 |
| OLLAMA_NUM_PARALLEL | 并行请求数 | 1-2 |
| OLLAMA_KEEP_ALIVE | 空闲卸载时间 | 5m |
| OLLAMA_GPU_LAYERS | GPU层数 (0=纯CPU) | 0 |

### 3.3 模型选型

**边缘设备内存约束**: 8GB总内存, 已分配 ~6.2GB 给其他服务, Ollama可用内存约 0-2GB

| 模型 | 量化 | 模型大小 | RAM需求 | CPU推理速度 | 可行性 |
|------|------|---------|---------|------------|--------|
| deepseek-r1:1.5b | Q4 | 1.1GB | ~2GB | 5-15 tok/s | 可行 (仅模型就占2GB) |
| qwen2.5:3b | Q4 | ~2.1GB | ~2.5GB | 5-15 tok/s | 勉强 (超出可用内存) |
| qwen2.5:7b | Q4 | ~4.4GB | ~5.5GB | 2-8 tok/s | 不可行 (内存不足) |
| qwen2.5-coder:3b | Q4 | ~2.1GB | ~2.5GB | 5-15 tok/s | 勉强 |

**关键决策**: 在8GB边缘盒子上, Ollama本地模型**不是优先选择**。建议:
1. 主力: DeepSeek API (外部网络可用时)
2. 降级方案A: 缓存常见查询的预设回复 (Redis)
3. 降级方案B: 简单规则引擎 (基于关键词的固定回复)
4. 可选: 如果边缘盒子升级到16GB, 可部署 deepseek-r1:1.5b

**如果升级内存预算**, 推荐本地模型优先级:
1. deepseek-r1:8b (6.5GB, 通用推理) -- 需要16GB RAM
2. qwen2.5:7b Q4_K_M (5.5GB, 通用对话) -- 需要12GB RAM
3. deepseek-r1:1.5b (2GB, 极低资源兜底) -- 需要4GB可用

### 3.4 降级架构

```
用户请求 -> API路由
           |
           v
      [健康检查] DeepSeek API可达?
      /           \
    是              否
    |                |
    v                v
DeepSeek API     [检查Ollama]
(stream=True)   /           \
              可用           不可用
              |               |
              v               v
         Ollama本地      缓存/预设回复
         (如果部署)       (Redis缓存)
```

**断路器模式** (参考 LiteLLM 18.5k stars):
- allowed_fails: 3 (每分钟允许失败3次)
- cooldown_time: 30s (冷却30秒)
- num_retries: 3 (重试3次, 指数退避)
- request_timeout: 10s (单次请求超时)

**SSE流式处理**:
- DeepSeek流式: 直接透传SSE到前端
- 切换到本地模型时: 发送 `[切换到本地模型]` 通知, 然后输出本地结果
- 切换时保留已生成的部分响应

### 3.5 制造业Prompt工程

AI助手的核心场景:
1. **工时分析解读**: 注入实时Therblig统计、瓶颈工序数据
2. **产线平衡建议**: 注入各工位负荷率、瓶颈识别结果
3. **异常检测解释**: 注入异常事件上下文、历史对比数据

**结构化输出**: 使用JSON mode + function calling 提取结构化数据
**上下文窗口管理**: Prompt压缩, 仅注入相关指标摘要, 限制在4K token以内

### 3.6 参考仓库

| 仓库 | Stars | 说明 |
|------|-------|------|
| [ollama/ollama](https://github.com/ollama/ollama) | 167k | 本地LLM运行平台 |
| [deepseek-ai/DeepSeek-R1](https://github.com/deepseek-ai/DeepSeek-R1) | 92k | 推理模型 |
| [BerriAI/litellm](https://github.com/BerriAI/litellm) | 18.5k | LLM网关, 完整回退/重试 |
| [deepseek-ai/awesome-deepseek-integration](https://github.com/deepseek-ai/awesome-deepseek-integration) | 36.1k | 集成指南合集 |
| [alpine-docker/ollama](https://github.com/alpine-docker/ollama) | - | 70MB CPU-only镜像 |

---

## 4. ONNX Runtime 动作分类

### 4.1 模型架构对比

| 架构 | 参数量 | 模型大小 | 推理速度(CPU) | 时序建模 | 空间建模 | 推荐度 |
|------|--------|---------|-------------|---------|---------|--------|
| **ST-GCN** | 3.1M | ~12MB | 5-20ms | 图卷积 | 图卷积 | 最推荐 |
| 2s-AGCN | ~3.5M | ~15MB | 10-25ms | 自适应图卷积 | 自适应图卷积 | 高 |
| CTRGCN | ~5M | ~20MB | 15-30ms | 时空图卷积 | 通道关系 | 高 |
| **1D-CNN (TCN)** | ~2M | ~8MB | **3-10ms** | 时序卷积 | 无 | 轻量首选 |
| LSTM | ~3M | ~12MB | 15-40ms | 序列依赖 | 无 | 简单 |

**对7类制造业动作 (grasp/assemble/reach/move/wait/inspect/release) 的推荐**:
- **小数据量 (<500样本/类)**: ST-GCN + 迁移学习, 模型小不易过拟合
- **对延迟敏感 (<33ms)**: 1D-CNN/TCN, 30帧窗口, CPU可达实时
- **对精度敏感**: ST-GCN 双流 (Joint+Bone)

### 4.2 ST-GCN 详细规格

| 参数 | 值 |
|------|-----|
| 论文 | AAAI 2018 |
| 参数量 | 3.1M (~12MB) |
| FLOPs | 3.8G (2D) / 5.7G (3D) |
| 输入维度 | [N, 3, T, V, M] = [批次, xyz, 帧数, 关节点数, 人数] |
| 典型帧数 | 30帧 (低延迟) 或 300帧 (高精度) |
| NTU60 XSub 2D准确率 | Joint 88.95%, Bone 91.69%, 四流 92.34% |

### 4.3 MediaPipe 33关键点兼容性

**核心挑战**: MediaPipe BlazePose输出33个关键点, ST-GCN常用17点(COCO)或25点(NTU)

**转换方案**:

**方案A: 关键点映射降维 (快速路径)**
- 从33点中选取COCO 17点子集
- 直接使用预训练COCO格式模型
- 优点: 无需重新训练; 缺点: 丢弃面部和手部信息

**方案B: 自定义Layout + 重新训练 (推荐)**
- 在 graph.py 中定义MediaPipe 33点的自定义Layout
- 定义 neighbor_link 连接关系
- 收集制造业动作数据, 在MMAction2中训练
- 优点: 利用全部信息; 缺点: 需要训练数据

**方案C: 滑动窗口 + LSTM/TCN (轻量化)**
- MediaPipe 33点 -> 压缩为特征向量 -> LSTM/TCN分类
- 优点: 不需要图结构匹配; 缺点: 丢失空间结构

**实际项目参考**:
- [Mediapipe-STGCN_Fall_Detection](https://github.com/Abhiraman-S-Nair/Mediapipe-STGCN_Fall_Detection): 验证了MediaPipe 33点 + ST-GCN的集成可行性, 双阶段检测 (ST-GCN主分类 + MediaPipe滑动窗口后验证)
- [Human-Falling-Detect-Tracks](https://github.com/GajuuzZ/Human-Falling-Detect-Tracks): 天然支持7类动作分类 (Standing/Walking/Sitting/Lying/Stand up/Sit down/Fall Down), 30帧 x 17点 x 2D

### 4.4 ONNX导出路径

| 训练框架 | 导出工具 | 命令 | 成熟度 |
|---------|---------|------|--------|
| **MMAction2 (PyTorch)** | mmdeploy | `python tools/deployment/pytorch2onnx.py CONFIG CHECKPOINT` | 最成熟 |
| PaddleVideo | Paddle2ONNX | 见 deploy/ 目录 | 成熟 |
| 原生PyTorch | torch.onnx.export | 手动处理动态操作 | 中等 |
| MMSkeleton | 手动转换 | 无内置支持 | 低 |

**推荐路径**: MMAction2训练 -> mmdeploy ONNX导出 -> ONNX Runtime推理 (+ OpenVINO EP加速CPU)

**关键步骤**:
```python
# 1. 训练 (MMAction2)
python tools/train.py configs/skeleton/stgcn/stgcn_ntu60_xsub_2d.py

# 2. 导出ONNX
python tools/deployment/pytorch2onnx.py \
    configs/skeleton/stgcn/stgcn_ntu60_xsub_2d.py \
    work_dir/best_model.pth \
    --shape 1 3 30 17 2

# 3. 验证ONNX
import onnxruntime as ort
session = ort.InferenceSession("model.onnx")
result = session.run(None, {"input": dummy_data})
```

**量化**: FP32 -> INT8 可减少模型大小约75%, ONNX Runtime支持onnxruntime.quantization工具

### 4.5 ONNX Runtime CPU 推理优化

```python
import onnxruntime as ort

# 基础配置
session = ort.InferenceSession(
    "model.onnx",
    providers=["CPUExecutionProvider"],
    sess_options=ort.SessionOptions()
)

# 优化配置
sess_options.intra_op_num_threads = 2   # 算子内并行 (匹配2核CPU)
sess_options.inter_op_num_threads = 1   # 算子间串行
sess_options.graph_optimization_level = ort.GraphOptimizationLevel.ORT_ENABLE_ALL
sess_options.enable_mem_pattern = False   # 减少内存碎片
```

**预估性能** (Intel i5/i7, 2核):
- ST-GCN 3.1M参数 (~12MB): 推理 5-20ms
- 加上预处理 (关键点格式化): +2-5ms
- 30帧滑动窗口: 每30帧推理一次, 不影响实时性
- 总延迟: 单次推理 ~10-25ms, 远低于33ms (30fps)目标

### 4.6 模型热更新集成

```
/app/models/
  action_classifier_v1.onnx  # 当前生产模型
  action_classifier_v2.onnx  # 待验证模型
  action_classifier_latest.onnx -> v1.onnx  # 软链接
```

**A/B测试模式**:
1. ONNX模型和规则分类器并行运行
2. 比较置信度: ONNX > threshold 时使用ONNX结果, 否则使用规则分类
3. 渐进推进: 逐步提高threshold
4. Fallback: ONNX推理失败 -> 自动切换规则分类

### 4.7 训练数据与流程

**数据集参考**:
| 数据集 | 类别数 | 关节点 | 样本数 | 适用性 |
|--------|--------|--------|--------|--------|
| NTU RGB+D 60 | 60 | 25 | 56,880 | 迁移学习预训练 |
| NTU RGB+D 120 | 120 | 25 | 114,480 | 更多类 |
| Kinetics-skeleton | 400 | 18 | ~300K | 大规模预训练 |
| 自定义制造数据 | 7 | 33 (MediaPipe) | 100-300/类 | 微调目标 |

**数据收集建议**:
- 每个动作类别至少100-300个视频样本
- 使用现有MediaPipe管线提取33关键点
- 数据格式: [帧数, 33, 3] (x, y, z + visibility)
- 增强策略: 关节抖动、缩放、时间采样偏移、镜像翻转

**训练资源**: 需要GPU (建议云端GPU), 边缘盒不可训练

### 4.8 参考仓库

| 仓库 | Stars | 说明 |
|------|-------|------|
| [open-mmlab/mmaction2](https://github.com/open-mmlab/mmaction2) | - | 最完善的训练框架, 支持ST-GCN/2s-AGCN/PoseC3D, 内置ONNX导出 |
| [PaddlePaddle/PaddleVideo](https://github.com/PaddlePaddle/PaddleVideo) | 1.7k | PaddlePaddle视频理解工具箱, Paddle2ONNX导出 |
| [Abhiraman-S-Nair/Mediapipe-STGCN_Fall_Detection](https://github.com/Abhiraman-S-Nair/Mediapipe-STGCN_Fall_Detection) | - | MediaPipe 33点 + ST-GCN端到端方案 |
| [GajuuzZ/Human-Falling-Detect-Tracks](https://github.com/GajuuzZ/Human-Falling-Detect-Tracks) | 845 | 7类动作分类, AlphaPose+ST-GCN+SORT |
| [wanjinchang/st-gcn](https://github.com/wanjinchang/st-gcn) | - | 维护版ST-GCN, 预训练模型, NTU/Kinetics支持 |

---

## 5. 内存预算总览 (8GB边缘盒子)

| 服务 | 当前分配 | Phase 4 调整 | 说明 |
|------|---------|-------------|------|
| redis | 600MB | 600MB (不变) | 新增Celery消息+结果存储 |
| influxdb | 1GB | 1GB (不变) | 时序数据 |
| api (FastAPI) | 2GB | 2GB (不变) | 主进程 |
| perception | 1.5GB | 1.5GB (不变) | MediaPipe感知 |
| **worker (Celery)** | **占位** | **1GB (solo pool)** | 异步任务+ONNX推理 |
| frontend | 256MB | 256MB (不变) | Nginx静态 |
| **ollama (可选)** | **无** | **0 (当前不可行)** | 内存不足, 需升级到16GB |
| **合计** | ~6.35GB | **~6.35GB** | 在预算内 |

**如果部署Ollama** (需要16GB或更大盒子):
- Ollama + deepseek-r1:1.5b: 额外 ~2GB
- Ollama + qwen2.5:7b Q4: 额外 ~5.5GB

---

## 6. 实施优先级

| 优先级 | 任务 | 预计工期 | 依赖 |
|--------|------|---------|------|
| P0 | Celery基础框架 (solo pool + Redis broker + 任务注册) | 2天 | 无 |
| P0 | AI任务异步化 (ai.py -> Celery task) | 1天 | Celery框架 |
| P1 | Celery Beat定时任务 (数据聚合+健康检查) | 1天 | Celery框架 |
| P1 | SSE流式响应 (AI聊天) | 2天 | FastAPI StreamingResponse |
| P2 | ONNX Runtime集成 (Session管理 + 推理封装) | 2天 | 无 |
| P2 | 1D-CNN/TCN轻量动作分类器 (替代/增强规则) | 3天 | ONNX Runtime |
| P3 | ST-GCN训练管线 (MMAction2 + 自定义数据) | 5天 | GPU训练环境 |
| P3 | Ollama降级 (需评估内存可行性) | 2天 | 网络离线检测 |
| P4 | 模型热更新 + A/B测试框架 | 2天 | ONNX Runtime |

---

## 7. 风险与缓解

| 风险 | 影响 | 缓解措施 |
|------|------|---------|
| 8GB内存不足以运行Ollama | 无本地AI降级 | 优先DeepSeek API + Redis缓存策略 |
| ONNX模型训练需要GPU | 延期ONNX集成 | 先部署1D-CNN轻量模型, 或使用规则分类更长时间 |
| MediaPipe 33点与ST-GCN不兼容 | 无法使用预训练模型 | 自定义Layout重新训练, 或用LSTM/TCN替代 |
| Celery worker内存泄漏 | OOM导致重启 | worker_max_tasks_per_child + worker_max_memory_per_child |
| DeepSeek API不可用 (网络断开) | AI功能降级 | 三级降级: API -> 缓存 -> 预设回复 |

---

## 8. 微信公众号搜索补充

搜索结果摘要 (2026-01至2026-03, 180天内):
- Celery+FastAPI: 多篇文章提及BackgroundTasks vs Celery的选择, 以及Celery+Redis集成最佳实践
- ONNX+边缘推理: YOLOv11+ONNX Runtime姿态检测方案, 智能工厂中ONNX Runtime作为AI推理引擎
- DeepSeek+Ollama: Ollama本地部署DeepSeek教程, OpenClaw项目提及"主力用DeepSeek V4, 备选用通义千问, 再备选用本地Ollama模型, 主力超时自动切备选"的降级策略
- 文章链接解析均失败 (搜狗微信反爬), 但摘要信息已验证研究结论

---

## References

- [Celery 官方文档 v5.6.3](https://docs.celeryq.dev/en/stable/)
- [Celery PyPI](https://pypi.org/project/celery/)
- [Celery 优化指南](https://docs.celeryq.dev/en/stable/userguide/optimizing.html)
- [Celery Solo Worker Pool](https://celery.school/the-solo-worker-pool)
- [TestDriven.io Celery+FastAPI教程](https://testdriven.io/courses/fastapi-celery/docker/)
- [MMAction2 骨骼模型基准](https://mmaction2.readthedocs.io/zh-cn/latest/model_zoo/skeleton.html)
- [Ollama Docker文档](https://docs.ollama.com/docker)
- [Ollama Model Library - DeepSeek-R1](https://ollama.com/library/deepseek-r1)
- [DeepSeek API定价](https://api-docs.deepseek.com/zh-cn/quick_start/pricing/)
- [DeepSeek API速率限制](https://api-docs.deepseek.com/zh-cn/quick_start/rate_limit/)
- [LiteLLM Router架构](https://docs.litellm.ai/docs/router_architecture)
- [LiteLLM 可靠性/回退](https://docs.litellm.ai/docs/proxy/reliability)
- [ONNX Runtime OpenVINO EP](https://onnxruntime.ai/docs/execution-providers/OpenVINO-ExecutionProvider.html)
- [alpine/ollama 70MB镜像](https://github.com/alpine-docker/ollama)
- [pravendra93/fast-celery-app-ex](https://github.com/pravendra93/fast-celery-app-ex)
- [kennyngdev/celery-fastapi-integration](https://github.com/kennyngdev/celery-fastapi-integration)
- [Abhiraman-S-Nair/Mediapipe-STGCN_Fall_Detection](https://github.com/Abhiraman-S-Nair/Mediapipe-STGCN_Fall_Detection)
- [GajuuzZ/Human-Falling-Detect-Tracks](https://github.com/GajuuzZ/Human-Falling-Detect-Tracks)
- [wanjinchang/st-gcn](https://github.com/wanjinchang/st-gcn)
- [BerriAI/litellm](https://github.com/BerriAI/litellm)
- [DeepSeek API定价指南 2026 (DevTk)](https://devtk.ai/zh/blog/deepseek-api-pricing-guide-2026/)
- [Qwen2.5-3B规格](https://apxml.com/models/qwen2-5-3b)
- [Qwen 2.5 7B 8GB运行指南](https://localaimaster.com/models/qwen-2-5-7b)
- [Ollama Docker内存优化](https://markaicode.com/ollama-container-memory-limits-docker-optimization/)
