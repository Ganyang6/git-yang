/**
 * useSSE - Server-Sent Events Composable
 *
 * 职责：
 *   - 管理 SSE 连接生命周期（基于 fetch + ReadableStream）
 *   - Token 通过 Authorization header 传递（不再暴露于 URL query）
 *   - 事件分发（按 event type 区分：analysis_complete, alert, equipment_status_change）
 *   - 重连策略：最多 5 次，指数退避
 *   - 401 Unauthorized 时停止重连并跳转登录页
 *   - 生命周期管理（onUnmounted 时自动关闭）
 *
 * 协议参考：spec_security_auth.md 6.4 / phase3_task_assignment.md B6
 */

import { ref, onUnmounted } from 'vue'
import { getAuthToken } from '../api/index.js'

const MAX_EVENTS = 200
const MAX_RETRIES = 5
const RETRY_BASE_DELAY = 1000 // 1 second

/**
 * @param {object} options
 * @param {string} [options.url]     - SSE 端点路径（如 /sse/events），缺省从 VITE_SSE_URL 读取
 * @param {string} [options.token]   - JWT token，缺省时从 auth store 获取
 * @param {function} [options.onEvent] - 收到事件时的回调 (eventData) => void
 * @param {boolean} [options.autoConnect=true] - 是否自动建立连接
 */
export function useSSE(options = {}) {
  const {
    url = '',
    token: tokenParam,
    onEvent,
    autoConnect = true
  } = options

  // -- Reactive State --
  const isConnected = ref(false)
  const events = ref([])

  let abortController = null
  let isDestroyed = false
  let retryCount = 0
  let retryTimer = null

  // -- Build SSE URL (token is NOT included — passed via Authorization header) --
  function buildSseUrl() {
    const base = resolveBaseUrl(url)
    return base
  }

  /**
   * Resolve relative path to full SSE URL.
   * Reads VITE_SSE_URL or derives from VITE_API_BASE.
   */
  function resolveBaseUrl(path) {
    const sseUrl = import.meta.env.VITE_SSE_URL
    if (sseUrl) {
      return sseUrl
    }
    const apiBase = import.meta.env.VITE_API_BASE
    if (apiBase) {
      return `${apiBase}${path || '/sse/events'}`
    }
    // No base configured: use relative path (nginx proxy handles routing)
    return path || '/sse/events'
  }

  /**
   * Clear token on 401.
   * Does NOT redirect — the component/page handles navigation itself.
   */
  function handleUnauthorized() {
    try {
      localStorage.removeItem('mes_auth_token')
    } catch {
      // ignore storage errors
    }
  }

  /**
   * Calculate delay for next retry (exponential backoff with jitter).
   * @param {number} attempt - current retry attempt (0-based)
   * @returns {number} delay in milliseconds
   */
  function getRetryDelay(attempt) {
    const base = RETRY_BASE_DELAY * Math.pow(2, attempt)
    // Add jitter: ±25%
    const jitter = 1 + (Math.random() * 0.5 - 0.25)
    return Math.min(base * jitter, 30000) // cap at 30s
  }

  /**
   * Schedule a reconnection attempt with backoff.
   */
  function scheduleReconnect() {
    if (isDestroyed) return
    if (retryCount >= MAX_RETRIES) {
      console.warn(`[useSSE] max retries (${MAX_RETRIES}) reached, giving up`)
      isConnected.value = false
      return
    }

    const delay = getRetryDelay(retryCount)
    retryCount++
    console.log(`[useSSE] reconnecting in ${Math.round(delay)}ms (attempt ${retryCount}/${MAX_RETRIES})`)

    retryTimer = setTimeout(() => {
      if (!isDestroyed) connect()
    }, delay)
  }

  /**
   * Parse SSE text stream from ReadableStream reader.
   * Handles event: / data: / empty-line delimiters per SSE spec.
   */
  async function readStream(reader, decoder) {
    let buffer = ''
    let currentEventType = null
    let currentData = null

    while (true) {
      const { done, value } = await reader.read()
      if (done) break

      buffer += decoder.decode(value, { stream: true })

      // Parse SSE lines
      const lines = buffer.split('\n')
      buffer = lines.pop() || '' // keep incomplete line in buffer

      for (const line of lines) {
        if (line.startsWith('event: ')) {
          currentEventType = line.slice(7).trim()
        } else if (line.startsWith('data: ')) {
          const dataStr = line.slice(6).trim()
          if (!dataStr) continue
          try {
            currentData = JSON.parse(dataStr)
          } catch {
            currentData = { raw: dataStr }
          }
        } else if (line === '') {
          // Empty line = SSE event delimiter
          if (currentData !== null) {
            const type = currentEventType || 'message'
            const eventObj = {
              type,
              data: currentData,
              timestamp: Date.now()
            }

            events.value = [...events.value, eventObj].slice(-MAX_EVENTS)

            if (onEvent) {
              onEvent(eventObj)
            }

            currentEventType = null
            currentData = null
          }
        }
      }
    }
  }

  // -- Connect --
  async function connect() {
    if (isDestroyed) return
    disconnect(true)

    const t = tokenParam || getAuthToken()
    if (!t) {
      console.warn('[useSSE] no token available, cannot connect')
      scheduleReconnect()
      return
    }

    const fullUrl = buildSseUrl()
    abortController = new AbortController()

    try {
      const response = await fetch(fullUrl, {
        headers: {
          Authorization: `Bearer ${t}`
        },
        signal: abortController.signal
      })

      if (response.status === 401) {
        console.warn('[useSSE] 401 Unauthorized — stopping reconnection, clearing token')
        isConnected.value = false
        handleUnauthorized()
        // Stop reconnection, do NOT redirect
        return
      }

      if (!response.ok) {
        throw new Error(`HTTP ${response.status}: ${response.statusText}`)
      }

      // Connected successfully
      isConnected.value = true
      retryCount = 0 // Reset retry count on successful connection

      const reader = response.body.getReader()
      const decoder = new TextDecoder()
      await readStream(reader, decoder)

      // Stream ended normally — schedule reconnect if not destroyed
      if (!isDestroyed) {
        isConnected.value = false
        scheduleReconnect()
      }
    } catch (err) {
      if (err.name === 'AbortError') {
        // User aborted (disconnect was called) — normal
        return
      }

      console.warn('[useSSE] connection error:', err.message)
      isConnected.value = false
      scheduleReconnect()
    }
  }

  // -- Disconnect --
  function disconnect(silent = false) {
    if (retryTimer) {
      clearTimeout(retryTimer)
      retryTimer = null
    }

    if (abortController) {
      abortController.abort()
      abortController = null
    }

    if (!silent) {
      isConnected.value = false
    }
  }

  // -- Lifecycle --
  onUnmounted(() => {
    isDestroyed = true
    disconnect()
  })

  // -- Auto connect --
  if (autoConnect) {
    // Defer connect to next tick so token can be set
    Promise.resolve().then(() => {
      if (!isDestroyed) connect()
    })
  }

  return {
    isConnected,
    events,
    connect,
    disconnect
  }
}
