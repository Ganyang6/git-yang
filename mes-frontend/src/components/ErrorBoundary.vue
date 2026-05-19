<template>
  <div v-if="error" class="error-boundary">
    <div class="error-boundary-content">
      <svg width="32" height="32" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
        <circle cx="12" cy="12" r="10" />
        <line x1="12" y1="8" x2="12" y2="12" />
        <line x1="12" y1="16" x2="12.01" y2="16" />
      </svg>
      <h3>页面渲染异常</h3>
      <p class="error-detail">{{ error?.message || String(error) || '未知错误' }}</p>
      <button class="btn btn-primary btn-sm" @click="handleReset" :disabled="retryCount >= 3">重试</button>
      <p v-if="retryCount >= 3" class="retry-exhausted">多次重试仍然失败</p>
    </div>
  </div>
  <slot v-else />
</template>

<script>
/**
 * ErrorBoundary - Catches rendering errors from child components
 *
 * Wraps <router-view> to prevent uncaught errors from causing
 * a full white screen (P1-28 from comprehensive review).
 */
export default {
  name: 'ErrorBoundary',
  data() {
    return {
      error: null,
      retryCount: 0,
    }
  },
  errorCaptured(err, _vm, info) {
    this.error = err
    console.error('[ErrorBoundary]', info, err)
    // Prevent the error from propagating further
    return false
  },
  methods: {
    reset() {
      this.error = null
    },
    handleReset() {
      this.retryCount++
      if (this.retryCount <= 3) this.reset()
    },
  },
}
</script>

<style scoped>
.error-boundary {
  display: flex;
  align-items: center;
  justify-content: center;
  min-height: 400px;
  padding: 24px;
}
.error-boundary-content {
  text-align: center;
  max-width: 480px;
  color: #6b7280;
}
.error-boundary-content svg {
  color: #ef4444;
  margin-bottom: 16px;
}
.error-boundary-content h3 {
  font-size: 16px;
  font-weight: 600;
  color: #111827;
  margin: 0 0 8px;
}
.error-detail {
  font-size: 13px;
  background: #fef2f2;
  color: #991b1b;
  padding: 8px 12px;
  border-radius: 6px;
  margin: 12px 0 8px;
  word-break: break-all;
}
.retry-exhausted {
  font-size: 12px;
  color: #ef4444;
  margin: 8px 0 0;
}
</style>
