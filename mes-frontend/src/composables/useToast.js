/**
 * P2 #95: Shared toast notification composable
 * Replaces duplicated showToast/toasts implementations across 5+ Vue pages.
 *
 * Usage:
 *   const { toasts, showToast } = useToast()
 *   showToast('操作成功', 'success')
 */
import { ref } from 'vue'

const _timers = new Map()
const MAX_TOASTS = 10

/**
 * @param {string} message
 * @param {'success'|'warning'|'error'|'info'} type
 * @param {number} duration - auto-dismiss time in ms (default 3000)
 */
function showToast(message, type = 'success', duration = 3000) {
  // Prevent unbounded growth
  if (toasts.value.length >= MAX_TOASTS) {
    const oldest = toasts.value[0]
    if (_timers.has(oldest.id)) { clearTimeout(_timers.get(oldest.id)); _timers.delete(oldest.id) }
    toasts.value = toasts.value.slice(1)
  }
  const id = Date.now() + Math.random()
  toasts.value.push({ id, message, type })
  if (_timers.has(id)) clearTimeout(_timers.get(id))
  _timers.set(id, setTimeout(() => {
    toasts.value = toasts.value.filter(t => t.id !== id)
    _timers.delete(id)
  }, duration))
}

/**
 * @param {number} id
 */
function dismissToast(id) {
  toasts.value = toasts.value.filter(t => t.id !== id)
  if (_timers.has(id)) {
    clearTimeout(_timers.get(id))
    _timers.delete(id)
  }
}

/**
 * @param {'success'|'warning'|'error'|'info'} type
 */
function dismissByType(type) {
  toasts.value = toasts.value.filter(t => {
    if (t.type === type) {
      if (_timers.has(t.id)) { clearTimeout(_timers.get(t.id)); _timers.delete(t.id) }
      return false
    }
    return true
  })
}

// Module-level shared state (singleton across all consumers)
const toasts = ref([])

export function useToast() {
  return { toasts, showToast, dismissToast, dismissByType }
}
