#!/usr/bin/env python3
"""Generate system architecture diagram (rev2: remove user layer)"""
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
from matplotlib.font_manager import FontProperties
from matplotlib.patches import FancyBboxPatch
import os

# Load Chinese font (Microsoft YaHei from Windows)
FONT_PATH = '/tmp/fonts/msyh.ttc'
cn_font = FontProperties(fname=FONT_PATH, size=11)
cn_font_title = FontProperties(fname=FONT_PATH, size=14)
cn_font_sm = FontProperties(fname=FONT_PATH, size=8)

fig, ax = plt.subplots(1, 1, figsize=(12, 7.5))
ax.set_xlim(0, 12)
ax.set_ylim(0, 7.5)
ax.axis('off')

COLORS = {
    'frontend': '#E8F5E9',
    'api': '#E3F2FD',
    'worker': '#FFF3E0',
    'redis': '#FCE4EC',
    'sqlite': '#F3E5F5',
    'influx': '#E0F7FA',
    'ai': '#FFEBEE',
    'text': '#212121',
    'arrow': '#78909C',
}

def draw_box(ax, x, y, w, h, color, text, sub_text=''):
    box = FancyBboxPatch((x, y), w, h,
                         boxstyle="round,pad=0.1",
                         facecolor=color,
                         edgecolor='#37474F',
                         linewidth=1.5)
    ax.add_patch(box)
    ax.text(x + w/2, y + h*0.55, text, ha='center', va='center',
            fontsize=11, fontweight='bold', color=COLORS['text'],
            fontproperties=cn_font)
    if sub_text:
        ax.text(x + w/2, y + h*0.25, sub_text, ha='center', va='center',
                fontsize=8, color='#546E7A', fontproperties=cn_font_sm)

def draw_arrow(ax, x1, y1, x2, y2, label='', style='arc3,rad=0.2'):
    ax.annotate('', xy=(x2, y2), xytext=(x1, y1),
                arrowprops=dict(arrowstyle='->', color=COLORS['arrow'],
                               lw=1.5, connectionstyle=style))
    if label:
        ax.text((x1+x2)/2+0.1, (y1+y2)/2+0.1, label,
                fontsize=7, color='#546E7A', fontstyle='italic',
                fontproperties=cn_font_sm)

# Title
ax.text(6, 7.2, '边缘AI作业工时测定系统 系统架构图',
        ha='center', fontsize=14, fontweight='bold', color=COLORS['text'],
        fontproperties=cn_font_title)

# Microservices row (moved up to fill space)
bh, bw = 1.2, 2.6
y1 = 5.5
draw_box(ax, 0.5, y1, bw, bh, COLORS['frontend'], '前端 (Vue3)', 'Nginx · 端口80')
draw_box(ax, 3.5, y1, bw, bh, COLORS['api'], 'API (FastAPI)', '业务逻辑 · 端口8000')
draw_box(ax, 6.5, y1, bw, bh, COLORS['worker'], 'Celery Worker', '异步任务处理')
draw_box(ax, 9.5, y1, bw, bh, COLORS['ai'], 'AI 分析模块', 'MediaPipe + LLM')

# Data stores row
y2 = 3.5
dh, dw = 1.0, 2.2
draw_box(ax, 0.8, y2, dw, dh, COLORS['redis'], 'Redis', '消息队列 · 端口6379')
draw_box(ax, 3.5, y2, dw, dh, COLORS['sqlite'], 'SQLite', '持久化存储')
draw_box(ax, 6.2, y2, dw, dh, COLORS['influx'], 'InfluxDB', '时序数据 · 端口8086')

# Infrastructure layer
y3 = 1.2
ax.text(6, y3+0.5, 'Docker Compose 编排', ha='center', fontsize=10, fontweight='bold',
        color=COLORS['text'], fontproperties=cn_font)
box = FancyBboxPatch((1.5, y3-0.2), 9, 0.8,
                     boxstyle="round,pad=0.1",
                     facecolor='#FAFAFA', edgecolor='#90A4AE',
                     linewidth=1, linestyle='--')
ax.add_patch(box)
ax.text(6, y3+0.1, 'Linux (Ubuntu) · Volume Mount · Network Bridge',
        ha='center', va='center', fontsize=8, color='#78909C',
        fontproperties=cn_font_sm)

# Arrows (no user layer arrows)
# Frontend → API
draw_arrow(ax, 3.1, 6.2, 3.5, 5.8, 'API调用')

# API → Worker (async)
draw_arrow(ax, 6.5, 5.5, 7.5, 5.8, '发布任务', 'arc3,rad=-0.3')

# Worker → AI
draw_arrow(ax, 9.0, 5.5, 9.5, 5.6, '', 'arc3,rad=0')

# Services → Data stores
draw_arrow(ax, 2.5, 5.5, 2.0, 4.5, '缓存', 'arc3,rad=-0.2')
draw_arrow(ax, 5.0, 5.5, 4.8, 4.5, 'CRUD', 'arc3,rad=-0.2')
draw_arrow(ax, 8.0, 5.7, 7.5, 4.5, '时序写', 'arc3,rad=0.3')

plt.tight_layout()
plt.savefig('/mnt/d/tmp/系统架构图.png', dpi=200, bbox_inches='tight',
            facecolor='white', edgecolor='none')
plt.close()

size = os.path.getsize('/mnt/d/tmp/系统架构图.png')
print(f"✅ 架构图已更新: {size/1024:.0f}KB")
