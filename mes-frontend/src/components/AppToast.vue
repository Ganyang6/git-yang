<template>
  <Teleport to="body">
    <div class="toast-container" aria-live="polite" aria-label="Notifications">
      <TransitionGroup name="toast-slide">
        <div
          v-for="item in visibleToasts"
          :key="item.id"
          class="toast-item"
          :class="`toast-${item.level}`"
          role="alert"
        >
          <div class="toast-icon">
            <!-- Warning icon -->
            <svg
              v-if="item.level === 'warning'"
              width="18"
              height="18"
              viewBox="0 0 24 24"
              fill="none"
              stroke="currentColor"
              stroke-width="2"
            >
              <path
                d="M10.29 3.86L1.82 18a2 2 0 0 0 1.71 3h16.94a2 2 0 0 0 1.71-3L13.71 3.86a2 2 0 0 0-3.42 0z"
              />
              <line x1="12" y1="9" x2="12" y2="13" />
              <line x1="12" y1="17" x2="12.01" y2="17" />
            </svg>
            <!-- Error icon -->
            <svg
              v-else-if="item.level === 'error'"
              width="18"
              height="18"
              viewBox="0 0 24 24"
              fill="none"
              stroke="currentColor"
              stroke-width="2"
            >
              <circle cx="12" cy="12" r="10" />
              <line x1="15" y1="9" x2="9" y2="15" />
              <line x1="9" y1="9" x2="15" y2="15" />
            </svg>
            <!-- Success icon -->
            <svg
              v-else-if="item.level === 'success'"
              width="18"
              height="18"
              viewBox="0 0 24 24"
              fill="none"
              stroke="currentColor"
              stroke-width="2"
            >
              <polyline points="20 6 9 17 4 12" />
            </svg>
            <!-- Info icon (default) -->
            <svg
              v-else
              width="18"
              height="18"
              viewBox="0 0 24 24"
              fill="none"
              stroke="currentColor"
              stroke-width="2"
            >
              <circle cx="12" cy="12" r="10" />
              <line x1="12" y1="16" x2="12" y2="12" />
              <line x1="12" y1="8" x2="12.01" y2="8" />
            </svg>
          </div>
          <div class="toast-body">
            <div v-if="item.title" class="toast-title">{{ item.title }}</div>
            <div class="toast-message">{{ item.message }}</div>
          </div>
          <button
            class="toast-close"
            aria-label="Close notification"
            @click="dismiss(item.id)"
          >
            <svg
              width="14"
              height="14"
              viewBox="0 0 24 24"
              fill="none"
              stroke="currentColor"
              stroke-width="2.5"
            >
              <line x1="18" y1="6" x2="6" y2="18" />
              <line x1="6" y1="6" x2="18" y2="18" />
            </svg>
          </button>
          <!-- Auto-dismiss progress bar -->
          <div class="toast-progress">
            <div
              class="toast-progress-bar"
              :style="`animation-duration: ${item.duration}ms`"
            ></div>
          </div>
        </div>
      </TransitionGroup>
    </div>
  </Teleport>
</template>

<script setup>
import { ref, computed, onUnmounted } from 'vue'

const DEFAULT_DURATION = 5000
let toastIdCounter = 0

const toasts = ref([])

const MAX_VISIBLE = 5

const visibleToasts = computed(() => {
  return toasts.value.slice(-MAX_VISIBLE)
})

/**
 * Show a toast notification.
 * @param {object} params
 * @param {string} params.message  - Required message text
 * @param {string} [params.title]  - Optional title
 * @param {'info'|'warning'|'error'|'success'} [params.level='info'] - Toast level
 * @param {number} [params.duration=5000] - Auto-dismiss duration in ms (0 = no auto-dismiss)
 */
function show({ message, title, level = 'info', duration = DEFAULT_DURATION }) {
  const id = ++toastIdCounter
  const item = {
    id,
    message,
    title,
    level,
    duration: duration > 0 ? duration : 0
  }

  toasts.value.push(item)

  // Auto-dismiss
  if (duration > 0) {
    const timer = setTimeout(() => {
      dismiss(id)
    }, duration)
    timeouts.set(id, timer)
  }

  return id
}

function dismiss(id) {
  const timer = timeouts.get(id)
  if (timer) {
    clearTimeout(timer)
    timeouts.delete(id)
  }
  const idx = toasts.value.findIndex((t) => t.id === id)
  if (idx !== -1) {
    toasts.value.splice(idx, 1)
  }
}

function dismissAll() {
  toasts.value = []
}

// Convenience methods
function info(message, title) {
  return show({ message, title, level: 'info' })
}

function warning(message, title) {
  return show({ message, title, level: 'warning', duration: 8000 })
}

function error(message, title) {
  return show({ message, title, level: 'error', duration: 10000 })
}

function success(message, title) {
  return show({ message, title, level: 'success' })
}

// P2-3: track active timeouts for cleanup on unmount
const timeouts = new Map()

onUnmounted(() => {
  timeouts.forEach((timer) => clearTimeout(timer))
  timeouts.clear()
})

defineExpose({
  show,
  dismiss,
  dismissAll,
  info,
  warning,
  error,
  success
})
</script>

<style scoped>
.toast-container {
  position: fixed;
  top: 16px;
  right: 16px;
  z-index: 9999;
  display: flex;
  flex-direction: column;
  gap: 8px;
  pointer-events: none;
  max-width: 400px;
  width: calc(100% - 32px);
}

.toast-item {
  display: flex;
  align-items: flex-start;
  gap: 10px;
  padding: 12px 14px;
  border-radius: 8px;
  background: #fff;
  box-shadow: 0 4px 12px rgba(0, 0, 0, 0.12), 0 1px 3px rgba(0, 0, 0, 0.08);
  pointer-events: auto;
  position: relative;
  overflow: hidden;
  border-left: 4px solid transparent;
}

.toast-info {
  border-left-color: #1a6ef5;
}

.toast-warning {
  border-left-color: #f59e0b;
}

.toast-error {
  border-left-color: #ef4444;
}

.toast-success {
  border-left-color: #10b981;
}

.toast-icon {
  flex-shrink: 0;
  width: 20px;
  height: 20px;
  display: flex;
  align-items: center;
  justify-content: center;
  margin-top: 1px;
}

.toast-info .toast-icon {
  color: #1a6ef5;
}

.toast-warning .toast-icon {
  color: #f59e0b;
}

.toast-error .toast-icon {
  color: #ef4444;
}

.toast-success .toast-icon {
  color: #10b981;
}

.toast-body {
  flex: 1;
  min-width: 0;
}

.toast-title {
  font-size: 13px;
  font-weight: 600;
  color: #111827;
  margin-bottom: 2px;
}

.toast-message {
  font-size: 12px;
  color: #6b7280;
  line-height: 1.4;
  word-break: break-word;
}

.toast-close {
  flex-shrink: 0;
  width: 24px;
  height: 24px;
  display: flex;
  align-items: center;
  justify-content: center;
  border: none;
  background: none;
  color: #9ca3af;
  cursor: pointer;
  border-radius: 4px;
  padding: 0;
  transition: color 0.15s, background 0.15s;
}

.toast-close:hover {
  color: #374151;
  background: #f3f4f6;
}

/* Progress bar at bottom */
.toast-progress {
  position: absolute;
  bottom: 0;
  left: 0;
  right: 0;
  height: 2px;
  background: transparent;
}

.toast-progress-bar {
  height: 100%;
  width: 100%;
  transform-origin: left;
  animation: toast-progress linear forwards;
}

.toast-info .toast-progress-bar {
  background: #1a6ef5;
}

.toast-warning .toast-progress-bar {
  background: #f59e0b;
}

.toast-error .toast-progress-bar {
  background: #ef4444;
}

.toast-success .toast-progress-bar {
  background: #10b981;
}

@keyframes toast-progress {
  from {
    transform: scaleX(1);
  }
  to {
    transform: scaleX(0);
  }
}

/* Transitions */
.toast-slide-enter-active {
  transition: all 0.3s ease-out;
}

.toast-slide-leave-active {
  transition: all 0.2s ease-in;
}

.toast-slide-enter-from {
  opacity: 0;
  transform: translateX(80px);
}

.toast-slide-leave-to {
  opacity: 0;
  transform: translateX(80px);
}

/* Responsive */
@media (max-width: 480px) {
  .toast-container {
    top: 8px;
    right: 8px;
    left: 8px;
    max-width: none;
    width: auto;
  }
}
</style>
