# Windows 感知模块设置指南

## 前置条件

1. **Python 3.12.9** — 从 https://www.python.org/downloads/release/python-3129/ 下载安装
   - 安装时勾选 "Add Python to PATH"

2. **Redis 端口暴露** — 已在 docker-compose.yml 中配置（127.0.0.1:6379→6379）

## 安装依赖

用 PowerShell 或 CMD 运行：

```powershell
cd D:\analyze ai\mes-perception-win
pip install -r requirements.txt
```

如果下载慢，加镜像源：

```powershell
pip install -r requirements.txt -i https://pypi.tuna.tsinghua.edu.cn/simple
```

## 运行

### 方式一：命令监听器（接收Docker前端上传的视频任务）

```powershell
run_perception.bat --listener
```

这会订阅 Redis 的 `channel:video_commands` 频道，自动接收从网页上传的视频。

### 方式二：直接处理视频文件

```powershell
run_perception.bat --video D:\analyze ai\data\videos\你的视频.mp4
```

## 验证

运行后检查：
- 感知模块日志应该显示 "Redis connected" 和 "PerceptionAdapter connected"
- 处理中的帧会显示 "--- Iteration N start ---"
- 完成后在工时分析页面刷新查看数据

## 常见问题

| 问题 | 解决 |
|------|------|
| ModuleNotFoundError: No module named 'redis' | `pip install redis` |
| Redis 连接失败 | 确认 Docker Redis 已运行: `docker ps | grep redis` |
| 视频路径错误 | 使用完整路径: `D:\analyze ai\data\videos\xxx.mp4` |
