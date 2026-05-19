/**
 * Video API unit tests
 *
 * Covers:
 *   - uploadVideo: FormData multipart upload
 *   - fetchVideoTasks: GET task list
 *   - fetchVideoTask: GET single task
 *   - cancelVideoTask: POST cancel
 *   - streamVideoProgress: SSE connection with close function
 */

import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest'

// Stub import.meta.env before any module that uses it
vi.stubGlobal('import_meta', {
  env: { VITE_API_BASE: 'http://localhost:8000' }
})

// Track fetch calls
let _fetchCalls = []
let _mockFetch

function setupMockFetch(resolver) {
  _fetchCalls = []
  _mockFetch = vi.fn(async (url, options) => {
    _fetchCalls.push({ url, options })
    return resolver(url, options)
  })
  vi.stubGlobal('fetch', _mockFetch)
}

function mockJsonResponse(data, status = 200) {
  return {
    ok: status >= 200 && status < 300,
    status,
    json: async () => data
  }
}

describe('Video API', () => {
  beforeEach(() => {
    const mockStorage = {}
    Object.defineProperty(window, 'localStorage', {
      value: {
        getItem: vi.fn(k => mockStorage[k] ?? null),
        setItem: vi.fn((k, v) => { mockStorage[k] = v }),
        removeItem: vi.fn(k => { delete mockStorage[k] }),
        clear: vi.fn(() => { Object.keys(mockStorage).forEach(k => delete mockStorage[k]) }),
      },
      writable: true,
    })
    vi.clearAllMocks()
    localStorage.clear()
  })

  afterEach(() => {
    vi.restoreAllMocks()
  })

  describe('uploadVideo', () => {
    it('sends FormData with file and station_id via multipart', async () => {
      const mockBlob = new Blob(['video-data'], { type: 'video/mp4' })
      const mockFile = new File([mockBlob], 'test.mp4', { type: 'video/mp4' })
      const taskData = {
        task_id: 'uuid-123',
        filename: 'uuid-123.mp4',
        size: 1024,
        status: 'uploaded'
      }

      setupMockFetch(() => mockJsonResponse({ code: 0, message: 'success', data: taskData }))

      // Dynamic import to get fresh module state
      const { uploadVideo } = await import('./index.js')

      const result = await uploadVideo(mockFile, 'WS-01', 'morning')

      expect(_fetchCalls.length).toBe(1)
      expect(_fetchCalls[0].url).toContain('/api/v1/video/upload')

      // Should NOT set Content-Type (let browser set multipart boundary)
      const headers = _fetchCalls[0].options.headers || {}
      expect(headers['Content-Type']).toBeUndefined()

      // Body should be FormData
      expect(_fetchCalls[0].options.body).toBeInstanceOf(FormData)

      // Should return unwrapped data
      expect(result).toEqual(taskData)
      expect(result.task_id).toBe('uuid-123')
    })

    it('includes station_id in FormData', async () => {
      const mockFile = new File(['data'], 'test.mp4', { type: 'video/mp4' })
      setupMockFetch(() =>
        mockJsonResponse({ code: 0, message: 'success', data: { task_id: 'id-1' } })
      )

      const { uploadVideo } = await import('./index.js')

      await uploadVideo(mockFile, 'WS-02', 'night')

      const formData = _fetchCalls[0].options.body
      expect(formData.get('station_id')).toBe('WS-02')
      expect(formData.get('shift')).toBe('night')
      expect(formData.get('file').name).toBe('test.mp4')
    })

    it('throws error when upload fails (413)', async () => {
      const mockFile = new File(['big-video'], 'big.mp4', { type: 'video/mp4' })
      setupMockFetch(() =>
        mockJsonResponse({ code: 1, message: 'File too large' }, 413)
      )

      const { uploadVideo } = await import('./index.js')

      await expect(uploadVideo(mockFile, 'WS-01', 'morning')).rejects.toThrow('File too large')
    })
  })

  describe('fetchVideoTasks', () => {
    it('returns task list from API', async () => {
      const tasks = {
        items: [
          { task_id: 't1', status: 'completed', filename: 'a.mp4' },
          { task_id: 't2', status: 'processing', filename: 'b.mp4' }
        ],
        total: 2
      }
      setupMockFetch(() => mockJsonResponse({ code: 0, message: 'success', data: tasks }))

      const { fetchVideoTasks } = await import('./index.js')

      const result = await fetchVideoTasks()

      expect(_fetchCalls[0].url).toContain('/api/v1/video/tasks')
      expect(result).toEqual(tasks)
    })
  })

  describe('fetchVideoTask', () => {
    it('returns single task detail', async () => {
      const task = { task_id: 't1', status: 'processing', progress: 0.5 }
      setupMockFetch(() => mockJsonResponse({ code: 0, message: 'success', data: task }))

      const { fetchVideoTask } = await import('./index.js')

      const result = await fetchVideoTask('t1')

      expect(_fetchCalls[0].url).toContain('/api/v1/video/tasks/t1')
      expect(result).toEqual(task)
    })
  })

  describe('cancelVideoTask', () => {
    it('sends cancel request', async () => {
      setupMockFetch(() =>
        mockJsonResponse({ code: 0, message: 'success', data: { status: 'cancelled' } })
      )

      const { cancelVideoTask } = await import('./index.js')

      const result = await cancelVideoTask('t1')

      expect(_fetchCalls[0].url).toContain('/api/v1/video/tasks/t1/cancel')
      expect(_fetchCalls[0].options.method).toBe('POST')
      expect(result.status).toBe('cancelled')
    })
  })

  describe('streamVideoProgress', () => {
    it('creates SSE connection and returns close function', async () => {
      let capturedUrl = ''
      let capturedAbortSignal = null

      // Mock fetch to capture URL and return a response with a readable stream
      const mockReader = {
        read: vi.fn().mockResolvedValueOnce({ done: true, value: undefined }),
        cancel: vi.fn(),
      }
      const originalFetch = globalThis.fetch
      vi.stubGlobal('fetch', vi.fn(async (url, opts) => {
        capturedUrl = typeof url === 'string' ? url : url.toString()
        capturedAbortSignal = opts?.signal || null
        return {
          ok: true,
          status: 200,
          body: {
            getReader: () => mockReader,
          },
        }
      }))

      const { streamVideoProgress } = await import('./index.js')
      const { close } = streamVideoProgress('task-abc', vi.fn())

      // Wait for microtick (autoConnect defers via Promise.resolve().then)
      await new Promise((r) => setTimeout(r, 10))

      expect(capturedUrl).toContain('/api/v1/video/tasks/task-abc/stream')
      expect(typeof close).toBe('function')
      close()
      // close() aborts the AbortController; verify the signal was captured
      expect(capturedAbortSignal).not.toBeNull()

      vi.stubGlobal('fetch', originalFetch)
    })

    it('does not auto-connect when autoConnect is false', async () => {
      const originalFetch = globalThis.fetch
      const mockFetch = vi.fn()
      vi.stubGlobal('fetch', mockFetch)

      const { streamVideoProgress } = await import('./index.js')
      streamVideoProgress('task-abc', vi.fn(), { autoConnect: false })

      // Wait a tick to ensure no async connect was triggered
      await new Promise((r) => setTimeout(r, 10))
      expect(mockFetch).not.toHaveBeenCalled()

      vi.stubGlobal('fetch', originalFetch)
    })
  })
})
