# 记忆导入工具使用说明

## 功能介绍

该工具用于将 `.workbuddy/memory/` 目录中的记忆文件导入到 MCP Memory 服务器中，实现记忆的自动同步。

## 目录结构

```
scripts/
├── import_memory.py     # 导入工具主脚本
└── README.md           # 本使用说明
```

## 工具原理

1. **读取记忆文件**：扫描 `.workbuddy/memory/` 目录下的所有 Markdown 文件
2. **解析内容**：提取文件中的标题和内容，转换为 MCP Memory 服务器可识别的格式
3. **生成实体**：将解析后的内容转换为 MCP Memory 服务器的实体格式
4. **导入实体**：通过 MCP Memory 服务器的 API 将实体导入到知识图谱中

## 使用方法

### 步骤 1：运行导入工具

在项目根目录下执行以下命令：

```bash
python scripts\import_memory.py
```

### 步骤 2：查看生成的文件

工具会生成 `memory_entities.json` 文件，包含所有记忆实体的详细信息。

### 步骤 3：导入到 MCP Memory 服务器

使用 MCP Memory 服务器的 `create_entities` 工具，将生成的实体导入到知识图谱中。

## 支持的记忆类型

- **semantic**：语义记忆，如角色定义、领域知识等
- **procedural**：过程记忆，如工作流程、操作步骤等
- **episodic**：情景记忆，如历史日志、事件记录等

## 注意事项

1. **文件格式**：确保记忆文件为 Markdown 格式，且遵循标准的标题层级结构
2. **编码问题**：工具支持 UTF-8 编码的文件，确保文件编码正确
3. **导入大小**：由于 MCP Memory 服务器的限制，建议分批导入大量记忆文件
4. **重复导入**：重复导入相同的记忆实体可能会导致数据重复，建议在导入前清理知识图谱

## 示例输出

```
记忆导入工具
==================================================  
从 .workbuddy/memory/ 目录导入记忆到 MCP Memory 服务器 
==================================================  
找到 36 个记忆实体

MCP Memory 服务器 create_entities 工具调用:
{
  "server_name": "mcp_Memory",
  "tool_name": "create_entities",
  "args": {
    "entities":
已生成记忆实体 JSON 文件: memory_entities.json
请使用 MCP Memory 服务器的 create_entities 工具导入这些实体
```

## 故障排除

1. **文件读取失败**：检查文件路径是否正确，文件是否存在，权限是否足够
2. **编码错误**：确保文件使用 UTF-8 编码，避免使用其他编码格式
3. **导入失败**：检查 MCP Memory 服务器是否正常运行，API 调用是否正确

## 版本信息

- 工具版本：v1.0.0
- 最后更新：2026-04-23
- 作者：系统自动生成
