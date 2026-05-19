<template>
  <div id="app-root">
    <ErrorBoundary>
      <router-view />
    </ErrorBoundary>
    <AppToast ref="toastRef" />
    <!-- Global confirm dialog -->
    <Teleport to="body">
      <div v-if="confirmOpen" class="confirm-overlay" @click.self="handleCancel" @keydown.escape="handleCancel">
        <div class="confirm-dialog">
          <h3 class="confirm-title">{{ confirmTitle }}</h3>
          <p class="confirm-message">{{ confirmMessage }}</p>
          <div class="confirm-actions">
            <button class="confirm-btn confirm-btn-cancel" @click="handleCancel">Cancel</button>
            <button class="confirm-btn confirm-btn-ok" @click="handleConfirm">OK</button>
          </div>
        </div>
      </div>
    </Teleport>
  </div>
</template>

<script setup>
import { ref, onMounted, onUnmounted } from 'vue'
import AppToast from './components/AppToast.vue'
import ErrorBoundary from './components/ErrorBoundary.vue'
import { useConfirm } from './composables/useConfirm.js'
// Phase 3: Global API error handler
import { useToast } from '@/composables/useToast'

const toastRef = ref(null)
const { confirmOpen, confirmTitle, confirmMessage, handleConfirm, handleCancel } = useConfirm()

function onToastEvent(event) {
  if (!toastRef.value) return
  const { level, title, message } = event.detail || {}
  if (message) {
    const validLevels = ['info', 'success', 'warning', 'error']
    if (level && !validLevels.includes(level)) {
      console.warn(`[toast] unknown level: "${level}", falling back to "info"`)
    }
    toastRef.value[level] ? toastRef.value[level](message, title) : toastRef.value.info(message, title)
  }
}

const { showToast } = useToast()

// Intercept unhandled promise rejections (API errors that weren't caught)
function onUnhandledRejection(event) {
  const msg = event.reason?.message || String(event.reason)
  showToast(`请求失败: ${msg}`, 'error')
}

onMounted(() => {
  window.addEventListener('mes:toast', onToastEvent)
  window.addEventListener('unhandledrejection', onUnhandledRejection)
})

onUnmounted(() => {
  window.removeEventListener('mes:toast', onToastEvent)
  window.removeEventListener('unhandledrejection', onUnhandledRejection)
})
</script>

<style>
#app-root {
  height: 100vh;
  overflow: hidden;
}

.confirm-overlay {
  position: fixed;
  top: 0; left: 0; right: 0; bottom: 0;
  background: rgba(0, 0, 0, 0.4);
  display: flex;
  align-items: center;
  justify-content: center;
  z-index: 9999;
}

.confirm-dialog {
  background: var(--bg-primary, #fff);
  border-radius: 8px;
  padding: 24px;
  max-width: 400px;
  width: 90%;
  box-shadow: 0 8px 32px rgba(0, 0, 0, 0.2);
}

.confirm-title {
  margin: 0 0 12px;
  font-size: 16px;
  font-weight: 600;
  color: var(--text-primary, #1a1a2e);
}

.confirm-message {
  margin: 0 0 20px;
  font-size: 14px;
  color: var(--text-secondary, #555);
  line-height: 1.5;
}

.confirm-actions {
  display: flex;
  justify-content: flex-end;
  gap: 8px;
}

.confirm-btn {
  padding: 6px 16px;
  border-radius: 4px;
  border: 1px solid #ddd;
  cursor: pointer;
  font-size: 14px;
  transition: background 0.15s;
}

.confirm-btn-cancel {
  background: transparent;
  color: var(--text-secondary, #555);
}

.confirm-btn-cancel:hover {
  background: #f5f5f5;
}

.confirm-btn-ok {
  background: var(--danger);
  color: #fff;
  border-color: var(--danger);
}

.confirm-btn-ok:hover {
  background: var(--danger-dark);
}
</style>
