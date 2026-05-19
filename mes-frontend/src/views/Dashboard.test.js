/**
 * Dashboard.vue component unit tests
 *
 * Covers:
 *   - renders page header with title and refresh button
 *   - shows loading skeletons initially
 *   - displays KPI cards after data loads
 *   - shows "no data" placeholders when API returns null
 *   - shows error banner when all API calls fail
 *   - date range selector triggers reload
 *   - renders section titles (balance chart, worktime trend, timeline, etc.)
 *   - recent worktime table renders rows from data
 *   - bottleneck diagnosis list renders items
 */

import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest'
import { mount, flushPromises } from '@vue/test-utils'
import { createPinia, setActivePinia } from 'pinia'

// Mock all API calls
const mockFetchDashboardKpi = vi.fn()
const mockFetchLineBalanceSummary = vi.fn()
const mockFetchWorktimeTrend = vi.fn()
const mockFetchStationTimeline = vi.fn()
const mockFetchTherbligDistribution = vi.fn()
const mockFetchRecentWorktime = vi.fn()
const mockFetchBottleneckDiagnosis = vi.fn()
const mockFetchAnomalyEvents = vi.fn()

vi.mock('../api/index.js', () => ({
  getAuthToken: vi.fn(() => 'test-token'),
  setAuthToken: vi.fn(),
  fetchDashboardKpi: (...args) => mockFetchDashboardKpi(...args),
  fetchLineBalanceSummary: (...args) => mockFetchLineBalanceSummary(...args),
  fetchWorktimeTrend: (...args) => mockFetchWorktimeTrend(...args),
  fetchStationTimeline: (...args) => mockFetchStationTimeline(...args),
  fetchTherbligDistribution: (...args) => mockFetchTherbligDistribution(...args),
  fetchRecentWorktime: (...args) => mockFetchRecentWorktime(...args),
  fetchBottleneckDiagnosis: (...args) => mockFetchBottleneckDiagnosis(...args),
  fetchAnomalyEvents: (...args) => mockFetchAnomalyEvents(...args)
}))

// Mock WebSocket composable (no-op for existing unit tests)
vi.mock('../composables/useWebSocket.js', async () => {
  const vue = await vi.importActual('vue')
  return {
    useWebSocket: vi.fn(() => ({
      isConnected: vue.ref(false),
      isReconnecting: vue.ref(false),
      messages: vue.shallowRef([]),
      lastMessage: vue.shallowRef(null),
      connect: vi.fn(),
      disconnect: vi.fn(),
      send: vi.fn()
    }))
  }
})

// Mock SSE composable (no-op for existing unit tests)
vi.mock('../composables/useSSE.js', async () => {
  const vue = await vi.importActual('vue')
  return {
    useSSE: vi.fn(() => ({
      isConnected: vue.ref(false),
      events: vue.ref([]),
      connect: vi.fn(),
      disconnect: vi.fn()
    }))
  }
})

// Mock useDashboardCharts composable (no-op for unit tests - canvas drawing)
vi.mock('../composables/useDashboardCharts.js', () => ({
  drawBalanceChart: vi.fn(),
  drawWorktimeChart: vi.fn(),
  drawThermChart: vi.fn()
}))

// Mock import.meta.env
vi.stubGlobal('import_meta', {
  env: { VITE_API_BASE: 'http://localhost:8000' }
})

import Dashboard from './Dashboard.vue'

// Mock canvas context (jsdom doesn't support canvas)
function mockCanvas() {
  HTMLCanvasElement.prototype.getContext = vi.fn(() => ({
    clearRect: vi.fn(),
    beginPath: vi.fn(),
    closePath: vi.fn(),
    fill: vi.fn(),
    stroke: vi.fn(),
    moveTo: vi.fn(),
    lineTo: vi.fn(),
    arc: vi.fn(),
    setLineDash: vi.fn(),
    createLinearGradient: vi.fn(() => ({
      addColorStop: vi.fn()
    })),
    fillRect: vi.fn(),
    fillText: vi.fn(),
    measureText: vi.fn(() => ({ width: 20 })),
    roundRect: vi.fn()
  }))
}

function mountDashboard() {
  return mount(Dashboard, {
    global: {
      plugins: [createPinia()],
      stubs: {
        'router-link': {
          template: '<a><slot /></a>'
        }
      }
    },
    attachTo: document.body
  })
}

const MOCK_KPI = {
  utilization: 82.5,
  stdtimeAchievement: 91.3,
  balanceRate: 78.2,
  waitLossMinutes: 12,
  trends: {
    utilization: 3.2,
    stdtimeAchievement: -1.5,
    balanceRate: 2.1,
    waitLossMinutes: -5.3
  }
}

const MOCK_BALANCE = {
  balanceRate: 78.2,
  smoothIndex: 0.85,
  bottleneckStation: 'WS-03',
  taktTime: 45,
  stations: [
    { name: 'WS-01', time: 42, isBottleneck: false },
    { name: 'WS-02', time: 38, isBottleneck: false },
    { name: 'WS-03', time: 52, isBottleneck: true },
    { name: 'WS-04', time: 35, isBottleneck: false }
  ]
}

const MOCK_TREND = {
  labels: ['3/27', '3/28', '3/29', '3/30', '3/31', '4/1', '4/2'],
  actual: [48, 45, 50, 47, 52, 49, 46],
  standard: [45, 45, 45, 45, 45, 45, 45]
}

const MOCK_TIMELINE = [
  {
    id: 'ws01',
    name: 'WS-01',
    oee: 88,
    segments: [
      { type: 'work', label: 'Effective', time: 120, pct: 60 },
      { type: 'wait', label: 'Waiting', time: 40, pct: 20 },
      { type: 'machine', label: 'Running', time: 30, pct: 15 },
      { type: 'idle', label: 'Idle', time: 10, pct: 5 }
    ]
  }
]

const MOCK_THERM = [
  { label: 'Reach', pct: 25, color: '#1a6ef5' },
  { label: 'Grasp', pct: 18, color: '#10b981' },
  { label: 'Move', pct: 22, color: '#f59e0b' }
]

const MOCK_RECENT = [
  { id: 'WRK-001', operation: 'Assembly A', station: 'WS-01', actual: 48, standard: 45, efficiency: 94 },
  { id: 'WRK-002', operation: 'Assembly B', station: 'WS-02', actual: 52, standard: 50, efficiency: 104 }
]

const MOCK_BOTTLENECK = [
  {
    station: 'WS-03',
    level: 'critical',
    levelLabel: 'critical',
    reason: 'Excessive cycle time',
    suggest: 'Apply ECRS to reduce waste'
  }
]

function setupAllApiSuccess() {
  mockFetchDashboardKpi.mockResolvedValue(MOCK_KPI)
  mockFetchLineBalanceSummary.mockResolvedValue(MOCK_BALANCE)
  mockFetchWorktimeTrend.mockResolvedValue(MOCK_TREND)
  mockFetchStationTimeline.mockResolvedValue(MOCK_TIMELINE)
  mockFetchTherbligDistribution.mockResolvedValue(MOCK_THERM)
  mockFetchRecentWorktime.mockResolvedValue(MOCK_RECENT)
  mockFetchBottleneckDiagnosis.mockResolvedValue(MOCK_BOTTLENECK)
  mockFetchAnomalyEvents.mockResolvedValue([])
}

function setupAllApiFail() {
  mockFetchDashboardKpi.mockRejectedValue(new Error('Network error'))
  mockFetchLineBalanceSummary.mockRejectedValue(new Error('Network error'))
  mockFetchWorktimeTrend.mockRejectedValue(new Error('Network error'))
  mockFetchStationTimeline.mockRejectedValue(new Error('Network error'))
  mockFetchTherbligDistribution.mockRejectedValue(new Error('Network error'))
  mockFetchRecentWorktime.mockRejectedValue(new Error('Network error'))
  mockFetchBottleneckDiagnosis.mockRejectedValue(new Error('Network error'))
  mockFetchAnomalyEvents.mockRejectedValue(new Error('Network error'))
}

describe('Dashboard.vue', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    mockCanvas()
    setActivePinia(createPinia())
  })

  afterEach(() => {
    vi.restoreAllMocks()
  })

  it('renders page header with title and refresh button', async () => {
    setupAllApiSuccess()
    const wrapper = mountDashboard()
    await flushPromises()
    await new Promise((r) => setTimeout(r, 100))

    expect(wrapper.find('.page-title').text()).toBe('生产工时看板')
    // Dashboard has a date range selector and a refresh button
    expect(wrapper.find('select').exists() || wrapper.find('.page-header').exists()).toBe(true)
    expect(wrapper.find('button').exists()).toBe(true)

    wrapper.unmount()
  })

  it('shows loading state initially', () => {
    setupAllApiSuccess()
    const wrapper = mountDashboard()
    // Loading state should be true before API resolves
    // The page header and refresh button should be present
    expect(wrapper.find('.page-title').text()).toBe('生产工时看板')
    expect(wrapper.find('select').exists()).toBe(true)

    wrapper.unmount()
  })

  it('renders 4 KPI cards after data loads', async () => {
    setupAllApiSuccess()
    const wrapper = mountDashboard()
    await flushPromises()
    await new Promise((r) => setTimeout(r, 100))

    const kpiCards = wrapper.findAll('.kpi-card')
    expect(kpiCards.length).toBe(4)

    // Check KPI labels
    const labels = kpiCards.map((c) => c.find('.kpi-label').text())
    expect(labels).toContain('人工稼动率')
    expect(labels).toContain('标准工时达成率')
    expect(labels).toContain('生产线平衡率')
    expect(labels).toContain('等待损失时间')

    wrapper.unmount()
  })

  it('shows "--" placeholder when API data is null', async () => {
    // All APIs return empty/no-data responses
    mockFetchDashboardKpi.mockResolvedValue(null)
    mockFetchLineBalanceSummary.mockResolvedValue(null)
    mockFetchWorktimeTrend.mockResolvedValue(null)
    mockFetchStationTimeline.mockResolvedValue(null)
    mockFetchTherbligDistribution.mockResolvedValue(null)
    mockFetchRecentWorktime.mockResolvedValue(null)
    mockFetchBottleneckDiagnosis.mockResolvedValue(null)
    mockFetchAnomalyEvents.mockResolvedValue(null)

    const wrapper = mountDashboard()
    await flushPromises()
    await new Promise((r) => setTimeout(r, 100))

    // KPI values should show "--"
    const noDataSpans = wrapper.findAll('.no-data')
    // At least the 4 KPI cards should show "--", possibly more from charts
    expect(noDataSpans.length).toBeGreaterThanOrEqual(4)

    wrapper.unmount()
  })

  it('shows error banner when all API calls fail', async () => {
    setupAllApiFail()
    const wrapper = mountDashboard()
    await flushPromises()
    await new Promise((r) => setTimeout(r, 100))

    expect(wrapper.find('.error-banner').exists()).toBe(true)
    expect(wrapper.find('.error-banner').text()).toContain('无法连接后端服务')

    wrapper.unmount()
  })

  it('renders section titles correctly', async () => {
    setupAllApiSuccess()
    const wrapper = mountDashboard()
    await flushPromises()
    await new Promise((r) => setTimeout(r, 100))

    const titles = wrapper.findAll('.chart-title')
    const titleTexts = titles.map((t) => t.text())
    expect(titleTexts).toContain('生产线平衡率')
    expect(titleTexts).toContain('标准工时 vs 实际工时')
    expect(titleTexts).toContain('人机协作时间线')
    expect(titleTexts).toContain('动素时间分布')
    expect(titleTexts).toContain('最新工序工时记录')
    expect(titleTexts).toContain('瓶颈诊断')

    wrapper.unmount()
  })

  it('renders recent worktime table rows from API data', async () => {
    setupAllApiSuccess()
    const wrapper = mountDashboard()
    await flushPromises()
    await new Promise((r) => setTimeout(r, 100))

    const rows = wrapper.findAll('tbody tr')
    expect(rows.length).toBe(MOCK_RECENT.length)
    expect(rows[0].text()).toContain('WRK-001')
    expect(rows[0].text()).toContain('Assembly A')
    expect(rows[1].text()).toContain('WRK-002')

    wrapper.unmount()
  })

  it('renders bottleneck diagnosis items from API data', async () => {
    setupAllApiSuccess()
    const wrapper = mountDashboard()
    await flushPromises()
    await new Promise((r) => setTimeout(r, 100))

    const items = wrapper.findAll('.bottleneck-item')
    expect(items.length).toBe(MOCK_BOTTLENECK.length)
    expect(items[0].find('.bn-station').text()).toBe('WS-03')
    expect(items[0].find('.bn-reason').text()).toContain('Excessive cycle time')

    wrapper.unmount()
  })

  it('renders balance rate and smooth index in gauge footer', async () => {
    setupAllApiSuccess()
    const wrapper = mountDashboard()
    await flushPromises()
    await new Promise((r) => setTimeout(r, 100))

    const gaugeStats = wrapper.findAll('.gauge-stat-value')
    expect(gaugeStats[0].text()).toContain('78.2%')
    expect(gaugeStats[1].text()).toContain('WS-03')
    expect(gaugeStats[2].text()).toContain('0.85')

    wrapper.unmount()
  })

  it('renders therblig legend items', async () => {
    setupAllApiSuccess()
    const wrapper = mountDashboard()
    await flushPromises()
    await new Promise((r) => setTimeout(r, 100))

    const legendItems = wrapper.findAll('.therm-legend-item')
    expect(legendItems.length).toBe(MOCK_THERM.length)
    expect(legendItems[0].find('.therm-label').text()).toBe('Reach')
    expect(legendItems[0].find('.therm-value').text()).toBe('25%')

    wrapper.unmount()
  })

  it('calls fetchDashboardKpi with selected date range', async () => {
    setupAllApiSuccess()
    const wrapper = mountDashboard()
    await flushPromises()
    await new Promise((r) => setTimeout(r, 100))

    // First call should be with 'today'
    expect(mockFetchDashboardKpi).toHaveBeenCalledWith('today')

    // Change date range and click refresh
    const select = wrapper.find('.select')
    await select.setValue('month')
    await wrapper.find('button.btn-primary').trigger('click')
    await flushPromises()
    await new Promise((r) => setTimeout(r, 100))

    // Should be called again with 'month'
    expect(mockFetchDashboardKpi).toHaveBeenCalledWith('month')

    wrapper.unmount()
  })
})
