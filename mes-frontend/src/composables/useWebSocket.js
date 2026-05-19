/**
 * useWebSocket - WebSocket 实时数据 Composable
 *
 * 职责：
 *   - 管理 WebSocket 连接生命周期（自动连接/断线重连/组件卸载关闭）
 *   - 心跳响应（自动回复服务端 ping）
 *   - 消息分发（按 type 字段路由到 onMessage 回调）
 *   - Token 注入（连接后通过 auth 帧发送，避免 URL 暴露）
 *   - 优雅降级（连接失败时降级为定时轮询）
 *
 * 协议参考：spec_security_auth.md 7. WebSocket 安全
 * 消息格式参考：spec_redis_streams.md 2.3 mes:metrics
 */

import { ref, shallowRef, onUnmounted } from 'vue'
import { getAuthToken } from '../api/index.js'

const RECONNECT_BASE_DELAY = 1000
const RECONNECT_MAX_DELAY = 30000
const RECONNECT_MAX_RETRIES = 10
const PING_TIMEOUT_MS = 10000
const FALLBACK_POLL_INTERVAL = 5000
const MAX_MESSAGES = 200
const AUTH_TIMEOUT_MS = 5000

// Allow injecting WebSocket constructor (useful for testing)
let _WebSocket = null
function getWebSocketConstructor() {
  return _WebSocket || WebSocket
}

/**
 * Override WebSocket constructor (for testing only).
 * @param {Function} ctor
 */
export function __setWebSocketConstructor(ctor) {
  _WebSocket = ctor
}

/**
 * @param {object} options
 * @param {string} options.url           - WebSocket 服务地址（含路径，如 /ws/metrics）
 * @param {string} [options.token]       - JWT token，缺省时从 auth store 获取
 * @param {string} [options.subscribe]   - 订阅类型，逗号分隔（如 "metrics,pose_frames"）
 * @param {string} [options.station]     - 工位标识（如 "station_03"）
 * @param {function} [options.onMessage] - 收到消息时的回调 (messageData) => void
 * @param {boolean} [options.autoReconnect=true] - 是否自动重连
 * @param {boolean} [options.autoConnect=true]  - 是否自动建立连接
 */
export function useWebSocket(options = {}) {
  const {
    url = '',
    token: tokenParam,
    subscribe = 'metrics',
    station = '',
    onMessage,
    autoReconnect = true,
    autoConnect = true
  } = options

  // -- Reactive State --
  const isConnected = ref(false)
  const isReconnecting = ref(false)
  const messages = shallowRef([])
  const lastMessage = shallowRef(null)
  const reconnectAttempt = ref(0)

  let ws = null
  let reconnectTimer = null
  let pingTimer = null
  let pingTimeoutTimer = null
  let fallbackPollTimer = null
  let isDestroyed = false

  // -- Build full WebSocket URL (no token in URL) --
  function buildWsUrl() {
    const base = url.startsWith('ws') ? url : resolveBaseUrl(url)
    const params = new URLSearchParams()
    if (subscribe) params.set('subscribe', subscribe)
    if (station) params.set('station_id', station)
    const qs = params.toString()
    return qs ? `${base}?${qs}` : base
  }

  /**
   * Resolve relative path to full WebSocket URL.
   * Reads VITE_WS_URL or derives from VITE_API_BASE.
   */
  function resolveBaseUrl(path) {
    const wsUrl = import.meta.env.VITE_WS_URL
    if (wsUrl) {
      // wsUrl is full address like ws://localhost:8000/ws/metrics
      return wsUrl
    }
    const apiBase = import.meta.env.VITE_API_BASE
    if (apiBase) {
      const wsBase = apiBase.replace(/^http/, 'ws')
      return `${wsBase}${path}`
    }
    // No base configured: derive from current page location (nginx proxy)
    const proto = window.location.protocol === 'https:' ? 'wss:' : 'ws:'
    return `${proto}//${window.location.host}${path}`
  }

  // -- Connect --
  function connect() {
    if (isDestroyed) return
    disconnect(true)

    const fullUrl = buildWsUrl()
    let wsInstance
    try {
      wsInstance = new (getWebSocketConstructor())(fullUrl)
    } catch (err) {
      console.warn('[ws] connection failed, falling back to polling:', err.message)
      if (autoReconnect) {
        startFallbackPolling()
      }
      return
    }

    ws = wsInstance

    ws.onopen = () => {
      if (isDestroyed) return
      isConnected.value = true
      isReconnecting.value = false
      reconnectAttempt.value = 0
      stopFallbackPolling()
      if (wsRecoveryTimer) { clearTimeout(wsRecoveryTimer); wsRecoveryTimer = null }

      // Send auth frame immediately after connecting
      const t = tokenParam || getAuthToken()
      if (t) {
        send({ type: 'auth', token: t })
        startPingCheck()
      } else {
        // No token available - close and don't reconnect
        console.warn('[ws] no token available, closing connection')
        ws.close(4001, 'No auth token')
      }
    }

    ws.onmessage = (event) => {
      if (isDestroyed) return
      try {
        const data = JSON.parse(event.data)

        // Handle auth response
        if (data.type === 'auth_ok') {
          // Authentication confirmed - connection is fully ready
          return
        }
        if (data.type === 'auth_failed' || data.type === 'auth_error') {
          console.warn('[ws] authentication failed, closing')
          ws.close(4001, 'Authentication failed')
          return
        }

        // Auto-respond to ping
        if (data.type === 'ping') {
          send({ type: 'pong' })
          return
        }

        lastMessage.value = data
        // Append to messages (shallowRef with array spread to trigger reactivity)
        messages.value = [...messages.value, data].slice(-MAX_MESSAGES)

        if (onMessage) {
          onMessage(data)
        }
      } catch {
        // Non-JSON message, ignore
      }
    }

    ws.onclose = (event) => {
      if (isDestroyed) return
      isConnected.value = false
      stopPingCheck()

      // Code 4001 = auth rejected, no reconnect
      if (event.code === 4001) {
        return
      }

      if (autoReconnect && !isDestroyed) {
        scheduleReconnect()
      }
    }

    ws.onerror = () => {
      // onclose will fire after onerror, reconnect handled there
    }
  }

  // -- Send --
  function send(data) {
    const WS = getWebSocketConstructor()
    if (ws && ws.readyState === WS.OPEN) {
      ws.send(typeof data === 'string' ? data : JSON.stringify(data))
    }
  }

  // -- Disconnect --
  function disconnect(silent = false) {
    stopPingCheck()
    clearReconnectTimer()
    stopFallbackPolling()
    if (wsRecoveryTimer) { clearTimeout(wsRecoveryTimer); wsRecoveryTimer = null }

    if (ws) {
      try {
        ws.close(1000, silent ? '' : 'client disconnect')
      } catch {
        // ignore
      }
      ws = null
    }

    if (!silent) {
      isConnected.value = false
      isReconnecting.value = false
      reconnectAttempt.value = 0
    }
  }

  let wsRecoveryTimer = null

  // -- Reconnect with exponential backoff --
  function scheduleReconnect() {
    if (reconnectAttempt.value >= RECONNECT_MAX_RETRIES) {
      isReconnecting.value = false
      // Exhausted fast retries, start fallback polling and schedule recovery attempt
      startFallbackPolling()
      // Try to reconnect via WebSocket every 5 minutes while in fallback
      wsRecoveryTimer = setTimeout(() => {
        if (!isDestroyed && !ws) {
          console.info('[ws] recovery attempt after fallback polling')
          reconnectAttempt.value = 0
          stopFallbackPolling()
          if (wsRecoveryTimer) { clearTimeout(wsRecoveryTimer); wsRecoveryTimer = null }
          scheduleReconnect()
        }
      }, 300000)
      return
    }

    isReconnecting.value = true
    clearReconnectTimer()

    const delay = Math.min(
      RECONNECT_BASE_DELAY * Math.pow(2, reconnectAttempt.value),
      RECONNECT_MAX_DELAY
    )
    reconnectAttempt.value++

    reconnectTimer = setTimeout(() => {
      if (!isDestroyed) {
        connect()
      }
    }, delay)
  }

  function clearReconnectTimer() {
    if (reconnectTimer) {
      clearTimeout(reconnectTimer)
      reconnectTimer = null
    }
  }

  // -- Ping/Pong heartbeat monitoring --
  function startPingCheck() {
    stopPingCheck()
    let lastMessageTime = Date.now()

    // Track last message time
    const originalOnMessage = ws.onmessage
    ws.onmessage = (event) => {
      lastMessageTime = Date.now()
      if (originalOnMessage) originalOnMessage.call(ws, event)
    }

    pingTimer = setInterval(() => {
      if (isDestroyed) return
      // If no message received within PING_TIMEOUT_MS, consider connection dead
      if (Date.now() - lastMessageTime > PING_TIMEOUT_MS) {
        ws.close(4000, 'Ping timeout')
      }
    }, 20000)
  }

  function stopPingCheck() {
    if (pingTimer) {
      clearInterval(pingTimer)
      pingTimer = null
    }
    if (pingTimeoutTimer) {
      clearTimeout(pingTimeoutTimer)
      pingTimeoutTimer = null
    }
  }

  // -- Fallback polling (degradation when WebSocket unavailable) --
  function startFallbackPolling() {
    if (fallbackPollTimer) return
    isReconnecting.value = false

    // Poll the REST API endpoint as fallback
    fallbackPollTimer = setInterval(async () => {
      if (isDestroyed) return
      try {
        const apiBase = import.meta.env.VITE_API_BASE || ''
        const t = tokenParam || getAuthToken()
        const headers = { 'Content-Type': 'application/json' }
        if (t) headers['Authorization'] = `Bearer ${t}`

        const url = apiBase ? `${apiBase}/api/dashboard/kpi` : '/api/dashboard/kpi'
        const res = await fetch(url, { headers })
        if (res.ok) {
          const data = await res.json()
          const wrapped = { type: 'metrics', data }
          lastMessage.value = wrapped
          messages.value = [...messages.value, wrapped].slice(-MAX_MESSAGES)
          if (onMessage) onMessage(wrapped)
        }
      } catch {
        // Silent fail during polling
      }
    }, FALLBACK_POLL_INTERVAL)
  }

  function stopFallbackPolling() {
    if (fallbackPollTimer) {
      clearInterval(fallbackPollTimer)
      fallbackPollTimer = null
    }
  }

  // -- Lifecycle --
  onUnmounted(() => {
    isDestroyed = true
    disconnect()
  })

  // -- Auto connect --
  if (autoConnect) {
    // Defer connect to next tick so that token can be set after composable creation
    Promise.resolve().then(() => {
      if (!isDestroyed) connect()
    })
  }

  return {
    isConnected,
    isReconnecting,
    messages,
    lastMessage,
    connect,
    disconnect,
    send
  }
}
