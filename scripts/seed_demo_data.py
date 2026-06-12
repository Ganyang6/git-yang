"""Demo data seeder — config-driven, zero hardcoded values.
Reads seed_data_config.yaml and populates ProcessSegment table.
"""
import random
import sys
import yaml
from datetime import datetime, timezone, timedelta

# ── Load config ──
config_path = "seed_data_config.yaml"
with open(config_path) as f:
    cfg = yaml.safe_load(f)

# ── Setup DB ──
from app.models.database import ProcessSegment, get_session, init_db
import os

db_url = os.environ.get("MES_DB_URL", "sqlite:///data/mes.db")
init_db(db_url=db_url)
session = get_session(db_url)

# ── Build weighted action list ──
action_pool = []
for a in cfg["actions"]:
    action_pool.extend([a] * a["weight"])

# ── Shanghai timezone ──
SH_TZ = timezone(timedelta(hours=8))
now_sh = datetime.now(SH_TZ)
today_start = now_sh.replace(hour=cfg["segments"]["start_hour"], minute=0, second=0, microsecond=0)
today_end = now_sh.replace(hour=cfg["segments"]["end_hour"], minute=0, second=0, microsecond=0)

total_inserted = 0
for station in cfg["stations"]:
    n = random.randint(cfg["segments"]["per_station_min"], cfg["segments"]["per_station_max"])
    for _ in range(n):
        action = random.choice(action_pool)
        dur_ms = random.randint(action["duration_ms"][0], action["duration_ms"][1])
        dur_ms = int(dur_ms * station.get("duration_multiplier", 1.0))
        offset_seconds = random.random() * (today_end.timestamp() - today_start.timestamp())
        start_dt = datetime.fromtimestamp(today_start.timestamp() + offset_seconds, tz=SH_TZ)
        end_dt = datetime.fromtimestamp(today_start.timestamp() + offset_seconds + dur_ms / 1000.0, tz=SH_TZ)
        seg = ProcessSegment(
            station_id=station["id"],
            action=action["name"],
            duration_ms=float(dur_ms),
            start_time=start_dt,
            end_time=end_dt,
            camera_id=station["id"],
            confidence=round(random.uniform(0.7, 0.99), 2),
        )
        session.add(seg)
        total_inserted += 1

session.commit()
session.close()
print(f"已插入 {total_inserted} 条 ProcessSegment 数据到 {db_url}")
