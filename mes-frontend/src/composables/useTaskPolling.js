/**
 * Async Task Polling Manager Composable
 *
 * Provides reactive task status polling with progressive backoff.
 * Supports tracking multiple tasks simultaneously.
 * Uses the centralized API layer for auth and error handling.
 *
 * Usage:
 *   const polling = useTaskPolling({
 *     onSuccess: (taskId, result) => showResult(taskId, result),
 *     onFail: (taskId, error) => showError(taskId, error),
 *   })
 *   polling.startPolling('task-uuid')
 */

import { ref, readonly, onUnmounted } from 'vue'
import { fetchTaskStatus } from '../api/index.js'

const DEFAULT_INITIAL_INTERVAL = 2000
const DEFAULT_MAX_INTERVAL = 10000
const DEFAULT_BACKOFF_FACTOR = 1.5

export function useTaskPolling(options = {}) {
  const {
    initialInterval = DEFAULT_INITIAL_INTERVAL,
    maxInterval = DEFAULT_MAX_INTERVAL,
    backoffFactor = DEFAULT_BACKOFF_FACTOR,
    onSuccess = null,
    onFail = null,
    onProgress = null,
    onStatusChange = null,
  } = options

  const status = ref('idle')
  const progress = ref(null)
  const result = ref(null)
  const error = ref(null)
  const isPolling = ref(false)

  let pollTimer = null
  let currentInterval = initialInterval
  let activeTaskId = null

  /**
   * Poll the task status endpoint using the centralized API layer.
   */
  let pollLock = false
  async function poll() {
    if (!activeTaskId) return
    if (pollLock) return
    pollLock = true

    try {
      const data = await fetchTaskStatus(activeTaskId)
      const taskStatus = data.data?.status || data.status || 'unknown'
      const taskProgress = data.data?.progress || data.progress || null
      const taskResult = data.data?.result || data.result || null
      const taskError = data.data?.error || data.error || null

      // Capture previous status before updating
      const prevStatus = status.value
      status.value = taskStatus
      progress.value = taskProgress
      result.value = taskResult
      error.value = taskError

      if (onProgress && taskProgress !== null) {
        onProgress(taskProgress)
      }

      if (onStatusChange && prevStatus !== taskStatus) {
        onStatusChange(taskStatus)
      }

      // Reset backoff on status change to avoid long delays during transitions
      if (prevStatus !== taskStatus) {
        currentInterval = initialInterval
      }

      // Check terminal states
      if (taskStatus === 'completed') {
        stopPolling()
        if (onSuccess) onSuccess(taskResult)
        return
      }

      if (taskStatus === 'failed') {
        stopPolling()
        const err = taskError ? (taskError instanceof Error ? taskError : new Error(taskError)) : new Error('Task failed')
        error.value = err
        if (onFail) onFail(err)
        return
      }

      // Schedule next poll with backoff
      currentInterval = Math.min(
        currentInterval * backoffFactor,
        maxInterval,
      )
      pollTimer = setTimeout(poll, currentInterval)
    } catch (err) {
      error.value = err
      // Don't stop polling on network errors, just retry
      pollTimer = setTimeout(poll, currentInterval)
    } finally {
      pollLock = false
    }
  }

  /**
   * Start polling a specific task.
   *
   * @param {string} id - The task ID to poll.
   */
  function startPolling(id) {
    if (id) {
      activeTaskId = id
    }
    if (!activeTaskId) return

    stopPolling()
    currentInterval = initialInterval
    isPolling.value = true
    status.value = 'polling'
    error.value = null
    result.value = null
    progress.value = null
    pollTimer = setTimeout(poll, initialInterval)
  }

  /**
   * Stop polling.
   */
  function stopPolling() {
    if (pollTimer) {
      clearTimeout(pollTimer)
      pollTimer = null
    }
    isPolling.value = false
  }

  /**
   * Reset all state.
   */
  function reset() {
    stopPolling()
    activeTaskId = null
    status.value = 'idle'
    progress.value = null
    result.value = null
    error.value = null
  }

  onUnmounted(() => {
    stopPolling()
  })

  return {
    status: readonly(status),
    progress: readonly(progress),
    result: readonly(result),
    error: readonly(error),
    isPolling: readonly(isPolling),
    startPolling,
    stopPolling,
    reset,
  }
}
