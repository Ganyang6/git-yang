<template>
  <div v-if="visible" class="fallback-badge" :class="severity">
    <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
      <path d="M10.29 3.86L1.82 18a2 2 0 0 0 1.71 3h16.94a2 2 0 0 0 1.71-3L13.71 3.86a2 2 0 0 0-3.42 0z" />
      <line x1="12" y1="9" x2="12" y2="13" />
      <line x1="12" y1="17" x2="12.01" y2="17" />
    </svg>
    <span>{{ label }}</span>
  </div>
</template>

<script setup>
import { computed } from 'vue'

const props = defineProps({
  /** Fallback severity: 'cache' uses Redis cached response, 'rule' uses rule engine */
  severity: {
    type: String,
    default: 'cache',
    validator: v => ['cache', 'rule', 'unknown'].includes(v)
  },
  /** Whether to show the badge */
  visible: {
    type: Boolean,
    default: true
  }
})

const label = computed(() => {
  const map = {
    cache: 'AI 服务降级 - 使用缓存响应',
    rule: 'AI 服务降级 - 使用规则引擎',
    unknown: 'AI 服务降级'
  }
  return map[props.severity] || map.unknown
})
</script>

<style scoped>
.fallback-badge {
  display: inline-flex;
  align-items: center;
  gap: 5px;
  padding: 4px 10px;
  border-radius: 6px;
  font-size: 11px;
  font-weight: 500;
  line-height: 1.3;
}
.fallback-badge.cache {
  background: #fef3c7;
  color: #92400e;
  border: 1px solid #fbbf24;
}
.fallback-badge.rule {
  background: #fee2e2;
  color: #991b1b;
  border: 1px solid #f87171;
}
.fallback-badge.unknown {
  background: #f1f5f9;
  color: #475569;
  border: 1px solid #cbd5e1;
}
</style>
