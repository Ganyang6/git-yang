#!/usr/bin/env python3
"""
导入 .workbuddy/memory/ 目录中的记忆文件到 MCP Memory 服务器
"""

import os
import json
from pathlib import Path

# 记忆目录路径
MEMORY_DIR = Path(".workbuddy/memory")

# 记忆类型映射
MEMORY_TYPES = {
    "semantic": "SemanticMemory",
    "procedural": "ProceduralMemory",
    "episodic": "EpisodicMemory"
}


def read_file_content(file_path):
    """读取文件内容"""
    try:
        with open(file_path, 'r', encoding='utf-8') as f:
            return f.read()
    except Exception as e:
        print(f"读取文件失败 {file_path}: {e}")
        return ""


def parse_markdown_content(content):
    """解析 Markdown 内容，提取关键信息"""
    # 提取标题和内容
    sections = []
    current_section = {"title": "", "content": []}
    
    for line in content.split('\n'):
        line = line.strip()
        if line.startswith('#'):
            if current_section["title"]:
                sections.append(current_section)
            current_section = {"title": line.lstrip('# '), "content": []}
        elif line:
            current_section["content"].append(line)
    
    if current_section["title"]:
        sections.append(current_section)
    
    return sections


def create_memory_entities():
    """创建记忆实体"""
    entities = []
    
    # 处理 semantic 目录
    semantic_dir = MEMORY_DIR / "semantic"
    if semantic_dir.exists():
        for file_path in semantic_dir.glob("*.md"):
            content = read_file_content(file_path)
            sections = parse_markdown_content(content)
            
            entity_name = file_path.stem
            observations = []
            
            for section in sections:
                observations.append(f"{section['title']}: {'; '.join(section['content'])}")
            
            entities.append({
                "name": entity_name,
                "entityType": MEMORY_TYPES["semantic"],
                "observations": observations
            })
    
    # 处理 procedural 目录
    procedural_dir = MEMORY_DIR / "procedural"
    if procedural_dir.exists():
        for file_path in procedural_dir.glob("*.md"):
            content = read_file_content(file_path)
            sections = parse_markdown_content(content)
            
            entity_name = file_path.stem
            observations = []
            
            for section in sections:
                observations.append(f"{section['title']}: {'; '.join(section['content'])}")
            
            entities.append({
                "name": entity_name,
                "entityType": MEMORY_TYPES["procedural"],
                "observations": observations
            })
    
    # 处理 episodic 目录
    episodic_dir = MEMORY_DIR / "episodic"
    if episodic_dir.exists():
        for file_path in episodic_dir.glob("*.md"):
            content = read_file_content(file_path)
            sections = parse_markdown_content(content)
            
            entity_name = file_path.stem
            observations = []
            
            for section in sections:
                observations.append(f"{section['title']}: {'; '.join(section['content'])}")
            
            entities.append({
                "name": entity_name,
                "entityType": MEMORY_TYPES["episodic"],
                "observations": observations
            })
    
    return entities


def generate_mcp_tool_calls():
    """生成 MCP 工具调用命令"""
    entities = create_memory_entities()
    
    if not entities:
        print("没有找到记忆文件")
        return
    
    print(f"找到 {len(entities)} 个记忆实体")
    
    # 生成 create_entities 工具调用
    print("\nMCP Memory 服务器 create_entities 工具调用:")
    print("{")
    print("  \"server_name\": \"mcp_Memory\",")
    print("  \"tool_name\": \"create_entities\",")
    print("  \"args\": {")
    print("    \"entities\": ")
    # 生成 JSON 文件
    output_file = Path("memory_entities.json")
    with open(output_file, 'w', encoding='utf-8') as f:
        json.dump(entities, f, ensure_ascii=False, indent=6)
    print(f"已生成记忆实体 JSON 文件: {output_file}")
    print("请使用 MCP Memory 服务器的 create_entities 工具导入这些实体")


def main():
    """主函数"""
    print("记忆导入工具")
    print("=" * 50)
    print("从 .workbuddy/memory/ 目录导入记忆到 MCP Memory 服务器")
    print("=" * 50)
    
    generate_mcp_tool_calls()


if __name__ == "__main__":
    main()
