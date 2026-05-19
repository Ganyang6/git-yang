/**
 * Shared confirmation dialog composable.
 * Replaces native confirm() calls for consistent UI.
 */
import { ref } from 'vue'

const isOpen = ref(false)
const title = ref('')
const message = ref('')
let _resolve = null
let _isOpen = false

function openConfirm(opts = {}) {
  // P1-3: Guard against concurrent openConfirm() calls.
  // When a second call arrives while one is already open,
  // reject the prior pending promise to prevent permanent leak.
  if (_isOpen) {
    const err = new Error('A confirm dialog is already open')
    if (_resolve) {
      _resolve(false)
      _resolve = null
    }
    _isOpen = false
    return Promise.reject(err)
  }
  title.value = opts.title || 'Confirm'
  message.value = opts.message || ''
  isOpen.value = true
  _isOpen = true
  return new Promise(resolve => {
    _resolve = resolve
  })
}

function handleConfirm() {
  isOpen.value = false
  _isOpen = false
  if (_resolve) { _resolve(true); _resolve = null }
}

function handleCancel() {
  isOpen.value = false
  _isOpen = false
  if (_resolve) { _resolve(false); _resolve = null }
}

export function useConfirm() {
  return {
    confirmOpen: isOpen,
    confirmTitle: title,
    confirmMessage: message,
    openConfirm,
    handleConfirm,
    handleCancel,
  }
}
