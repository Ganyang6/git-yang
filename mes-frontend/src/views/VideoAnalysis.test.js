/**
 * VideoAnalysis.vue component unit tests
 *
 * Covers:
 *   - renders page header with title
 *   - shows upload area with drag-and-drop zone
 *   - validates file format before upload
 *   - shows error for invalid file format
 *   - displays progress bar during processing
 *   - shows completion summary
 *   - shows error state with retry button
 *   - renders task history list
 *   - links to WorktimeAnalysis page on completion
 */

import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest'
import { mount, flushPromises } from '@vue/test-utils'
import { createPinia, setActivePinia } from 'pinia'
import { nextTick } from 'vue'

// Mock API functions
const mockUploadVideo = vi.fn()
const mockFetchVideoTasks = vi.fn()
const mockFetchVideoTask = vi.fn()
const mockCancelVideoTask = vi.fn()
const mockStreamVideoProgress = vi.fn()
const mockValidateVideoFile = vi.fn()
const mockFetchVideoStations = vi.fn()

vi.mock('../api/index.js', () => ({
  getAuthToken: vi.fn(() => 'test-token'),
  setAuthToken: vi.fn(),
  uploadVideo: (...args) => mockUploadVideo(...args),
  fetchVideoTasks: (...args) => mockFetchVideoTasks(...args),
  fetchVideoTask: (...args) => mockFetchVideoTask(...args),
  cancelVideoTask: (...args) => mockCancelVideoTask(...args),
  streamVideoProgress: (...args) => mockStreamVideoProgress(...args),
  validateVideoFile: (...args) => mockValidateVideoFile(...args),
  fetchVideoStations: (...args) => mockFetchVideoStations(...args)
}))

vi.stubGlobal('import_meta', {
  env: { VITE_API_BASE: 'http://localhost:8000' }
})

import VideoAnalysis from './VideoAnalysis.vue'

const MOCK_TASK_UPLOADED = {
  task_id: 'task-001',
  filename: 'video-001.mp4',
  size: 10485760,
  status: 'uploaded'
}

const MOCK_TASK_PROCESSING = {
  task_id: 'task-002',
  filename: 'video-002.mp4',
  size: 20971520,
  status: 'processing',
  progress: 0.45,
  total_frames: 500,
  processed_frames: 225
}

const MOCK_TASK_COMPLETED = {
  task_id: 'task-003',
  filename: 'video-003.mp4',
  size: 5242880,
  status: 'completed',
  progress: 1.0,
  duration_s: 32.5,
  total_frames: 300,
  processed_frames: 300,
  segments_count: 12
}

const MOCK_TASK_FAILED = {
  task_id: 'task-004',
  filename: 'video-004.mp4',
  size: 10485760,
  status: 'failed',
  error: 'Video format not supported'
}

const MOCK_TASKS = {
  items: [MOCK_TASK_COMPLETED, MOCK_TASK_PROCESSING, MOCK_TASK_UPLOADED],
  total: 3
}

const MOCK_STATIONS = [
  { id: 'WS-01', name: '工位 1' },
  { id: 'WS-02', name: '工位 2' },
  { id: 'WS-03', name: '工位 3' },
  { id: 'WS-04', name: '工位 4' }
]

function mountPage() {
  return mount(VideoAnalysis, {
    global: {
      plugins: [createPinia()],
      stubs: {
        'router-link': {
          template: '<a :href="\'#/\' + $attrs.to"><slot /></a>',
          props: ['to']
        }
      }
    },
    attachTo: document.body
  })
}

function createFile(name = 'test.mp4', size = 1024, type = 'video/mp4') {
  return new File([new ArrayBuffer(size)], name, { type })
}

describe('VideoAnalysis.vue', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    setActivePinia(createPinia())
    mockValidateVideoFile.mockReturnValue({ valid: true })
    mockStreamVideoProgress.mockReturnValue({ close: vi.fn() })
    mockFetchVideoStations.mockResolvedValue(MOCK_STATIONS)
    global.fetch = vi.fn().mockResolvedValue({
      ok: true,
      json: () => Promise.resolve({ data: MOCK_STATIONS })
    })
  })

  afterEach(() => {
    vi.restoreAllMocks()
  })

  it('renders page header with Chinese title', async () => {
    mockFetchVideoTasks.mockResolvedValue(MOCK_TASKS)
    const wrapper = mountPage()
    await flushPromises()

    expect(wrapper.find('.page-title').text()).toContain('视频分析')

    wrapper.unmount()
  })

  it('shows upload area with file input and drag zone', async () => {
    mockFetchVideoTasks.mockResolvedValue(MOCK_TASKS)
    const wrapper = mountPage()
    await flushPromises()

    const dropZone = wrapper.find('.upload-drop-zone')
    expect(dropZone.exists()).toBe(true)

    const fileInput = wrapper.find('input[type="file"]')
    expect(fileInput.exists()).toBe(true)

    // Should show station and shift selectors
    const stationSelect = wrapper.find('.station-select')
    expect(stationSelect.exists()).toBe(true)
    const shiftSelect = wrapper.find('.shift-selector')
    expect(shiftSelect.exists()).toBe(true)
    const shiftOptions = shiftSelect.findAll('option')
    expect(shiftOptions.length).toBe(4)

    wrapper.unmount()
  })

  it('validates file format before upload', async () => {
    mockFetchVideoTasks.mockResolvedValue(MOCK_TASKS)
    mockValidateVideoFile.mockReturnValue({
      valid: false,
      reason: 'Unsupported format: .exe. Allowed: mp4, avi, mov, mkv'
    })

    const wrapper = mountPage()
    await flushPromises()

    const file = createFile('malware.exe', 1024, 'application/octet-stream')
    const dropZone = wrapper.find('.upload-drop-zone')
    await dropZone.trigger('drop', {
      dataTransfer: { files: [file] }
    })
    await flushPromises()

    // Should show error, NOT call upload
    expect(mockUploadVideo).not.toHaveBeenCalled()
    expect(wrapper.text()).toContain('Unsupported format')

    wrapper.unmount()
  })

  it('calls uploadVideo and starts progress streaming on valid file', async () => {
    mockFetchVideoTasks.mockResolvedValue(MOCK_TASKS)
    mockUploadVideo.mockResolvedValue(MOCK_TASK_UPLOADED)

    const wrapper = mountPage()
    await flushPromises()

    const file = createFile('test.mp4', 1024)
    const dropZone = wrapper.find('.upload-drop-zone')
    await dropZone.trigger('drop', {
      dataTransfer: { files: [file] }
    })
    await flushPromises()

    expect(mockUploadVideo).toHaveBeenCalledWith(file, expect.any(String), expect.any(String), expect.any(String))
    expect(mockStreamVideoProgress).toHaveBeenCalled()

    wrapper.unmount()
  })

  it('displays progress bar during processing', async () => {
    mockFetchVideoTasks.mockResolvedValue(MOCK_TASKS)
    mockUploadVideo.mockResolvedValue(MOCK_TASK_UPLOADED)

    // Capture progress callback
    let progressCallback = null
    mockStreamVideoProgress.mockImplementation((taskId, onProgress) => {
      progressCallback = onProgress
      return { close: vi.fn() }
    })

    const wrapper = mountPage()
    await flushPromises()

    // Simulate file drop
    const file = createFile('test.mp4')
    await wrapper.find('.upload-drop-zone').trigger('drop', {
      dataTransfer: { files: [file] }
    })
    await flushPromises()

    // Simulate progress update
    if (progressCallback) {
      progressCallback({
        task_id: 'task-001',
        progress: 0.65,
        total_frames: 500,
        processed_frames: 325,
        status: 'processing'
      })
      await flushPromises()
      await nextTick()
    }

    // Should show progress percentage
    const text = wrapper.text()
    expect(text).toContain('65%')

    wrapper.unmount()
  })

  it('shows completion summary when processing finishes', async () => {
    mockFetchVideoTasks.mockResolvedValue(MOCK_TASKS)
    mockUploadVideo.mockResolvedValue(MOCK_TASK_UPLOADED)

    let progressCallback = null
    mockStreamVideoProgress.mockImplementation((taskId, onProgress) => {
      progressCallback = onProgress
      return { close: vi.fn() }
    })

    const wrapper = mountPage()
    await flushPromises()

    const file = createFile('test.mp4')
    await wrapper.find('.upload-drop-zone').trigger('drop', {
      dataTransfer: { files: [file] }
    })
    await flushPromises()

    if (progressCallback) {
      progressCallback({
        task_id: 'task-001',
        progress: 1.0,
        status: 'completed',
        duration_s: 32.5,
        total_frames: 300,
        processed_frames: 300
      })
      await flushPromises()
      await nextTick()
    }

    expect(wrapper.find('.task-completed').exists()).toBe(true)
    expect(wrapper.text()).toContain('分析完成')

    wrapper.unmount()
  })

  it('shows error state with retry button when processing fails', async () => {
    mockFetchVideoTasks.mockResolvedValue(MOCK_TASKS)
    mockUploadVideo.mockResolvedValue(MOCK_TASK_UPLOADED)

    let progressCallback = null
    mockStreamVideoProgress.mockImplementation((taskId, onProgress) => {
      progressCallback = onProgress
      return { close: vi.fn() }
    })

    const wrapper = mountPage()
    await flushPromises()

    const file = createFile('test.mp4')
    await wrapper.find('.upload-drop-zone').trigger('drop', {
      dataTransfer: { files: [file] }
    })
    await flushPromises()

    if (progressCallback) {
      progressCallback({
        task_id: 'task-001',
        progress: 0.15,
        status: 'failed',
        error: 'Video codec not supported'
      })
      await flushPromises()
      await nextTick()
    }

    expect(wrapper.find('.task-failed').exists()).toBe(true)
    expect(wrapper.text()).toContain('Video codec not supported')

    wrapper.unmount()
  })

  it('renders task history list', async () => {
    mockFetchVideoTasks.mockResolvedValue(MOCK_TASKS)
    const wrapper = mountPage()
    await flushPromises()

    // Should show task items
    const taskItems = wrapper.findAll('.task-item')
    expect(taskItems.length).toBe(MOCK_TASKS.items.length)

    wrapper.unmount()
  })

  it('has link to WorktimeAnalysis page after completion', async () => {
    mockFetchVideoTasks.mockResolvedValue(MOCK_TASKS)
    mockUploadVideo.mockResolvedValue(MOCK_TASK_UPLOADED)

    let progressCallback = null
    mockStreamVideoProgress.mockImplementation((taskId, onProgress) => {
      progressCallback = onProgress
      return { close: vi.fn() }
    })

    const wrapper = mountPage()
    await flushPromises()

    // Drop a file and trigger completion
    const file = createFile('test.mp4')
    await wrapper.find('.upload-drop-zone').trigger('drop', {
      dataTransfer: { files: [file] }
    })
    await flushPromises()

    if (progressCallback) {
      progressCallback({
        task_id: 'task-001',
        progress: 1.0,
        status: 'completed',
        duration_s: 32.5,
        total_frames: 300,
        processed_frames: 300
      })
      await flushPromises()
      await nextTick()
    }

    // Should now have a link to /worktime
    const anchors = wrapper.findAll('a')
    const hasWorktimeLink = anchors.some(
      (a) => {
        const href = a.attributes('href') || ''
        return href.includes('/worktime')
      }
    )
    // Fallback: check text content for the link
    const textHasLink = wrapper.text().includes('查看工时分析')
    expect(hasWorktimeLink || textHasLink).toBe(true)

    wrapper.unmount()
  })

  it('P1-1: handleCancel calls cancelVideoTask API', async () => {
    mockFetchVideoTasks.mockResolvedValue(MOCK_TASKS)
    mockUploadVideo.mockResolvedValue(MOCK_TASK_UPLOADED)
    mockCancelVideoTask.mockResolvedValue({ status: 'cancelled' })

    let progressCallback = null
    mockStreamVideoProgress.mockImplementation((taskId, onProgress) => {
      progressCallback = onProgress
      return { close: vi.fn() }
    })

    const wrapper = mountPage()
    await flushPromises()

    // Upload a file to set currentTask
    const file = createFile('test.mp4')
    await wrapper.find('.upload-drop-zone').trigger('drop', {
      dataTransfer: { files: [file] }
    })
    await flushPromises()

    // Progress to processing state
    if (progressCallback) {
      progressCallback({
        task_id: 'task-001',
        progress: 0.3,
        status: 'processing',
        total_frames: 500,
        processed_frames: 150
      })
      await flushPromises()
      await nextTick()
    }

    // Click cancel button
    const cancelBtn = wrapper.find('.btn-ghost')
    await cancelBtn.trigger('click')
    await flushPromises()

    // Should have called backend cancel API
    expect(mockCancelVideoTask).toHaveBeenCalledWith('task-001')

    wrapper.unmount()
  })

  it('P2-2: station selector defaults to first station and passes station+shift to upload', async () => {
    mockFetchVideoTasks.mockResolvedValue(MOCK_TASKS)
    mockUploadVideo.mockResolvedValue(MOCK_TASK_UPLOADED)

    const wrapper = mountPage()
    await flushPromises()

    // Default station should be first from API (WS-01)
    const stationSelect = wrapper.find('.station-select')
    expect(stationSelect.element.value).toBe('WS-01')

    // Change station to WS-03
    await stationSelect.setValue('WS-03')

    // Change shift to afternoon
    const shiftSelect = wrapper.findAll('.station-select')[1]
    await shiftSelect.setValue('afternoon')

    // Drop a file
    const file = createFile('test.mp4')
    await wrapper.find('.upload-drop-zone').trigger('drop', {
      dataTransfer: { files: [file] }
    })
    await flushPromises()

    // Should pass WS-03, 'afternoon', and line to uploadVideo
    expect(mockUploadVideo).toHaveBeenCalledWith(file, 'WS-03', 'afternoon', expect.any(String))

    wrapper.unmount()
  })

  it('P2-3: uploaded state shows spinner instead of progress bar', async () => {
    mockFetchVideoTasks.mockResolvedValue(MOCK_TASKS)
    mockUploadVideo.mockResolvedValue(MOCK_TASK_UPLOADED)

    const wrapper = mountPage()
    await flushPromises()

    // Drop a file
    const file = createFile('test.mp4')
    await wrapper.find('.upload-drop-zone').trigger('drop', {
      dataTransfer: { files: [file] }
    })
    await flushPromises()

    // Should show upload spinner, not progress bar
    expect(wrapper.find('.upload-spinner').exists()).toBe(true)
    expect(wrapper.find('.progress-bar').exists()).toBe(false)

    wrapper.unmount()
  })

  it('shows Chinese status labels in task history', async () => {
    mockFetchVideoTasks.mockResolvedValue(MOCK_TASKS)
    const wrapper = mountPage()
    await flushPromises()

    const text = wrapper.text()
    expect(text).toContain('已完成')
    expect(text).toContain('处理中')
    expect(text).toContain('已上传')

    wrapper.unmount()
  })
})
