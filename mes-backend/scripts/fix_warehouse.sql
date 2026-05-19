-- fix_warehouse.sql
-- 修复库存物料 warehouse 字段为空的问题
-- 对 warehouse 为空但 location 包含 "-" 的记录，从 location 自动推导 warehouse（取第一个 "-" 之前的部分）

-- 预览即将修改的记录
SELECT id, code, name, location, warehouse AS old_warehouse,
       substr(location, 1, instr(location, '-') - 1) AS new_warehouse
FROM inventory_items
WHERE (warehouse IS NULL OR warehouse = '')
  AND location IS NOT NULL
  AND location != ''
  AND instr(location, '-') > 0
ORDER BY id;

-- 执行修复
UPDATE inventory_items
SET warehouse = substr(location, 1, instr(location, '-') - 1),
    updated_at = datetime('now', 'localtime')
WHERE (warehouse IS NULL OR warehouse = '')
  AND location IS NOT NULL
  AND location != ''
  AND instr(location, '-') > 0;

-- 验证修复结果：检查 warehouse 仍为空的记录
SELECT id, code, name, location, warehouse
FROM inventory_items
WHERE warehouse IS NULL OR warehouse = ''
ORDER BY id;
