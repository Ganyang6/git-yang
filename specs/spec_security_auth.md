# 技术规范：安全认证设计

> 版本：1.0 | 状态：已接受 | 角色：后端（实现者）、前端（对接者）、运维（配置者）
>
> 本规范定义了系统的认证鉴权机制、API 安全策略、数据保护和部署安全要求。所有涉及用户身份、权限控制和网络通信的模块必须严格遵守此契约。

---

## 1. 认证架构总览

系统采用 JWT（JSON Web Token）认证方案，无独立用户管理系统（Phase 3-4），使用配置文件管理固定用户。Phase 5+ 扩展为数据库用户表时，本规范的接口契约不变。

```
[前端] --(POST /api/v1/auth/login)--> [FastAPI]
                                            |
                                     验证用户名密码
                                            |
                                     签发 JWT Token
                                            |
[前端] <--(200 {access_token})---------- [FastAPI]

[前端] --(GET /api/v1/xxx + Authorization: Bearer <token>)--> [FastAPI]
                                                             |
                                                      解析+验证 JWT
                                                             |
                                                      放行 / 401
```

---

## 2. JWT Token 规范

### 2.1 Token 结构

```
Header:  {"alg": "HS256", "typ": "JWT"}
Payload: {"sub": "admin", "role": "admin", "exp": 1743572400, "iat": 1743568800}
```

### 2.2 Payload 字段

| 字段 (claim) | 类型 | 必填 | 说明 |
|---|---|---|---|
| `sub` | string | 是 | 用户唯一标识（用户名） |
| `role` | string | 是 | 角色：`admin` / `engineer` / `operator` |
| `exp` | integer | 是 | 过期时间，Unix epoch 秒 |
| `iat` | integer | 是 | 签发时间，Unix epoch 秒 |

### 2.3 签名算法与密钥

- 算法：HS256（HMAC-SHA256）
- 密钥来源：环境变量 `JWT_SECRET_KEY`，若未设置则从 `config.yaml` 读取
- 密钥长度要求：>= 32 字节
- 密钥生成：`python -c "import secrets; print(secrets.token_urlsafe(32))"`

### 2.4 Token 有效期

| 场景 | 有效期 | 说明 |
|---|---|---|
| 默认 | 8 小时 | 匹配最长班次（night shift 22:00-06:00） |
| "记住我" | 7 天 | 用户勾选"记住我"时 |
| WebSocket | 8 小时 | WebSocket 连接建立时验证一次，连接保持期间不重新验证 |

### 2.5 Token 刷新

当前阶段不实现 Refresh Token。Token 过期后前端跳转登录页重新认证。

---

## 3. 认证 API 契约

### 3.1 登录

```
POST /api/v1/auth/login
Content-Type: application/json
```

**请求体**：
```json
{
  "username": "admin",
  "password": "changeme",
  "remember": false
}
```

**成功响应** (200)：
```json
{
  "code": 0,
  "message": "success",
  "data": {
    "access_token": "eyJhbGciOiJIUzI1NiIs...",
    "token_type": "bearer",
    "expires_in": 28800,
    "user": {
      "username": "admin",
      "role": "admin",
      "display_name": "Admin"
    }
  },
  "timestamp": 1743568800
}
```

**失败响应** (401)：
```json
{
  "code": 40101,
  "message": "Invalid credentials",
  "timestamp": 1743568800
}
```

### 3.2 获取当前用户

```
GET /api/v1/auth/me
Authorization: Bearer <token>
```

**成功响应** (200)：
```json
{
  "code": 0,
  "message": "success",
  "data": {
    "username": "admin",
    "role": "admin",
    "display_name": "Admin"
  },
  "timestamp": 1743568800
}
```

### 3.3 登出

```
POST /api/v1/auth/logout
Authorization: Bearer <token>
```

**成功响应** (200)：
```json
{
  "code": 0,
  "message": "success",
  "data": null,
  "timestamp": 1743568800
}
```

> 注意：当前阶段服务端不做 Token 黑名单（无状态 JWT），登出仅清除前端 localStorage。

---

## 4. 用户管理规范

### 4.1 固定用户配置（Phase 3-4）

用户信息存储在 `config.yaml` 中：

```yaml
app:
  auth:
    jwt_secret_key: "${JWT_SECRET_KEY}"  # 从环境变量注入
    token_expire_hours: 8
    token_remember_days: 7
    users:
      - username: admin
        password: "bcrypt_hash_here"     # bcrypt 哈希存储
        role: admin
        display_name: "Admin"
      - username: engineer
        password: "bcrypt_hash_here"
        role: engineer
        display_name: "Process Engineer"
      - username: operator
        password: "bcrypt_hash_here"
        role: operator
        display_name: "Line Operator"
```

### 4.2 密码存储

- 算法：bcrypt（`passlib[bcrypt]`）
- work factor：12 rounds（默认）
- 明文密码仅存在于登录请求的传输过程中，服务端仅存储哈希值
- 配置文件中的 password 字段为 bcrypt 哈希值，非明文

### 4.3 默认凭据

首次部署时生成默认 admin 账户，密码写入 `.env` 文件：

```env
# .env (首次部署时自动生成，运维人员需及时修改)
DEFAULT_ADMIN_PASSWORD=changeme_1743568800
```

系统启动时检测默认密码，如未修改则输出 WARN 级别日志。

---

## 5. 角色权限模型

### 5.1 角色定义

| 角色 | 标识 | 职责 | 权限范围 |
|---|---|---|---|
| 管理员 | `admin` | 系统配置、用户管理、全部数据访问 | 全部API |
| 工艺工程师 | `engineer` | 工时分析、AI对话、报告查看、瓶颈诊断 | 读+分析权限，无系统配置权限 |
| 操作工 | `operator` | 查看实时看板、接收通知 | 仅看板查看权限 |

### 5.2 权限矩阵

| API 路由前缀 | admin | engineer | operator |
|---|---|---|---|
| `/api/v1/auth/*` | RW | R (me) | R (me) |
| `/api/v1/ingest/*` | RW | RW | RW (传感器直连) |
| `/api/v1/worktime/*` | RW | R | R |
| `/api/v1/cameras/*` | RW | R | - |
| `/api/v1/balance/*` | R | R | R |
| `/api/v1/analysis/*` | RW | RW | - |
| `/api/v1/ai/*` | RW | RW | - |
| `/api/v1/dashboard/*` | R | R | R |
| `/api/v1/orders/*` | RW | R | - |
| `/api/v1/customers/*` | RW | R | - |
| `/api/v1/inventory/*` | RW | R | - |
| `/api/v1/equipment/*` | RW | R | - |
| `/api/v1/reports/*` | RW | R | R |
| `/ws/realtime` | RW | R | R |
| `/sse/events` | R | R | R |

> R = 读取, W = 写入/修改/删除, RW = 全部, `-` = 无权限

### 5.3 权限实现

```python
from fastapi import Depends, HTTPException, Security
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials

security = HTTPBearer()

async def get_current_user(credentials: HTTPAuthorizationCredentials = Security(security)):
    """解码并验证 JWT，返回用户信息。"""
    token = credentials.credentials
    try:
        payload = jwt.decode(token, SECRET_KEY, algorithms=["HS256"])
    except jwt.ExpiredSignatureError:
        raise HTTPException(status_code=401, detail="Token expired")
    except jwt.InvalidTokenError:
        raise HTTPException(status_code=401, detail="Invalid token")
    return payload

async def require_role(required_role: str):
    """角色检查依赖项工厂。"""
    async def checker(user = Depends(get_current_user)):
        if user.get("role") != required_role and user.get("role") != "admin":
            raise HTTPException(status_code=403, detail="Insufficient permissions")
        return user
    return checker

# 路由使用示例
@router.delete("/equipment/{id}")
async def delete_equipment(user = Depends(require_role("admin"))):
    ...
```

---

## 6. API 安全策略

### 6.1 CORS 配置

```python
# app/core/config.py -> CorsConfig
allow_origins: ["http://localhost:5173", "http://localhost:80"]  # 开发环境
# 生产环境改为具体域名
allow_credentials: False
allow_methods: ["GET", "POST", "PUT", "DELETE"]
allow_headers: ["Content-Type", "Authorization"]
```

生产环境禁用通配符 `"*"`，仅允许已知前端域名。

### 6.2 请求限流

| 路由 | 限制 | 说明 |
|---|---|---|
| `POST /auth/login` | 5次/分钟/IP | 防暴力破解 |
| `POST /ingest/*` | 200次/分钟/IP | 传感器数据摄入 |
| `GET /worktime/*` | 60次/分钟/IP | 常规查询 |
| `POST /analysis/*` | 10次/分钟/用户 | AI分析（资源消耗型） |
| 其他 GET | 120次/分钟/IP | 常规浏览 |

实现方式：基于 Redis 的滑动窗口限流（`INCR` + `EXPIRE`），key 格式 `ratelimit:{ip}:{endpoint}`。

### 6.3 输入校验

- 所有请求体通过 Pydantic schema 校验，拒绝未知字段
- 路径参数和查询参数使用 FastAPI 类型约束（`Query(max_length=32)`）
- 时间参数校验：`start_time < end_time`，范围不超过31天
- station_id / camera_id：仅允许字母、数字、下划线，长度 1-32

### 6.4 全局异常处理

```python
@app.exception_handler(Exception)
async def global_exception_handler(request, exc):
    logger.exception("Unhandled error on %s %s", request.method, request.url)
    return JSONResponse(
        status_code=500,
        content={
            "code": 50000,
            "message": "Internal server error",
            "timestamp": time.time(),
        },
    )
```

500 错误响应不暴露异常类名和堆栈信息，完整异常记录在服务端日志（`exc_info=True`）。

### 6.5 API Key 代理（AI 模块）

DeepSeek API Key 通过后端代理调用，前端不接触密钥：

```
前端 -> POST /api/v1/ai/chat -> 后端 -> POST https://api.deepseek.com/v1/chat/completions
                                     (后端注入 API Key)
```

AI 分析请求中的系统提示词注入工位实时数据（工时、平衡率、OEE），用户无法篡改注入内容。

---

## 7. WebSocket 安全

### 7.1 认证

WebSocket 连接通过 URL query parameter 传递 Token：

```
ws://localhost:8000/ws/realtime?token=<jwt_token>&subscribe=metrics,pose_frames&station_id=station_03
```

服务端在 `WebSocket.connect` 时验证 Token，无效则拒绝连接（关闭 code 4001）。

### 7.2 频率控制

| 推送类型 | 频率 | 说明 |
|---|---|---|
| 实时指标 | 1次/秒 | 固定频率 |
| 动作事件 | 实时 | 事件驱动，有即推 |
| 分析结果 | 实时 | 事件驱动 |
| 系统告警 | 实时 | 事件驱动 |

### 7.3 连接管理

```python
# 心跳参数
ping_interval = 20   # 每20秒发送ping
ping_timeout = 10    # 10秒无pong则断开

# 连接数限制
MAX_WS_CONNECTIONS = 100  # 单实例最大并发连接数

# 连接生命周期
1. 客户端连接 -> 验证 Token -> 注册到 ConnectionManager
2. 按订阅推送数据 -> 检查连接存活
3. 客户端断开（正常/超时）-> 从 ConnectionManager 移除
```

### 7.4 订阅隔离

客户端只能订阅其权限范围内的 station_id：

- admin：所有 station_id
- engineer：配置中绑定的 station_id 列表
- operator：仅自己的 station_id

---

## 8. 数据保护

### 8.1 传输加密

| 通道 | 加密方式 | 说明 |
|---|---|---|
| 前端 <-> Nginx | HTTPS (TLS 1.2+) | Nginx 配置 SSL 证书 |
| Nginx <-> FastAPI | HTTP (内网) | Docker bridge 网络，不暴露端口 |
| FastAPI <-> Redis | TCP (内网) | Docker bridge 网络 |
| FastAPI <-> DeepSeek | HTTPS | 外部API调用 |
| FastAPI <-> InfluxDB | HTTP (内网) | Docker bridge 网络 |

### 8.2 敏感配置管理

```env
# .env 文件（不入 Git，.gitignore 中排除）
JWT_SECRET_KEY=<32字节随机字符串>
DEEPSEEK_API_KEY=<DeepSeek API Key>
INFLUXDB_TOKEN=<InfluxDB Admin Token>
```

敏感配置通过 `.env` 文件注入 Docker 容器（`env_file: .env`），不写入 Docker 镜像。

### 8.3 数据最小化

- 不存储原始视频帧，仅提取关键点坐标
- 关键点坐标不含面部特征（NOSE/EAR/EYE 等点可选关闭）
- 日志中不记录完整请求体，仅记录路由、状态码、耗时
- AI分析报告中的个人信息（工位/操作工）仅在需要时展示

### 8.4 SQLite 安全

- 数据库文件位于 Docker 命名卷，不映射到宿主机可访问路径
- 数据库连接使用只读权限执行查询操作（写操作通过专用 Session）
- 定期备份：`sqlite3 mes.db ".backup /backup/mes_$(date +%Y%m%d).db"`

---

## 9. Docker 安全

### 9.1 容器用户

所有容器以非 root 用户运行：

```dockerfile
# Dockerfile.backend
RUN useradd --create-home --shell /bin/bash appuser
USER appuser
```

感知容器需要访问 `/dev/video` 设备，使用 `--privileged` 时需确保仅在可信内网环境部署。

### 9.2 网络隔离

```yaml
# docker-compose.yml
services:
  frontend:
    ports:
      - "80:80"        # 唯一对外端口
  api:
    expose:
      - "8000"         # 仅内部网络可访问
  redis:
    expose:
      - "6379"
  influxdb:
    expose:
      - "8086"
```

仅 `frontend`（Nginx）暴露宿主机端口，其他服务仅通过 Docker bridge 网络通信。

### 9.3 健康检查与自动重启

所有容器配置 `restart: unless-stopped` 和 `healthcheck`：

```yaml
healthcheck:
  test: ["CMD", "curl", "-f", "http://localhost:8000/health"]
  interval: 30s
  timeout: 10s
  retries: 3
  start_period: 10s
```

### 9.4 资源限制

```yaml
deploy:
  resources:
    limits:
      memory: 2G
      cpus: "2"
    reservations:
      memory: 1G
      cpus: "1"
```

防止某一容器异常占用全部系统资源。

---

## 10. 日志安全

### 10.1 日志格式

```python
# 结构化日志
{
    "timestamp": "2026-04-02T08:30:15.123Z",
    "level": "INFO",
    "service": "api",
    "module": "app.api.v1.ingest",
    "method": "POST",
    "path": "/api/v1/ingest/frame",
    "status_code": 200,
    "duration_ms": 5.2,
    "station_id": "station_03",
    "client_ip": "172.18.0.1"
}
```

### 10.2 禁止记录的内容

- JWT Token（完整值或 payload 中的密码）
- API Key（DeepSeek / InfluxDB）
- 用户密码（即使是哈希值也不在常规日志中出现）
- 完整请求体（仅在 DEBUG 级别且配置 `app.database.echo=true` 时记录）
- 完整响应体

### 10.3 审计日志

以下操作必须写入审计日志（独立于常规日志）：

| 操作 | 记录内容 |
|---|---|
| 登录成功/失败 | 用户名、IP、时间、成功/失败 |
| 权限变更 | 操作者、目标用户、变更内容 |
| 设备配置变更 | 操作者、设备ID、变更内容 |
| 模型热更新 | 操作者、模型版本、更新结果 |
| 数据导出 | 操作者、导出范围、时间 |

---

## 11. 错误码规范

| 范围 | 类别 | 说明 |
|---|---|---|
| 0 | 成功 | 正常响应 |
| 40001-40099 | 请求错误 | 参数校验失败、格式错误 |
| 40101-40199 | 认证错误 | Token无效/过期、凭据错误 |
| 40301-40399 | 权限错误 | 权限不足、角色不匹配 |
| 40401-40499 | 资源不存在 | 查询目标不存在 |
| 42901-42999 | 限流 | 请求频率超限 |
| 50001-50099 | 服务端错误 | 内部异常（不暴露细节） |
| 50301-50399 | 服务不可用 | Redis/InfluxDB 连接失败、模型加载失败 |

示例错误响应：

```json
{
  "code": 40101,
  "message": "Token expired",
  "timestamp": 1743568800
}
```
