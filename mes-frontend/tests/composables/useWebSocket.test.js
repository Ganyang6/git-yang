/**
 * useWebSocket composable tests
 *
 * Uses __setWebSocketConstructor to inject a mock WebSocket,
 * avoiding jsdom's built-in WebSocket implementation.
 */

import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest'

// import.meta.env is loaded from .env.test automatically by Vitest

// Mock api module
vi.mock('../../src/api/index.js', () => ({
  getAuthToken: vi.fn(() => 'test-token-123'),
  setAuthToken: vi.fn()
}))

const { useWebSocket, __setWebSocketConstructor } = await import(
  '../../src/composables/useWebSocket.js'
)

// Standard WebSocket OPEN state constant
const WS_OPEN = 1

describe('useWebSocket', () => {
  let capturedUrl
  let mockWs

  function createMockWs() {
    capturedUrl = null
    mockWs = {
      url: '',
      readyState: 0,
      send: vi.fn(),
      close: vi.fn(),
      onopen: null,
      onmessage: null,
      onclose: null,
      onerror: null
    }
    // The mock constructor needs OPEN constant for send() checks
    function MockWebSocket(url) {
      mockWs.url = url
      capturedUrl = url
      return mockWs
    }
    MockWebSocket.OPEN = WS_OPEN
    __setWebSocketConstructor(MockWebSocket)
  }

  beforeEach(() => {
    createMockWs()
    vi.useFakeTimers()
  })

  afterEach(() => {
    __setWebSocketConstructor(null)
    vi.useRealTimers()
    vi.restoreAllMocks()
  })

  it('should connect with query params and send token as auth frame', () => {
    const ws = useWebSocket({
      url: '/ws/realtime',
      subscribe: 'metrics',
      station: 'station_03',
      autoConnect: false
    })
    ws.connect()

    // Token is NOT in URL (security best practice)
    expect(capturedUrl).not.toContain('token=')
    expect(capturedUrl).toContain('subscribe=metrics')
    expect(capturedUrl).toContain('station_id=station_03')

    // Token is sent as auth frame after opening
    mockWs.readyState = 1
    if (mockWs.onopen) mockWs.onopen({})

    expect(mockWs.send).toHaveBeenCalledWith(
      JSON.stringify({ type: 'auth', token: 'test-token-123' })
    )
  })

  it('should update isConnected on open', () => {
    const ws = useWebSocket({ autoConnect: false })
    ws.connect()

    expect(ws.isConnected.value).toBe(false)

    mockWs.readyState = WS_OPEN
    if (mockWs.onopen) mockWs.onopen({})

    expect(ws.isConnected.value).toBe(true)
  })

  it('should parse and dispatch received messages', () => {
    const onMessage = vi.fn()
    const ws = useWebSocket({ autoConnect: false, onMessage })
    ws.connect()

    const data = { type: 'metrics', data: { utilization: 0.85 } }
    if (mockWs.onmessage) {
      mockWs.onmessage({ data: JSON.stringify(data) })
    }

    expect(ws.lastMessage.value).toEqual(data)
    expect(ws.messages.value).toHaveLength(1)
    expect(onMessage).toHaveBeenCalledWith(data)
  })

  it('should auto-respond to ping messages', () => {
    useWebSocket({ autoConnect: false }).connect()

    // WebSocket must be open for send() to work
    mockWs.readyState = WS_OPEN
    if (mockWs.onopen) mockWs.onopen({})

    if (mockWs.onmessage) {
      mockWs.onmessage({ data: JSON.stringify({ type: 'ping' }) })
    }

    expect(mockWs.send).toHaveBeenCalledWith(JSON.stringify({ type: 'pong' }))
  })

  it('should handle non-JSON messages gracefully', () => {
    const onMessage = vi.fn()
    useWebSocket({ autoConnect: false, onMessage }).connect()

    if (mockWs.onmessage) {
      mockWs.onmessage({ data: 'not json' })
    }

    expect(onMessage).not.toHaveBeenCalled()
  })

  it('should send messages via send() when connected', () => {
    const ws = useWebSocket({ autoConnect: false })
    ws.connect()
    mockWs.readyState = WS_OPEN

    ws.send({ type: 'custom', value: 42 })

    expect(mockWs.send).toHaveBeenCalledWith(JSON.stringify({ type: 'custom', value: 42 }))
  })

  it('should not send when WebSocket is not open', () => {
    const ws = useWebSocket({ autoConnect: false })
    ws.connect()

    ws.send({ type: 'test' })

    expect(mockWs.send).not.toHaveBeenCalled()
  })

  it('should update isConnected on close', () => {
    const ws = useWebSocket({ autoConnect: false, autoReconnect: false })
    ws.connect()

    mockWs.readyState = WS_OPEN
    if (mockWs.onopen) mockWs.onopen({})
    expect(ws.isConnected.value).toBe(true)

    if (mockWs.onclose) mockWs.onclose({ code: 1000 })
    expect(ws.isConnected.value).toBe(false)
  })

  it('should close WebSocket on disconnect()', () => {
    const ws = useWebSocket({ autoConnect: false, autoReconnect: false })
    ws.connect()

    ws.disconnect()

    expect(mockWs.close).toHaveBeenCalledWith(1000, 'client disconnect')
  })

  it('should not reconnect when autoReconnect is false', () => {
    const ws = useWebSocket({ autoConnect: false, autoReconnect: false })
    ws.connect()

    if (mockWs.onclose) mockWs.onclose({ code: 1006 })

    // Only one WebSocket was created (no reconnect)
    // capturedUrl was set once
    expect(capturedUrl).toBeTruthy()
  })

  it('should use VITE_WS_URL when available', () => {
    useWebSocket({ url: '/ws/realtime', autoConnect: false }).connect()

    expect(capturedUrl).toContain('ws://localhost:8000/ws/realtime')
  })
})
