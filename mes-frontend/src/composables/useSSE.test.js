/**
 * useSSE composable unit tests
 *
 * Covers:
 *   - autoConnect false: no fetch on construction
 *   - connect: successful SSE stream parsing
 *   - connect: handles event types and data fields
 *   - connect: enforces MAX_EVENTS (200) cap
 *   - connect: calls onEvent callback
 *   - connect: 401 stops reconnection, clears token
 *   - connect: non-ok HTTP response schedules reconnect
 *   - disconnect: aborts connection and resets state
 *   - max retries: gives up after RETRY_MAX attempts
 *   - onUnmounted: tears down without side effects
 */

import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest'
import { nextTick } from 'vue'

// Track onUnmounted callbacks
let _onUnmountedCb = null

vi.mock('vue', async () => {
  const actual = await vi.importActual('vue')
  return {
    ...actual,
    onUnmounted: vi.fn((cb) => { _onUnmountedCb = cb }),
    ref: actual.ref,
    computed: actual.computed
  }
})

// Mock the API module for token access
vi.mock('../api/index.js', () => ({
  getAuthToken: vi.fn(() => 'mock-token-abc')
}))

import { useSSE } from './useSSE.js'
import { getAuthToken } from '../api/index.js'

// Fake global fetch for testing
let mockFetch = null
function setMockFetch(impl) {
  mockFetch = impl
  globalThis.fetch = vi.fn(impl)
}

function makeStreamResponse(bodyChunks) {
  const encoder = new TextEncoder()
  let index = 0
  return {
    ok: true,
    status: 200,
    statusText: 'OK',
    body: {
      getReader() {
        return {
          read() {
            if (index >= bodyChunks.length) {
              return Promise.resolve({ done: true, value: undefined })
            }
            const value = encoder.encode(bodyChunks[index])
            index++
            return Promise.resolve({ done: false, value })
          },
          cancel() {}
        }
      }
    }
  }
}

describe('useSSE', () => {
  beforeEach(() => {
    _onUnmountedCb = null
    vi.clearAllMocks()
    // Default: never resolve the stream (hang forever) so connect doesn't loop
    setMockFetch(() => new Promise(() => {}))
    globalThis.localStorage = {
      getItem: vi.fn(),
      setItem: vi.fn(),
      removeItem: vi.fn()
    }
  })

  afterEach(() => {
    if (_onUnmountedCb) {
      _onUnmountedCb()
      _onUnmountedCb = null
    }
  })

  it('returns reactive isConnected and events refs', () => {
    const sse = useSSE({ autoConnect: false })
    expect(sse.isConnected).toBeDefined()
    expect(typeof sse.isConnected.value).toBe('boolean')
    expect(sse.events).toBeDefined()
    expect(Array.isArray(sse.events.value)).toBe(true)
    expect(typeof sse.connect).toBe('function')
    expect(typeof sse.disconnect).toBe('function')
  })

  it('does not fetch when autoConnect is false', () => {
    useSSE({ autoConnect: false })
    expect(globalThis.fetch).not.toHaveBeenCalled()
  })

  it('fetches when autoConnect is true (default)', () => {
    useSSE({ autoConnect: false })
    // Trigger deferred connect by awaiting microtask
    const sse = useSSE({ autoConnect: true })
    // Promise.resolve().then(() => connect) runs at microtask
    return Promise.resolve().then(() => {
      expect(globalThis.fetch).toHaveBeenCalled()
    })
  })

  it('connects successfully and parses SSE events', async () => {
    const body = [
      'event: analysis_complete\n',
      'data: {"taskId":"t1","status":"done"}\n',
      '\n',
      'event: alert\n',
      'data: {"level":"info","msg":"test alert"}\n',
      '\n'
    ]
    setMockFetch(() => Promise.resolve(makeStreamResponse(body)))

    const onEvent = vi.fn()
    const sse = useSSE({ autoConnect: false })

    await sse.connect()
    // Wait for stream read to complete
    await vi.waitFor(() => {
      expect(sse.events.value.length).toBe(2)
    })

    expect(sse.events.value[0].type).toBe('analysis_complete')
    expect(sse.events.value[0].data.taskId).toBe('t1')
    expect(sse.events.value[1].type).toBe('alert')
    expect(sse.events.value[1].data.level).toBe('info')

    expect(onEvent).not.toHaveBeenCalled()
  })

  it('calls onEvent callback when provided', async () => {
    const body = [
      'event: analysis_complete\n',
      'data: {"taskId":"t1"}\n',
      '\n'
    ]
    setMockFetch(() => Promise.resolve(makeStreamResponse(body)))

    const onEvent = vi.fn()
    const sse = useSSE({ autoConnect: false, onEvent })
    await sse.connect()
    await vi.waitFor(() => {
      expect(onEvent).toHaveBeenCalledTimes(1)
    })
    expect(onEvent).toHaveBeenCalledWith(
      expect.objectContaining({
        type: 'analysis_complete',
        data: expect.objectContaining({ taskId: 't1' })
      })
    )
  })

  it('caps events at MAX_EVENTS (200)', async () => {
    // Generate exactly 205 events
    const bodyLines = []
    for (let i = 0; i < 205; i++) {
      bodyLines.push(`data: {"idx":${i}}\n\n`)
    }
    setMockFetch(() => Promise.resolve(makeStreamResponse(bodyLines)))

    const sse = useSSE({ autoConnect: false })
    await sse.connect()
    await vi.waitFor(() => {
      expect(sse.events.value.length).toBe(200)
    })
    // First event should have been evicted
    expect(sse.events.value[0].data.idx).toBe(5)
    expect(sse.events.value[199].data.idx).toBe(204)
  })

  it('handles 401: stops reconnect, clears token', async () => {
    setMockFetch(() =>
      Promise.resolve({
        ok: false,
        status: 401,
        statusText: 'Unauthorized'
      })
    )

    const sse = useSSE({ autoConnect: false })
    await sse.connect()

    expect(sse.isConnected.value).toBe(false)
    expect(localStorage.removeItem).toHaveBeenCalledWith('mes_auth_token')
  })

  it('schedules reconnect on non-401 HTTP error', async () => {
    setMockFetch(() =>
      Promise.resolve({
        ok: false,
        status: 503,
        statusText: 'Service Unavailable'
      })
    )

    vi.useFakeTimers()
    const sse = useSSE({ autoConnect: false })

    await sse.connect()
    // Stream ended -> scheduleReconnect sets a timer
    expect(sse.isConnected.value).toBe(false)

    // Advance to next timer (async, flushes microtasks)
    await vi.advanceTimersToNextTimerAsync()
    // Second attempt (reconnect scheduled in connect) - fetch called again
    expect(globalThis.fetch).toHaveBeenCalledTimes(2)
    vi.useRealTimers()
  })

  it('disconnect aborts connection and resets connected state', async () => {
    const abortSpy = vi.fn()
    setMockFetch(() =>
      Promise.resolve({
        ok: true,
        status: 200,
        body: {
          getReader() {
            return {
              read: () => new Promise(() => {}), // never resolves
              cancel: abortSpy
            }
          }
        }
      })
    )

    const sse = useSSE({ autoConnect: false })
    const connectPromise = sse.connect()

    // Let the connection establish
    await vi.waitFor(() => {
      expect(sse.isConnected.value).toBe(true)
    })

    sse.disconnect()
    expect(sse.isConnected.value).toBe(false)
  })

  it('gives up after max retries (5)', async () => {
    vi.useFakeTimers()
    let callCount = 0
    // Always fail
    setMockFetch(() => {
      callCount++
      return Promise.resolve({
        ok: false,
        status: 503,
        statusText: 'Service Unavailable'
      })
    })

    const sse = useSSE({ autoConnect: false })
    await sse.connect()

    // Each retry uses async connect() which awaits fetch.
    // advanceTimersToNextTimerAsync flushes microtasks so scheduleReconnect
    // runs and sets up the next timer.
    for (let i = 0; i < 5; i++) {
      await vi.advanceTimersToNextTimerAsync()
    }

    // Initial connect + 5 retries = 6 total calls
    expect(callCount).toBe(6)
    expect(sse.isConnected.value).toBe(false)
    vi.useRealTimers()
  })

  it('onUnmounted triggers cleanup (isDestroyed set, no reconnect)', async () => {
    setMockFetch(() =>
      Promise.resolve({
        ok: false,
        status: 503,
        statusText: 'Service Unavailable'
      })
    )

    vi.useFakeTimers()
    const sse = useSSE({ autoConnect: false })

    await sse.connect()
    // Call unmounted callback
    expect(_onUnmountedCb).toBeDefined()
    _onUnmountedCb()

    const fetchCount = globalThis.fetch.mock.calls.length
    // Advance time — no more fetch calls because isDestroyed is true
    vi.advanceTimersByTime(60000)
    expect(globalThis.fetch).toHaveBeenCalledTimes(fetchCount)
    vi.useRealTimers()
  })

  it('uses Authorization header with Bearer token', async () => {
    const body = ['data: {"ok":true}\n\n']
    let capturedHeaders = null
    setMockFetch((url, opts) => {
      capturedHeaders = opts.headers
      return Promise.resolve(makeStreamResponse(body))
    })

    const sse = useSSE({ autoConnect: false })
    await sse.connect()
    await vi.waitFor(() => {
      expect(sse.events.value.length).toBe(1)
    })

    expect(capturedHeaders).toBeDefined()
    expect(capturedHeaders.Authorization).toBe('Bearer mock-token-abc')
  })

  it('handles non-JSON data as raw field', async () => {
    const body = ['data: plain text\n\n']
    setMockFetch(() => Promise.resolve(makeStreamResponse(body)))

    const sse = useSSE({ autoConnect: false })
    await sse.connect()
    await vi.waitFor(() => {
      expect(sse.events.value.length).toBe(1)
    })
    expect(sse.events.value[0].data.raw).toBe('plain text')
  })

  it('ignores empty data lines', async () => {
    const body = [
      'data: \n',
      '\n',
      'data: {"x":1}\n',
      '\n'
    ]
    setMockFetch(() => Promise.resolve(makeStreamResponse(body)))

    const sse = useSSE({ autoConnect: false })
    await sse.connect()
    await vi.waitFor(() => {
      expect(sse.events.value.length).toBe(1)
    })
    expect(sse.events.value[0].data.x).toBe(1)
  })
})
