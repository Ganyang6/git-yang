#!/usr/bin/env python3
"""Generate ER diagram for MES Edge AI system (ASCII-safe, no CJK fonts needed)"""
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
from matplotlib.patches import FancyBboxPatch

fig, ax = plt.subplots(1, 1, figsize=(11, 8))
ax.set_xlim(0, 11)
ax.set_ylim(0, 8.5)
ax.axis('off')

# Colors
TABLE_BG = '#F5F5F5'
TABLE_HEADER = '#37474F'

def draw_table(ax, x, y, w, h, title, fields):
    """Draw a table with header and fields"""
    box = FancyBboxPatch((x, y), w, h, boxstyle="round,pad=0.08",
                          facecolor=TABLE_BG, edgecolor='#37474F', linewidth=1.5)
    ax.add_patch(box)

    # Header
    box_h = FancyBboxPatch((x, y + h - 0.35), w, 0.35,
                            boxstyle="round,pad=0.05",
                            facecolor=TABLE_HEADER, edgecolor=TABLE_HEADER, linewidth=0)
    ax.add_patch(box_h)
    ax.text(x + w/2, y + h - 0.175, title, ha='center', va='center',
            fontsize=9, fontweight='bold', color='white')

    # Fields
    field_y = y + h - 0.5
    for field in fields:
        is_pk = field.startswith('[PK]')
        is_fk = field.startswith('[FK]')
        display = field

        if is_pk or is_fk:
            bg = FancyBboxPatch((x + 0.05, field_y - 0.2), w - 0.1, 0.2,
                                boxstyle="round,pad=0.02",
                                facecolor='#FFF3E0' if is_pk else '#E3F2FD',
                                edgecolor='#BDBDBD', linewidth=0.5)
            ax.add_patch(bg)

        ax.text(x + 0.15, field_y - 0.1, display, ha='left', va='center',
                fontsize=7, color='#1A237E' if (is_pk or is_fk) else '#37474F',
                fontweight='bold' if (is_pk or is_fk) else 'normal')
        field_y -= 0.22

# === Tables ===
# stations (top-left)
draw_table(ax, 0.3, 5.5, 3.0, 2.0, 'stations', [
    '[PK] id (INTEGER)',
    'name (VARCHAR)',
    'worker (VARCHAR)',
    'line (VARCHAR)',
    'shift (VARCHAR)',
    'created_at (DATETIME)',
])

# process_segments (center-top)
draw_table(ax, 4.0, 5.5, 3.0, 2.4, 'process_segments', [
    '[PK] id (INTEGER)',
    '[FK] station_id -> stations',
    'action (VARCHAR)',
    'therblig_symbol (VARCHAR)',
    'duration_ms (FLOAT)',
    'confidence (FLOAT)',
    'start_time (DATETIME)',
    'end_time (DATETIME)',
])

# worktime_records (center-bottom)
draw_table(ax, 4.0, 1.5, 3.0, 2.4, 'worktime_records', [
    '[PK] id (INTEGER)',
    '[FK] station_id -> stations',
    'action (VARCHAR)',
    'shift (VARCHAR)',
    'avg_cycle_time (FLOAT)',
    'actual_ms (FLOAT)',
    'worker (VARCHAR)',
    'created_at (DATETIME)',
])

# therblig_details (bottom-right)
draw_table(ax, 7.5, 0.5, 3.0, 2.6, 'therblig_details', [
    '[PK] id (INTEGER)',
    '[FK] worktime_record_id -> worktime_records',
    'therblig_symbol (VARCHAR)',
    'category (VARCHAR)',
    'count (INTEGER)',
    'avg_duration (FLOAT)',
    'pct (FLOAT)',
])

# users (bottom-left)
draw_table(ax, 0.3, 0.5, 2.5, 1.6, 'users', [
    '[PK] id (INTEGER)',
    'username (VARCHAR)',
    'password_hash (VARCHAR)',
    'role (VARCHAR)',
])

# === Relationships (arrows) ===
def draw_rel(ax, x1, y1, x2, y2, label='', style='arc3,rad=0.1'):
    ax.annotate('', xy=(x2, y2), xytext=(x1, y1),
                arrowprops=dict(arrowstyle='->', color='#78909C', lw=1.5, connectionstyle=style))
    if label:
        ax.text((x1+x2)/2, (y1+y2)/2+0.1, label, ha='center', va='center',
                fontsize=6.5, color='#546E7A', fontstyle='italic')

# stations -> process_segments
draw_rel(ax, 3.3, 6.5, 4.0, 6.7, '1:N', 'arc3,rad=0.15')
# stations -> worktime_records
draw_rel(ax, 3.3, 6.0, 4.0, 5.8, '1:N', 'arc3,rad=-0.2')
# process_segments -> worktime_records (aggregation)
draw_rel(ax, 5.5, 5.5, 5.5, 3.9, 'aggregates', 'arc3,rad=0')
# worktime_records -> therblig_details
draw_rel(ax, 7.0, 2.5, 7.5, 2.5, '1:N', 'arc3,rad=0')

# Title
ax.text(5.5, 8.2, 'Edge AI Work-hour Measurement System -- ER Diagram',
        ha='center', fontsize=14, fontweight='bold', color='#212121')

# Legend
legend_y = 0.2
ax.text(9.0, legend_y, '[PK] Primary Key', fontsize=7, color='#1A237E', fontweight='bold')
ax.text(9.0, legend_y - 0.25, '[FK] Foreign Key', fontsize=7, color='#1A237E', fontweight='bold')

plt.tight_layout()
plt.savefig('/mnt/d/tmp/fig_er_diagram.png', dpi=200, bbox_inches='tight', facecolor='white')
plt.close()

import os
size = os.path.getsize('/mnt/d/tmp/fig_er_diagram.png')
print(f"ER diagram generated: {size/1024:.0f}KB")
