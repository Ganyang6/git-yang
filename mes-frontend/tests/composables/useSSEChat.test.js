/**
 * useSSEChat composable tests
 *
 * Mocks fetch + ReadableStream to simulate SSE responses.
 */

import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest'

// Mock import.meta.env
vi.stubGlobal('import.meta', {
  env: {
    VITE_API_BASE: 'http://localhost:8000',
    VITE_SSE_URL: ''
  }
})

// Mock api module
vi.mock('../../src/api/index.js', () => ({
  getAuthToken: vi.fn(() => 'chat-token-789')
}))

const { useSSEChat } = await import('../../src/composables/useSSEChat.js')

/**
 * Create a mock ReadableStream that yields SSE-formatted data chunks.
 */
function createMockSSEStream(chunks, options = {}) {
  const { delay = 0, failOnRead = false } = options
  let chunkIndex = 0

  return new ReadableStream({
    async start(controller) {
      for (const chunk of chunks) {
        if (delay) await new Promise(r => setTimeout(r, delay))
        if (failOnRead && chunkIndex === chunks.length - 1) {
          controller.error(new Error('Stream interrupted'))
          return
        }
        controller.enqueue(new TextEncoder().encode(chunk))
        chunkIndex++
      }
      controller.close()
    }
  })
}

/**
 * Create a mock fetch response with SSE stream body.
 */
function createMockFetchResponse(chunks, options = {}) {
  return {
    ok: true,
    body: createMockSSEStream(chunks, options),
    text: vi.fn(() => Promise.resolve(''))
  }
}

describe('useSSEChat', () => {
  let mockFetch

  beforeEach(() => {
    vi.useFakeTimers()
    mockFetch = vi.fn()
    vi.stubGlobal('fetch', mockFetch)
  })

  afterEach(() => {
    vi.useRealTimers()
    vi.restoreAllMocks()
  })

  it('should send POST request with Authorization header from getAuthToken', async () => {
    const sseChunks = [
      'data: {"content": "Hello"}\n\n',
      'data: {"content": " World"}\n\n',
      'data: {"done": true}\n\n'
    ]
    mockFetch.mockResolvedValue(createMockFetchResponse(sseChunks))

    const { sendChat } = useSSEChat()
    const promise = sendChat('Hi there')

    // Check the fetch call
    expect(mockFetch).toHaveBeenCalledTimes(1)
    const [url, opts] = mockFetch.mock.calls[0]
    expect(url).toBe('http://localhost:8000/api/ai/chat/stream')
    expect(opts.method).toBe('POST')
    expect(opts.headers['Authorization']).toBe('Bearer chat-token-789')

    const body = JSON.parse(opts.body)
    expect(body.message).toBe('Hi there')
    expect(body.context).toBeNull()

    // Let the stream process
    await vi.runAllTimersAsync()
    await promise
  })

  it('should accumulate streamed content chunks', async () => {
    const sseChunks = [
      'data: {"content": "Part1"}\n\n',
      'data: {"content": " Part2"}\n\n',
      'data: {"content": " Part3"}\n\n'
    ]
    mockFetch.mockResolvedValue(createMockFetchResponse(sseChunks))

    const onMessage = vi.fn()
    const { sendChat, messages } = useSSEChat({ onMessage })
    const promise = sendChat('test')

    await vi.runAllTimersAsync()
    await promise

    expect(onMessage).toHaveBeenCalledTimes(3)
    expect(onMessage).toHaveBeenNthCalledWith(1, 'Part1', 'Part1')
    expect(onMessage).toHaveBeenNthCalledWith(2, ' Part2', 'Part1 Part2')
    expect(onMessage).toHaveBeenNthCalledWith(3, ' Part3', 'Part1 Part2 Part3')

    // Check final assistant message content
    const assistantMsg = messages.value.find(m => m.role === 'assistant')
    expect(assistantMsg.content).toBe('Part1 Part2 Part3')
  })

  it('should call onFallback with full event object', async () => {
    const sseChunks = [
      'data: {"type": "fallback", "message": "switching to cached response"}\n\n',
      'data: {"content": "Cached answer"}\n\n'
    ]
    mockFetch.mockResolvedValue(createMockFetchResponse(sseChunks))

    const onFallback = vi.fn()
    const { sendChat, messages } = useSSEChat({ onFallback })
    const promise = sendChat('test')

    await vi.runAllTimersAsync()
    await promise

    // Should receive the full event object, not just the message string
    expect(onFallback).toHaveBeenCalledWith({ type: 'fallback', message: 'switching to cached response' })

    const assistantMsg = messages.value.find(m => m.role === 'assistant')
    expect(assistantMsg.source).toBe('fallback')
  })

  it('should add user message before assistant message', async () => {
    const sseChunks = [
      'data: {"content": "Response"}\n\n'
    ]
    mockFetch.mockResolvedValue(createMockFetchResponse(sseChunks))

    const { sendChat, messages } = useSSEChat()
    const promise = sendChat('My question')

    // Before stream completes, check user message exists
    const userMsg = messages.value.find(m => m.role === 'user')
    expect(userMsg).toBeDefined()
    expect(userMsg.content).toBe('My question')

    await vi.runAllTimersAsync()
    await promise

    expect(messages.value.length).toBe(2)
    expect(messages.value[0].role).toBe('user')
    expect(messages.value[1].role).toBe('assistant')
  })

  it('should handle abort via abort()', async () => {
    let controller
    mockFetch.mockImplementation((_url, opts) => {
      controller = opts.signal
      return createMockFetchResponse([
        'data: {"content": "Start"}\n\n'
      ])
    })

    const { sendChat, abort, messages } = useSSEChat()
    const promise = sendChat('test')

    // Abort immediately
    abort()

    // Should set isStreaming to false
    expect(messages.value.find(m => m.isStreaming)).toBeUndefined()
  })

  it('should clear messages with clearMessages()', async () => {
    const sseChunks = [
      'data: {"content": "Response"}\n\n'
    ]
    mockFetch.mockResolvedValue(createMockFetchResponse(sseChunks))

    const { sendChat, clearMessages, messages } = useSSEChat()
    const promise = sendChat('test')

    await vi.runAllTimersAsync()
    await promise

    expect(messages.value.length).toBeGreaterThan(0)
    clearMessages()
    expect(messages.value.length).toBe(0)
  })

  it('should set error on fetch failure', async () => {
    mockFetch.mockResolvedValue({
      ok: false,
      status: 500,
      statusText: 'Internal Server Error',
      text: vi.fn(() => Promise.resolve('Internal error'))
    })

    const onError = vi.fn()
    const { sendChat, error } = useSSEChat({ onError })
    const promise = sendChat('test')

    await vi.runAllTimersAsync()
    await promise

    expect(error.value).toBe('HTTP 500: Internal Server Error')
    expect(onError).toHaveBeenCalledWith('HTTP 500: Internal Server Error')
  })

  it('should set error when token is missing', async () => {
    // Override getAuthToken to return null
    const { getAuthToken } = await import('../../src/api/index.js')
    getAuthToken.mockReturnValueOnce(null)

    const onError = vi.fn()
    const { sendChat, error, isStreaming } = useSSEChat({ onError })
    sendChat('test')

    expect(error.value).toBe('Authentication required')
    expect(onError).toHaveBeenCalledWith('Authentication required')
    expect(isStreaming.value).toBe(false)
  })

  it('should addMessage programmatically', () => {
    const { addMessage, messages } = useSSEChat()

    addMessage({ role: 'assistant', content: 'Programmatic message' })

    expect(messages.value.length).toBe(1)
    expect(messages.value[0].role).toBe('assistant')
    expect(messages.value[0].content).toBe('Programmatic message')
  })
})
