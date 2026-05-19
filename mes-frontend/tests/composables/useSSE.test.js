/**
 * useSSE composable tests
 *
 * Tests fetch + ReadableStream based SSE implementation.
 * Token is passed via Authorization header, not URL query params.
 * 401 stops reconnection + redirects. Max 5 retries with backoff.
 */

import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest'

vi.mock('../../src/api/index.js', () => ({
  getAuthToken: vi.fn(() => 'sse-token-456')
}))

const { useSSE } = await import('../../src/composables/useSSE.js')

/**
 * Helper: create a mock fetch response with SSE stream data.
 */
function makeSseResponse(chunks, status = 200) {
  const chunkList = Array.isArray(chunks) ? chunks : [chunks]
  let idx = 0
  const encoder = new TextEncoder()
  return {
    ok: status >= 200 && status < 300,
    status,
    statusText: status === 401 ? 'Unauthorized' : 'OK',
    body: {
      getReader: vi.fn(() => ({
        read: async () => {
          if (idx >= chunkList.length) return { done: true, value: undefined }
          return { done: false, value: encoder.encode(chunkList[idx++]) }
        }
      }))
    }
  }
}

describe('useSSE (fetch + ReadableStream)', () => {
  let origLocation

  beforeEach(() => {
    origLocation = window.location
    globalThis.fetch = vi.fn()
    vi.stubEnv('VITE_API_BASE', 'http://test.test')

    Object.defineProperty(window, 'location', {
      value: { pathname: '/dashboard', href: '' },
      writable: true,
      configurable: true
    })

    const store = {}
    Object.defineProperty(window, 'localStorage', {
      value: {
        getItem: vi.fn((k) => store[k] || null),
        setItem: vi.fn((k, v) => { store[k] = String(v) }),
        removeItem: vi.fn((k) => { delete store[k] }),
        clear: vi.fn(() => { Object.keys(store).forEach(k => delete store[k]) })
      },
      writable: true,
      configurable: true
    })

    Object.defineProperty(window, 'sessionStorage', {
      value: {
        getItem: vi.fn(() => null),
        setItem: vi.fn(),
        removeItem: vi.fn()
      },
      writable: true,
      configurable: true
    })
  })

  afterEach(() => {
    Object.defineProperty(window, 'location', {
      value: origLocation,
      writable: true,
      configurable: true
    })
    vi.restoreAllMocks()
  })

  // ============================================
  // Token / Security
  // ============================================

  it('passes token via Authorization header, NOT in URL', async () => {
    globalThis.fetch.mockResolvedValue(makeSseResponse('', 200))
    const { connect } = useSSE({ url: '/sse/events', autoConnect: false })
    connect()
    // Let connect() reach the await fetch
    await Promise.resolve()

    expect(globalThis.fetch).toHaveBeenCalledWith(
      expect.not.stringContaining('token='),
      expect.objectContaining({
        headers: expect.objectContaining({
          Authorization: 'Bearer sse-token-456'
        })
      })
    )
  })

  it('does not append any query string to the URL', async () => {
    globalThis.fetch.mockResolvedValue(makeSseResponse('', 200))
    const { connect } = useSSE({ url: '/sse/events', autoConnect: false })
    connect()
    await Promise.resolve()

    const url = globalThis.fetch.mock.calls[0][0]
    expect(url).not.toContain('?')
  })

  it('uses the token passed in options over the auth store', async () => {
    globalThis.fetch.mockResolvedValue(makeSseResponse('', 200))
    const { connect } = useSSE({
      url: '/sse/events',
      autoConnect: false,
      token: 'custom'
    })
    connect()
    await Promise.resolve()

    expect(globalThis.fetch).toHaveBeenCalledWith(
      expect.any(String),
      expect.objectContaining({
        headers: expect.objectContaining({ Authorization: 'Bearer custom' })
      })
    )
  })

  it('does NOT call fetch when no token is available', async () => {
    const { getAuthToken } = await import('../../src/api/index.js')
    getAuthToken.mockReturnValueOnce(null)
    const { connect } = useSSE({ autoConnect: false, token: null })
    connect()
    expect(globalThis.fetch).not.toHaveBeenCalled()
  })

  // ============================================
  // Event parsing
  // ============================================

  it('dispatches named SSE events', async () => {
    const onEvent = vi.fn()
    globalThis.fetch.mockResolvedValue(makeSseResponse(
      'event: analysis_complete\ndata: {"summary":"done"}\n\n' +
      'event: alert\ndata: {"level":"warn"}\n\n'
    ))

    useSSE({ url: '/sse/events', autoConnect: false, onEvent }).connect()
    await Promise.resolve() // fetch resolves → isConnected set → readStream starts
    await Promise.resolve() // first reader.read() resolves
    await Promise.resolve() // second reader.read() (done) resolves

    expect(onEvent).toHaveBeenCalledTimes(2)
    expect(onEvent).toHaveBeenCalledWith(
      expect.objectContaining({ type: 'analysis_complete', data: { summary: 'done' } })
    )
    expect(onEvent).toHaveBeenCalledWith(
      expect.objectContaining({ type: 'alert', data: { level: 'warn' } })
    )
  })

  it('treats events without "event:" prefix as "message"', async () => {
    const onEvent = vi.fn()
    globalThis.fetch.mockResolvedValue(makeSseResponse('data: {"status":"ok"}\n\n'))
    useSSE({ url: '/sse/events', autoConnect: false, onEvent }).connect()
    await Promise.resolve()
    await Promise.resolve()

    expect(onEvent).toHaveBeenCalledWith(
      expect.objectContaining({ type: 'message', data: { status: 'ok' } })
    )
  })

  it('handles non-JSON data as { raw: string }', async () => {
    const onEvent = vi.fn()
    globalThis.fetch.mockResolvedValue(makeSseResponse('event: alert\ndata: plain\n\n'))
    useSSE({ url: '/sse/events', autoConnect: false, onEvent }).connect()
    await Promise.resolve()
    await Promise.resolve()

    expect(onEvent).toHaveBeenCalledWith(
      expect.objectContaining({ type: 'alert', data: { raw: 'plain' } })
    )
  })

  it('accumulates events in the events array', async () => {
    globalThis.fetch.mockResolvedValue(makeSseResponse(
      'event: alert\ndata: {"msg":"a"}\n\nevent: alert\ndata: {"msg":"b"}\n\n'
    ))
    const { connect, events } = useSSE({ autoConnect: false })
    connect()
    await Promise.resolve()
    await Promise.resolve()

    expect(events.value).toHaveLength(2)
  })

  // ============================================
  // Connection state
  // ============================================

  it('returns isConnected as false initially', () => {
    const { isConnected } = useSSE({ autoConnect: false })
    expect(isConnected.value).toBe(false)
  })

  it('sets isConnected to true after successful fetch', async () => {
    globalThis.fetch.mockResolvedValue(makeSseResponse('data: {}\n\n'))
    const { connect, isConnected } = useSSE({ autoConnect: false })
    connect()
    await Promise.resolve() // fetch resolves → isConnected = true
    expect(isConnected.value).toBe(true)
  })

  it('sets isConnected to false on disconnect', async () => {
    globalThis.fetch.mockResolvedValue(makeSseResponse('data: {}\n\n'))
    const { connect, disconnect, isConnected } = useSSE({ autoConnect: false })
    connect()
    await Promise.resolve()
    expect(isConnected.value).toBe(true)
    disconnect()
    expect(isConnected.value).toBe(false)
  })

  // ============================================
  // 401 handling
  // ============================================

  it('clears token on 401 (useSSE does NOT redirect — api/index.js request() handles redirect)', async () => {
    globalThis.fetch.mockResolvedValue(makeSseResponse('', 401))
    const { connect } = useSSE({ autoConnect: false })

    delete window.location
    window.location = { pathname: '/dashboard', href: '' }

    connect()
    await Promise.resolve()

    expect(localStorage.removeItem).toHaveBeenCalledWith('mes_auth_token')
    // useSSE composable only clears token, does NOT redirect
    expect(window.location.href).toBe('')
  })

  it('does NOT redirect if already on /login', async () => {
    globalThis.fetch.mockResolvedValue(makeSseResponse('', 401))
    const { connect } = useSSE({ autoConnect: false })

    delete window.location
    window.location = { pathname: '/login', href: '' }

    connect()
    await Promise.resolve()
    expect(window.location.href).toBe('')
  })

  // ============================================
  // Retry with fake timers
  // ============================================

  it('reconnects after stream ends normally', async () => {
    vi.useFakeTimers()
    let callCount = 0
    globalThis.fetch.mockImplementation(async () => {
      callCount++
      // First call: sends real data. Subsequent: empty (stream ends immediately).
      return callCount === 1
        ? makeSseResponse('data: {"x":1}\n\n')
        : makeSseResponse('', 200)
    })

    const { connect } = useSSE({ autoConnect: false })
    connect()

    // Flush all pending microtasks so scheduleReconnect has called setTimeout
    for (let i = 0; i < 10; i++) {
      await Promise.resolve()
    }

    // Advance past the scheduled reconnect (~1s with jitter)
    vi.advanceTimersByTime(3000)

    // Flush microtasks from the reconnect callback
    for (let i = 0; i < 10; i++) {
      await Promise.resolve()
    }

    expect(callCount).toBeGreaterThanOrEqual(2)
    vi.useRealTimers()
  }, 10000)

  it('stops reconnecting after MAX_RETRIES (5)', async () => {
    vi.useFakeTimers()
    let callCount = 0
    // Simulate persistent server errors so retryCount is NOT reset
    globalThis.fetch.mockImplementation(async () => {
      callCount++
      return { ok: false, status: 500, statusText: 'Server Error' }
    })

    const { connect } = useSSE({ autoConnect: false })
    connect()

    // Flush microtasks so scheduleReconnect has called setTimeout
    for (let i = 0; i < 10; i++) {
      await Promise.resolve()
    }

    // Advance through retry delays
    for (let i = 0; i < 8; i++) {
      vi.advanceTimersByTime(40000)
      for (let j = 0; j < 10; j++) {
        await Promise.resolve()
      }
    }

    // Initial connect (1) + up to MAX_RETRIES (5) = max 6
    expect(callCount).toBeLessThanOrEqual(6)
    vi.useRealTimers()
  }, 15000)
})
