-- Layer 3: 清理数据库中已存在的负值 duration/actual_ms
-- 执行前请确认数据库路径
-- sqlite3 /path/to/mes.db < scripts/cleanup_negative_durations.sql

UPDATE process_segments SET duration_ms = 0 WHERE duration_ms < 0;
UPDATE worktime_records SET actual_ms = 0 WHERE actual_ms < 0;
UPDATE therblig_details SET actual_ms = 0 WHERE actual_ms < 0;

-- 验证清理结果
SELECT 'process_segments (negatives)' AS table_name, COUNT(*) AS fixed_rows
FROM process_segments WHERE duration_ms < 0;
SELECT 'worktime_records (negatives)' AS table_name, COUNT(*) AS fixed_rows
FROM worktime_records WHERE actual_ms < 0;
SELECT 'therblig_details (negatives)' AS table_name, COUNT(*) AS fixed_rows
FROM therblig_details WHERE actual_ms < 0;

-- 确认零值行存在
SELECT 'process_segments (zeros)' AS table_name, COUNT(*) AS zero_rows
FROM process_segments WHERE duration_ms = 0;
SELECT 'worktime_records (zeros)' AS table_name, COUNT(*) AS zero_rows
FROM worktime_records WHERE actual_ms = 0;
SELECT 'therblig_details (zeros)' AS table_name, COUNT(*) AS zero_rows
FROM therblig_details WHERE actual_ms = 0;
