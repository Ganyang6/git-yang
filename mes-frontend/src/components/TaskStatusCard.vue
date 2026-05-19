<template>
  <div class="task-card" :class="statusClass">
    <div class="task-header">
      <div class="task-type">{{ displayType }}</div>
      <div class="task-time">{{ formattedCreatedAt }}</div>
    </div>

    <div class="task-body">
      <!-- Status with icon -->
      <div class="task-status-row">
        <span class="status-icon" :class="statusClass">
          <svg v-if="status === 'processing'" class="spin" width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5">
            <path d="M21 12a9 9 0 1 1-6.219-8.56" />
          </svg>
          <svg v-else-if="status === 'completed'" width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5">
            <polyline points="20 6 9 17 4 12" />
          </svg>
          <svg v-else-if="status === 'failed'" width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5">
            <line x1="18" y1="6" x2="6" y2="18" />
            <line x1="6" y1="6" x2="18" y2="18" />
          </svg>
          <svg v-else width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5">
            <circle cx="12" cy="12" r="10" />
            <line x1="12" y1="8" x2="12" y2="12" />
            <line x1="12" y1="16" x2="12.01" y2="16" />
          </svg>
        </span>
        <span class="status-label">{{ displayStatus }}</span>
      </div>

      <!-- Progress bar (only when processing) -->
      <div v-if="status === 'processing' && progress > 0" class="progress-wrap">
        <div class="progress-bar">
          <div class="progress-fill" :style="{ width: progress + '%' }"></div>
        </div>
        <span class="progress-text">{{ progress }}%</span>
      </div>

      <!-- Result preview (completed tasks) -->
      <div v-if="status === 'completed' && resultText" class="task-result">
        {{ resultText }}
      </div>

      <!-- Error (failed tasks) -->
      <div v-if="status === 'failed' && errorMsg" class="task-error">
        {{ errorMsg }}
      </div>
    </div>

    <!-- Actions -->
    <div class="task-actions">
      <button
        v-if="status === 'processing' || status === 'pending'"
        class="btn-action btn-cancel"
        :disabled="cancelling"
        @click="$emit('cancel', taskId)"
      >
        {{ cancelling ? '取消中...' : '取消' }}
      </button>
      <button
        v-if="status === 'completed'"
        class="btn-action btn-view"
        @click="$emit('view', { taskId, result })"
      >
        查看
      </button>
      <button
        v-if="status === 'failed'"
        class="btn-action btn-retry"
        @click="$emit('retry', { analysisType, params })"
      >
        重试
      </button>
    </div>
  </div>
</template>

<script setup>
import { computed } from 'vue'

const props = defineProps({
  taskId: {
    type: String,
    required: true
  },
  analysisType: {
    type: String,
    default: 'worktime'
  },
  status: {
    type: String,
    default: 'pending',
    validator: v => ['pending', 'processing', 'completed', 'failed', 'cancelled', 'revoked'].includes(v)
  },
  progress: {
    type: Number,
    default: 0
  },
  result: {
    type: [Object, String, null],
    default: null
  },
  error: {
    type: String,
    default: ''
  },
  createdAt: {
    type: [Number, String],
    default: null
  },
  params: {
    type: Object,
    default: () => ({})
  },
  cancelling: {
    type: Boolean,
    default: false
  }
})

defineEmits(['cancel', 'view', 'retry'])

const statusClass = computed(() => props.status)

const displayType = computed(() => {
  const map = {
    worktime: '工时分析',
    line_balance: '线平衡分析',
    anomaly: '异常检测',
    report: '报表生成',
    therblig_optimization: '动素优化'
  }
  return map[props.analysisType] || props.analysisType
})

const displayStatus = computed(() => {
  const map = {
    pending: '等待中',
    processing: '处理中',
    completed: '已完成',
    failed: '失败',
    cancelled: '已取消',
    revoked: '已撤销'
  }
  return map[props.status] || props.status
})

const formattedCreatedAt = computed(() => {
  if (!props.createdAt) return ''
  const ts = typeof props.createdAt === 'number' ? props.createdAt : new Date(props.createdAt).getTime()
  // P2-4: guard against invalid timestamps
  if (isNaN(ts)) return ''
  return new Date(ts).toLocaleString('zh-CN', {
    month: '2-digit',
    day: '2-digit',
    hour: '2-digit',
    minute: '2-digit'
  })
})

const resultText = computed(() => {
  if (!props.result) return ''
  if (typeof props.result === 'string') return props.result.length > 120 ? props.result.slice(0, 120) + '...' : props.result
  if (props.result.content) return props.result.content.length > 120 ? props.result.content.slice(0, 120) + '...' : props.result.content
  if (props.result.summary) return props.result.summary
  return '分析已完成'
})

const errorMsg = computed(() => {
  if (props.error) return props.error
  if (typeof props.result === 'object' && props.result?.error) return props.result.error
  return ''
})
</script>

<style scoped>
.task-card {
  padding: 12px 14px;
  border: 1px solid var(--gray-200, #e5e7eb);
  border-radius: 10px;
  background: #fff;
  transition: var(--transition-fast, all 0.15s ease);
}
.task-card:hover {
  box-shadow: 0 1px 4px rgba(0, 0, 0, 0.06);
}
.task-card.completed {
  border-left: 3px solid var(--success, #22c55e);
}
.task-card.failed {
  border-left: 3px solid var(--danger, #ef4444);
}
.task-card.processing {
  border-left: 3px solid var(--primary, #4f46e5);
}
.task-card.pending {
  border-left: 3px solid var(--gray-300, #d1d5db);
}

.task-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  margin-bottom: 8px;
}
.task-type {
  font-size: var(--font-size-sm, 13px);
  font-weight: 600;
  color: var(--gray-800, #1f2937);
}
.task-time {
  font-size: 11px;
  color: var(--gray-400, #9ca3af);
}

.task-body {
  margin-bottom: 8px;
}

.task-status-row {
  display: flex;
  align-items: center;
  gap: 6px;
  margin-bottom: 6px;
}
.status-icon {
  display: flex;
  align-items: center;
  justify-content: center;
}
.status-icon.completed { color: var(--success, #22c55e); }
.status-icon.failed { color: var(--danger, #ef4444); }
.status-icon.processing { color: var(--primary, #4f46e5); }
.status-icon.pending { color: var(--gray-400, #9ca3af); }

.status-label {
  font-size: 12px;
  font-weight: 500;
}

.progress-wrap {
  display: flex;
  align-items: center;
  gap: 8px;
  margin-top: 4px;
}
.progress-bar {
  flex: 1;
  height: 6px;
  background: var(--gray-100, #f3f4f6);
  border-radius: 3px;
  overflow: hidden;
}
.progress-fill {
  height: 100%;
  background: var(--primary, #4f46e5);
  border-radius: 3px;
  transition: width 0.3s ease;
}
.progress-text {
  font-size: 11px;
  font-weight: 600;
  color: var(--primary, #4f46e5);
  min-width: 32px;
  text-align: right;
}

.task-result {
  font-size: var(--font-size-xs, 12px);
  color: var(--gray-600, #4b5563);
  line-height: 1.5;
  margin-top: 6px;
  padding: 6px 8px;
  background: var(--gray-50, #f9fafb);
  border-radius: 6px;
}

.task-error {
  font-size: var(--font-size-xs, 12px);
  color: var(--danger, #ef4444);
  line-height: 1.5;
  margin-top: 6px;
  padding: 6px 8px;
  background: #fef2f2;
  border-radius: 6px;
}

.task-actions {
  display: flex;
  justify-content: flex-end;
  gap: 6px;
}

.btn-action {
  padding: 4px 10px;
  border: 1px solid var(--gray-200, #e5e7eb);
  border-radius: 6px;
  font-size: 11px;
  font-weight: 500;
  cursor: pointer;
  background: #fff;
  color: var(--gray-600, #4b5563);
  transition: var(--transition-fast, all 0.15s ease);
}
.btn-action:hover:not(:disabled) {
  background: var(--gray-50, #f9fafb);
}
.btn-action:disabled {
  opacity: 0.5;
  cursor: not-allowed;
}
.btn-cancel:hover:not(:disabled) {
  border-color: var(--danger, #ef4444);
  color: var(--danger, #ef4444);
}
.btn-view:hover:not(:disabled) {
  border-color: var(--primary, #4f46e5);
  color: var(--primary, #4f46e5);
}
.btn-retry:hover:not(:disabled) {
  border-color: var(--warning, #f59e0b);
  color: var(--warning, #f59e0b);
}

.spin {
  animation: card-spin 1s linear infinite;
}
@keyframes card-spin {
  from { transform: rotate(0deg); }
  to { transform: rotate(360deg); }
}
</style>
