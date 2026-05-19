# T7-10 + T9-06 端到端验证报告

**验证人**: 运维角色
**日期**: 2026-04-19
**环境**: WSL2 + Docker Compose (Win11), 7 容器全部 healthy

## 1. 验证结论

**端到端数据链路已打通**: `Perception → Redis Stream → Consumer → SQLite → API → Frontend` 全链路验证通过。

## 2. 验证结果汇总

| # | 验收项 | 任务 | 结果 | 说明 |
|---|--------|------|------|------|
| 1 | Volume 共享 | T9-06 | PASS | docker-compose.yml api/perception 共享 `./data/videos` |
| 2 | 管线触发方案 | T9-06 | PASS | Redis Pub/Sub 命令通道 (`mes:cmd:bridge`) |
| 3 | Docker 加载修复代码 | T7-10 | PASS | 后端 persist bug 已修复，重启生效 |
| 4 | pose_frames 消息 | T7-10 | PASS | `mes:pose_frames` Stream 有 ~120 帧消息 |
| 5 | action_events 事件 | T7-10 | PASS | `mes:action_events` Stream 有分类事件 |
| 6 | SQLite 持久化 | T7-10 | PASS | `process_segments` 表有 1 行记录 |
| 7 | API 数据接口 | T7-10 | PASS | `/worktime/recent` 返回 2 条，summary/operations 均正常响应 |
| 8 | 前端链路 | T7-10 | PASS | 前端 → Nginx → API → SQLite 通路正常 |
| 9 | 前端页面渲染 | T7-10 | PASS | 登录、路由、页面组件均正常 |
| 10 | 前端数据展示 | T7-10 | PASS* | 页面正常显示"暂无工序数据"（API 返回空是预期） |

*注: WorktimeAnalysis 页面显示"暂无工序数据"是因为 `worktime_records` 表为空，不是链路问题。

## 3. 额外修复（运维域）

### 3.1 Nginx client_max_body_size

| 项目 | 详情 |
|------|------|
| 文件 | `docker/nginx.conf` |
| 修改 | `location /api/` 添加 `client_max_body_size 500m;` |
| 原因 | Nginx 默认 1MB 限制导致视频上传 413，Phase 9 设计为 500MB |
| 部署 | `docker cp` + `nginx -s reload`（WSL2 9P 缓存导致 build 缓存未失效） |
| 验证 | 容器内 `cat /etc/nginx/conf.d/default.conf` 确认第 30 行 |

### 3.2 Redis TimeoutError 日志降噪

| 项目 | 详情 |
|------|------|
| 文件 | `mes-backend/app/core/redis_client.py` |
| 修改 | `consume_stream()` 新增 `except TimeoutError: return []` |
| 原因 | XREADGROUP BLOCK 5000 + socket_timeout=2 导致每秒交替刷 error 日志 |
| 影响 | 正常轮询超时，静默处理 |

## 4. 已知问题（移交后端）

| 问题 | 根因 | 影响 | 建议 |
|------|------|------|------|
| `worktime_records` 表为空 | `_AGGREGATION_THRESHOLD=50`，测试只有 1-2 个 segments | summary/operations/therblig 返回空数组 | 降低阈值或加定时聚合 |

## 5. 数据链路图

```
[Perception] --pose_frames--> [Redis Stream: mes:pose_frames]
                                      |
                              [ActionEventConsumer]
                                      |
                              [Redis Stream: mes:action_events]
                                      |
                              [_persist_to_sqlite]
                                      |
                              [SQLite: process_segments] --(需50个)--> [worktime_records]
                                      |                                        |
                              [/worktime/recent]                     [/worktime/operations]
                              [/worktime/summary]                    [/worktime/therblig/{id}]
                                      |                                        |
                              [FastAPI API]                            [FastAPI API]
                                      \                                      /
                                       [Nginx Reverse Proxy]
                                              |
                                      [Frontend Vue3]
```
