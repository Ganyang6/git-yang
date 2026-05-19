/**
 * useTaskPolling composable tests
 *
 * Mocks fetchTaskStatus API to simulate task lifecycle.
 */

import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest'

// Mock import.meta.env
vi.stubGlobal('import.meta', {
  env: {
    VITE_API_BASE: 'http://localhost:8000'
  }
})

// Mock api module -- fetchTaskStatus returns {code:0, message:"success", data:{...}}
vi.mock('../../src/api/index.js', () => ({
  fetchTaskStatus: vi.fn((taskId) => Promise.resolve({
    code: 0,
    message: 'success',
    data: {
      task_id: taskId,
      status: 'processing',
      progress: 50,
      result: null,
      error: null
    }
  }))
}))

const { useTaskPolling } = await import('../../src/composables/useTaskPolling.js')

describe('useTaskPolling', () => {
  beforeEach(async () => {
    vi.useFakeTimers()
    const mod = await import('../../src/api/index.js')
    mod.fetchTaskStatus.mockReset()
  })

  afterEach(() => {
    vi.useRealTimers()
    vi.restoreAllMocks()
  })

  it('should start polling and accept taskId via startPolling()', async () => {
    const { fetchTaskStatus } = await import('../../src/api/index.js')
    fetchTaskStatus.mockResolvedValue({
      code: 0,
      message: 'success',
      data: { task_id: 'task-001', status: 'pending', progress: 0, result: null, error: null }
    })

    const { startPolling, isPolling, status } = useTaskPolling()

    startPolling('task-001')

    expect(isPolling.value).toBe(true)
    expect(status.value).toBe('polling')

    // Advance to trigger first poll
    await vi.advanceTimersByTimeAsync(2000)
    expect(fetchTaskStatus).toHaveBeenCalledWith('task-001')
  })

  it('should update status and progress from API response', async () => {
    const { fetchTaskStatus } = await import('../../src/api/index.js')
    fetchTaskStatus.mockResolvedValue({
      code: 0,
      message: 'success',
      data: { task_id: 'task-002', status: 'processing', progress: 50, result: null, error: null }
    })

    const onSuccess = vi.fn()
    const { startPolling, status, progress } = useTaskPolling({ onSuccess })

    startPolling('task-002')

    // Advance timers to trigger first poll
    await vi.advanceTimersByTimeAsync(2000)

    expect(fetchTaskStatus).toHaveBeenCalledWith('task-002')
    expect(status.value).toBe('processing')
    expect(progress.value).toBe(50)
  })

  it('should stop polling when task completes', async () => {
    const { fetchTaskStatus } = await import('../../src/api/index.js')

    // First call: processing, second call: completed
    fetchTaskStatus
      .mockResolvedValueOnce({
        code: 0, message: 'success',
        data: { task_id: 'task-003', status: 'processing', progress: 80, result: null, error: null }
      })
      .mockResolvedValueOnce({
        code: 0, message: 'success',
        data: { task_id: 'task-003', status: 'completed', progress: 100, result: { summary: 'Done' }, error: null }
      })

    const onSuccess = vi.fn()
    const { startPolling, isPolling, status, result } = useTaskPolling({ onSuccess })

    startPolling('task-003')

    // Advance enough time for first poll + async resolution
    await vi.advanceTimersByTimeAsync(5000)
    expect(status.value).toBe('completed')
    expect(isPolling.value).toBe(false)
    expect(result.value).toEqual({ summary: 'Done' })
    expect(onSuccess).toHaveBeenCalledWith({ summary: 'Done' })
    expect(fetchTaskStatus).toHaveBeenCalledTimes(2)

    // No more polls should happen
    const callCount = fetchTaskStatus.mock.calls.length
    await vi.advanceTimersByTimeAsync(10000)
    expect(fetchTaskStatus).toHaveBeenCalledTimes(callCount)
  })

  it('should stop polling when task fails', async () => {
    const { fetchTaskStatus } = await import('../../src/api/index.js')
    fetchTaskStatus.mockResolvedValue({
      code: 0,
      message: 'success',
      data: { task_id: 'task-004', status: 'failed', progress: 30, result: null, error: 'API timeout' }
    })

    const onFail = vi.fn()
    const { startPolling, isPolling, status, error } = useTaskPolling({ onFail })

    startPolling('task-004')

    await vi.advanceTimersByTimeAsync(2000)

    expect(status.value).toBe('failed')
    expect(isPolling.value).toBe(false)
    expect(error.value).toBeInstanceOf(Error)
    expect(error.value.message).toBe('API timeout')
    expect(onFail).toHaveBeenCalled()
  })

  it('should use progressive backoff', async () => {
    const { fetchTaskStatus } = await import('../../src/api/index.js')
    fetchTaskStatus.mockResolvedValue({
      code: 0, message: 'success',
      data: { task_id: 'task-005', status: 'pending', progress: 0, result: null, error: null }
    })

    const { startPolling } = useTaskPolling()
    startPolling('task-005')

    // First poll at 2s
    await vi.advanceTimersByTimeAsync(2000)
    expect(fetchTaskStatus).toHaveBeenCalledTimes(1)

    // Second poll at ~3s (backoff = 2s * 1.5 = 3s)
    await vi.advanceTimersByTimeAsync(3000)
    expect(fetchTaskStatus).toHaveBeenCalledTimes(2)

    // Third poll at ~4.5s (backoff = 3s * 1.5 = 4.5s)
    await vi.advanceTimersByTimeAsync(5000)
    expect(fetchTaskStatus).toHaveBeenCalledTimes(3)
  })

  it('should stop polling on stopPolling()', async () => {
    const { fetchTaskStatus } = await import('../../src/api/index.js')
    fetchTaskStatus.mockResolvedValue({
      code: 0, message: 'success',
      data: { task_id: 'task-007', status: 'pending', progress: 0, result: null, error: null }
    })

    const { startPolling, stopPolling, isPolling } = useTaskPolling()
    startPolling('task-007')

    await vi.advanceTimersByTimeAsync(2000)
    expect(fetchTaskStatus).toHaveBeenCalledTimes(1)

    stopPolling()
    expect(isPolling.value).toBe(false)

    // No more polls
    const callCount = fetchTaskStatus.mock.calls.length
    await vi.advanceTimersByTimeAsync(10000)
    expect(fetchTaskStatus).toHaveBeenCalledTimes(callCount)
  })

  it('should reset all state with reset()', async () => {
    const { fetchTaskStatus } = await import('../../src/api/index.js')
    fetchTaskStatus.mockResolvedValue({
      code: 0, message: 'success',
      data: { task_id: 'task-008', status: 'pending', progress: 0, result: null, error: null }
    })

    const { startPolling, reset, status, progress, error, result } = useTaskPolling()
    startPolling('task-008')

    await vi.advanceTimersByTimeAsync(2000)

    reset()

    expect(status.value).toBe('idle')
    expect(progress.value).toBeNull()
    expect(result.value).toBeNull()
    expect(error.value).toBeNull()
  })

  it('should call onStatusChange when status changes', async () => {
    const { fetchTaskStatus } = await import('../../src/api/index.js')
    fetchTaskStatus.mockResolvedValue({
      code: 0, message: 'success',
      data: { task_id: 'task-009', status: 'processing', progress: 20, result: null, error: null }
    })

    const onStatusChange = vi.fn()
    const { startPolling } = useTaskPolling({ onStatusChange })
    startPolling('task-009')

    // First poll: status changes from initial 'polling' to 'processing'
    await vi.advanceTimersByTimeAsync(2000)
    expect(onStatusChange).toHaveBeenCalledWith('processing')
  })

  it('should handle network error with retry', async () => {
    const { fetchTaskStatus } = await import('../../src/api/index.js')
    fetchTaskStatus
      .mockRejectedValueOnce(new Error('Network error'))
      .mockResolvedValue({
        code: 0, message: 'success',
        data: { task_id: 'task-010', status: 'completed', progress: 100, result: { data: 'ok' }, error: null }
      })

    const { startPolling, status, result } = useTaskPolling()
    startPolling('task-010')

    // First poll fails
    await vi.advanceTimersByTimeAsync(2000)

    // Second poll succeeds (backoff increased)
    await vi.advanceTimersByTimeAsync(3000)

    expect(status.value).toBe('completed')
    expect(result.value).toEqual({ data: 'ok' })
  })

  it('should not poll when startPolling called without id and no prior id', async () => {
    const { fetchTaskStatus } = await import('../../src/api/index.js')
    const { startPolling, isPolling } = useTaskPolling()

    startPolling()

    expect(isPolling.value).toBe(false)
    expect(fetchTaskStatus).not.toHaveBeenCalled()
  })
})
