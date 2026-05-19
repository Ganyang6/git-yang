/**
 * AiAnalysis page SSE streaming tests
 *
 * Tests the integration of useSSEChat, useTaskPolling,
 * ChatMessage, TaskStatusCard, and FallbackBadge in AiAnalysis.vue.
 */

import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest'
import { mount, flushPromises } from '@vue/test-utils'
import { ref } from 'vue'

// Mock import.meta.env
vi.stubGlobal('import.meta', {
  env: {
    VITE_API_BASE: 'http://localhost:8000'
  }
})

// ─── Mock API functions ───────────────────────────────────────────────────────
const mockFetchAiContext = vi.fn()
const mockSendAiChat = vi.fn()
const mockFetchAiStatus = vi.fn()
const mockFetchAiHealth = vi.fn()
const mockSubmitAiTask = vi.fn()
const mockCancelTask = vi.fn()

vi.mock('../../src/api/index.js', () => ({
  fetchAiContext: (...args) => mockFetchAiContext(...args),
  sendAiChat: (...args) => mockSendAiChat(...args),
  fetchAiStatus: (...args) => mockFetchAiStatus(...args),
  fetchAiHealth: (...args) => mockFetchAiHealth(...args),
  submitAiTask: (...args) => mockSubmitAiTask(...args),
  cancelTask: (...args) => mockCancelTask(...args),
  getAuthToken: vi.fn(() => 'test-token'),
  setAuthToken: vi.fn()
}))

// ─── Mock composables ────────────────────────────────────────────────────────
vi.mock('../../src/composables/useSSEChat.js', () => {
  const { ref, readonly } = require('vue')
  return {
    useSSEChat: () => ({
      messages: readonly(ref([])),
      isStreaming: readonly(ref(false)),
      error: readonly(ref(null)),
      sendChat: vi.fn(),
      addMessage: vi.fn(),
      abort: vi.fn(),
      clearMessages: vi.fn()
    })
  }
})

vi.mock('../../src/composables/useTaskPolling.js', () => ({
  useTaskPolling: () => ({
    taskId: ref(null),
    status: ref(null),
    progress: ref(0),
    result: ref(null),
    isPolling: ref(false),
    error: ref(null),
    startPolling: vi.fn(),
    stopPolling: vi.fn(),
    reset: vi.fn()
  })
}))

// Import components after mocking
const AiAnalysis = (await import('../../src/views/AiAnalysis.vue')).default
const ChatMessage = (await import('../../src/components/ChatMessage.vue')).default
const FallbackBadge = (await import('../../src/components/FallbackBadge.vue')).default
const TaskStatusCard = (await import('../../src/components/TaskStatusCard.vue')).default

// ─── Component Tests ─────────────────────────────────────────────────────────

describe('ChatMessage', () => {
  const mountOptions = {
    global: {
      stubs: {
        FallbackBadge: true
      }
    }
  }

  it('should render user message with correct avatar', () => {
    const wrapper = mount(ChatMessage, {
      props: {
        role: 'user',
        content: 'Hello AI',
        timestamp: Date.now()
      },
      ...mountOptions
    })

    expect(wrapper.text()).toContain('ME')
    expect(wrapper.text()).toContain('Hello AI')
    expect(wrapper.find('.msg-row.user').exists()).toBe(true)
  })

  it('should render assistant message with correct avatar', () => {
    const wrapper = mount(ChatMessage, {
      props: {
        role: 'assistant',
        content: 'Hello human',
        timestamp: Date.now()
      },
      ...mountOptions
    })

    expect(wrapper.text()).toContain('AI')
    expect(wrapper.text()).toContain('Hello human')
    expect(wrapper.find('.msg-row.assistant').exists()).toBe(true)
  })

  it('should show typing indicator when streaming', () => {
    const wrapper = mount(ChatMessage, {
      props: {
        role: 'assistant',
        content: '',
        isStreaming: true,
        timestamp: null
      },
      ...mountOptions
    })

    expect(wrapper.find('.typing-indicator').exists()).toBe(true)
  })

  it('should render markdown content as HTML', () => {
    const wrapper = mount(ChatMessage, {
      props: {
        role: 'assistant',
        content: '**Bold** and *italic*',
        timestamp: Date.now()
      },
      ...mountOptions
    })

    const html = wrapper.find('.msg-content').html()
    expect(html).toContain('<strong>Bold</strong>')
    expect(html).toContain('<em>italic</em>')
  })

  it('should show fallback badge when isFallback is true', () => {
    const wrapper = mount(ChatMessage, {
      props: {
        role: 'assistant',
        content: 'Cached response',
        isFallback: true,
        fallbackSeverity: 'cache',
        timestamp: Date.now()
      },
      ...mountOptions
    })

    expect(wrapper.findComponent(FallbackBadge).exists()).toBe(true)
    expect(wrapper.findComponent(FallbackBadge).props('visible')).toBe(true)
  })
})

describe('FallbackBadge', () => {
  it('should render cache severity badge', () => {
    const wrapper = mount(FallbackBadge, {
      props: { severity: 'cache', visible: true }
    })
    expect(wrapper.find('.fallback-badge.cache').exists()).toBe(true)
    expect(wrapper.text()).toContain('AI 服务降级')
  })

  it('should render rule severity badge', () => {
    const wrapper = mount(FallbackBadge, {
      props: { severity: 'rule', visible: true }
    })
    expect(wrapper.find('.fallback-badge.rule').exists()).toBe(true)
  })

  it('should hide when visible is false', () => {
    const wrapper = mount(FallbackBadge, {
      props: { severity: 'cache', visible: false }
    })
    expect(wrapper.find('.fallback-badge').exists()).toBe(false)
  })
})

describe('TaskStatusCard', () => {
  const defaultProps = {
    taskId: 'task-001',
    analysisType: 'worktime',
    status: 'pending',
    progress: 0,
    result: null,
    error: '',
    createdAt: Date.now(),
    params: {},
    cancelling: false
  }

  it('should render task type correctly', () => {
    const wrapper = mount(TaskStatusCard, { props: defaultProps })
    expect(wrapper.text()).toContain('工时分析')
  })

  it('should show progress bar when processing', () => {
    const wrapper = mount(TaskStatusCard, {
      props: { ...defaultProps, status: 'processing', progress: 65 }
    })
    expect(wrapper.find('.progress-bar').exists()).toBe(true)
    expect(wrapper.text()).toContain('65%')
  })

  it('should emit cancel event when cancel button clicked', async () => {
    const wrapper = mount(TaskStatusCard, {
      props: { ...defaultProps, status: 'processing' }
    })

    await wrapper.find('.btn-cancel').trigger('click')
    expect(wrapper.emitted('cancel')).toBeTruthy()
    expect(wrapper.emitted('cancel')[0]).toEqual(['task-001'])
  })

  it('should emit view event for completed tasks', async () => {
    const wrapper = mount(TaskStatusCard, {
      props: {
        ...defaultProps,
        status: 'completed',
        result: { summary: 'Analysis complete' }
      }
    })

    await wrapper.find('.btn-view').trigger('click')
    expect(wrapper.emitted('view')).toBeTruthy()
  })

  it('should emit retry event for failed tasks', async () => {
    const wrapper = mount(TaskStatusCard, {
      props: {
        ...defaultProps,
        status: 'failed',
        error: 'API timeout'
      }
    })

    await wrapper.find('.btn-retry').trigger('click')
    expect(wrapper.emitted('retry')).toBeTruthy()
    expect(wrapper.emitted('retry')[0]).toEqual([{ analysisType: 'worktime', params: {} }])
  })

  it('should display result text for completed tasks', () => {
    const wrapper = mount(TaskStatusCard, {
      props: {
        ...defaultProps,
        status: 'completed',
        result: 'Long analysis result text that should be truncated'
      }
    })

    expect(wrapper.find('.task-result').exists()).toBe(true)
    expect(wrapper.text()).toContain('Long analysis result')
  })

  it('should display error message for failed tasks', () => {
    const wrapper = mount(TaskStatusCard, {
      props: {
        ...defaultProps,
        status: 'failed',
        error: 'Connection refused'
      }
    })

    expect(wrapper.find('.task-error').exists()).toBe(true)
    expect(wrapper.text()).toContain('Connection refused')
  })

  it('should apply correct border color based on status', () => {
    const pendingWrapper = mount(TaskStatusCard, { props: defaultProps })
    const completedWrapper = mount(TaskStatusCard, { props: { ...defaultProps, status: 'completed' } })
    const failedWrapper = mount(TaskStatusCard, { props: { ...defaultProps, status: 'failed' } })

    expect(pendingWrapper.find('.task-card.pending').exists()).toBe(true)
    expect(completedWrapper.find('.task-card.completed').exists()).toBe(true)
    expect(failedWrapper.find('.task-card.failed').exists()).toBe(true)
  })
})

describe('AiAnalysis', () => {
  beforeEach(() => {
    mockFetchAiContext.mockResolvedValue({
      balanceRate: 78,
      bottleneckStation: 'WS-03',
      taktTime: 45,
      lostCapacity: 120,
      utilization: 72,
      stdtimeAchievement: 85,
      wasteRatio: 28
    })
    mockFetchAiStatus.mockResolvedValue({ configured: true, model: 'deepseek-chat', api_url: 'https://api.deepseek.com' })
    mockFetchAiHealth.mockResolvedValue({
      deepseek_ok: true,
      cache_hit_rate: 35,
      task_success_rate: 92,
      avg_response_ms: 2300
    })
    mockSubmitAiTask.mockResolvedValue({ task_id: 'celery-task-001' })
    mockCancelTask.mockResolvedValue({})
  })

  afterEach(() => {
    vi.restoreAllMocks()
  })

  it('should mount without errors', async () => {
    const wrapper = mount(AiAnalysis, {
      global: {
        stubs: {
          ChatMessage: true,
          TaskStatusCard: true,
          FallbackBadge: true
        }
      }
    })

    await flushPromises()

    expect(wrapper.find('.ai-page').exists()).toBe(true)
    expect(wrapper.find('.page-title').text()).toContain('AI 深度分析')
  })

  it('should load AI context on mount', async () => {
    const wrapper = mount(AiAnalysis, {
      global: {
        stubs: {
          ChatMessage: true,
          TaskStatusCard: true,
          FallbackBadge: true
        }
      }
    })

    await flushPromises()

    expect(mockFetchAiContext).toHaveBeenCalledTimes(1)
    expect(mockFetchAiStatus).toHaveBeenCalledTimes(1)
    expect(mockFetchAiHealth).toHaveBeenCalledTimes(1)
  })

  it('should display line data after context loads', async () => {
    const wrapper = mount(AiAnalysis, {
      global: {
        stubs: {
          ChatMessage: true,
          TaskStatusCard: true,
          FallbackBadge: true
        }
      }
    })

    await flushPromises()

    expect(wrapper.text()).toContain('78%')   // balanceRate
    expect(wrapper.text()).toContain('WS-03')  // bottleneck
    expect(wrapper.text()).toContain('45s')    // taktTime
  })
})
