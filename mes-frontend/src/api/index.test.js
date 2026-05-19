/**
 * API data access layer unit tests
 *
 * Covers:
 *   - token management (setAuthToken / getAuthToken)
 *   - request() core: URL construction, header injection, error handling
 *   - convenience helpers: post / put / del
 *   - all exported API functions build correct URLs and methods
 */

import {
  describe,
  it,
  expect,
  vi,
  beforeEach,
  afterEach
} from 'vitest'
import {
  setAuthToken,
  getAuthToken,
  fetchDashboardKpi,
  fetchLineBalanceSummary,
  fetchWorktimeTrend,
  fetchStationTimeline,
  fetchTherbligDistribution,
  fetchRecentWorktime,
  fetchBottleneckDiagnosis,
  fetchWorktimeSummary,
  fetchOperations,
  fetchTherbligDetail,
  fetchLineBalanceFull,
  fetchAiContext,
  sendAiChat,
  fetchAiStatus,
  login,
  fetchCurrentUser,
  fetchOrders,
  fetchOrder,
  createOrder,
  updateOrder,
  deleteOrder,
  fetchCustomers,
  fetchCustomerStats,
  createCustomer,
  updateCustomer,
  deleteCustomer,
  fetchInventory,
  fetchInventoryStats,
  inboundStock,
  outboundStock,
  createInventoryItem,
  fetchEquipment,
  fetchEquipmentStats,
  createEquipment,
  fetchReportKpi,
  fetchMonthlyOutput,
  fetchProductMix,
  fetchTopCustomers,
  fetchBoxplotData,
  fetchHeatmapData
} from './index.js'

/** Collect all arguments passed to the most recent fetch call */
function captureFetch() {
  return fetch.mock.calls[fetch.mock.calls.length - 1]
}

describe('setAuthToken / getAuthToken', () => {
  beforeEach(() => {
    setAuthToken(null)
  })

  it('initially returns null', () => {
    expect(getAuthToken()).toBeNull()
  })

  it('stores and retrieves a token', () => {
    setAuthToken('jwt-abc-123')
    expect(getAuthToken()).toBe('jwt-abc-123')
  })

  it('can clear the token', () => {
    setAuthToken('jwt-abc-123')
    setAuthToken(null)
    expect(getAuthToken()).toBeNull()
  })
})

describe('request() core behavior', () => {
  const originalFetch = globalThis.fetch

  beforeEach(() => {
    globalThis.fetch = vi.fn(() =>
      Promise.resolve({
        ok: true,
        json: () => Promise.resolve({ data: 'ok' })
      })
    )
    setAuthToken(null)
  })

  afterEach(() => {
    globalThis.fetch = originalFetch
  })

  it('sends GET request to correct URL with BASE prefix', async () => {
    await fetchDashboardKpi('today')
    const [url, init] = captureFetch()
    expect(url).toMatch(/\/api\/dashboard\/kpi\?range=today$/)
    // GET is the default for fetch, no explicit method set
    expect(init.method).toBeUndefined()
  })

  it('includes Authorization header when token is set', async () => {
    setAuthToken('my-jwt-token')
    await fetchDashboardKpi('week')
    const [, init] = captureFetch()
    expect(init.headers['Authorization']).toBe('Bearer my-jwt-token')
  })

  it('omits Authorization header when token is null', async () => {
    await fetchDashboardKpi()
    const [, init] = captureFetch()
    expect(init.headers['Authorization']).toBeUndefined()
  })

  it('throws descriptive error on non-ok response', async () => {
    globalThis.fetch = vi.fn(() =>
      Promise.resolve({
        ok: false,
        status: 500,
        json: () => Promise.reject(new Error('not json'))
      })
    )
    await expect(fetchDashboardKpi()).rejects.toThrow(/请求失败 \(500\)/)
  })

  it('handles non-ok response when json() also fails', async () => {
    globalThis.fetch = vi.fn(() =>
      Promise.resolve({
        ok: false,
        status: 502,
        json: () => Promise.reject(new Error('not json'))
      })
    )
    await expect(fetchDashboardKpi()).rejects.toThrow(/请求失败 \(502\)/)
  })
})

describe('convenience methods (post / put / del)', () => {
  const originalFetch = globalThis.fetch

  beforeEach(() => {
    globalThis.fetch = vi.fn(() =>
      Promise.resolve({
        ok: true,
        json: () => Promise.resolve({ id: 1 })
      })
    )
    setAuthToken(null)
  })

  afterEach(() => {
    globalThis.fetch = originalFetch
  })

  it('login() sends POST with credentials', async () => {
    await login('admin', 'pass123')
    const [url, init] = captureFetch()
    expect(url).toMatch(/\/api\/auth\/login$/)
    expect(init.method).toBe('POST')
    const body = JSON.parse(init.body)
    expect(body).toEqual({ username: 'admin', password: 'pass123' })
  })

  it('createOrder() sends POST with order data', async () => {
    const orderData = { product: 'Widget A', qty: 100 }
    await createOrder(orderData)
    const [url, init] = captureFetch()
    expect(url).toMatch(/\/api\/orders$/)
    expect(init.method).toBe('POST')
    expect(JSON.parse(init.body)).toEqual(orderData)
  })

  it('updateOrder() sends PUT with order data', async () => {
    await updateOrder('ORD-001', { status: 'completed' })
    const [url, init] = captureFetch()
    expect(url).toMatch(/\/api\/orders\/ORD-001$/)
    expect(init.method).toBe('PUT')
    expect(JSON.parse(init.body)).toEqual({ status: 'completed' })
  })

  it('deleteOrder() sends DELETE', async () => {
    await deleteOrder('ORD-001')
    const [url, init] = captureFetch()
    expect(url).toMatch(/\/api\/orders\/ORD-001$/)
    expect(init.method).toBe('DELETE')
  })

  it('createCustomer() sends POST', async () => {
    await createCustomer({ name: 'Test Co' })
    const [, init] = captureFetch()
    expect(init.method).toBe('POST')
  })

  it('updateCustomer() sends PUT', async () => {
    await updateCustomer('C1', { name: 'Updated' })
    const [url, init] = captureFetch()
    expect(url).toMatch(/\/api\/customers\/C1$/)
    expect(init.method).toBe('PUT')
  })

  it('deleteCustomer() sends DELETE', async () => {
    await deleteCustomer('C1')
    const [url, init] = captureFetch()
    expect(url).toMatch(/\/api\/customers\/C1$/)
    expect(init.method).toBe('DELETE')
  })

  it('inboundStock() sends POST to /inbound', async () => {
    await inboundStock({ code: 'M1', qty: 50 })
    const [url, init] = captureFetch()
    expect(url).toMatch(/\/api\/inventory\/inbound$/)
    expect(init.method).toBe('POST')
  })

  it('outboundStock() sends POST to /outbound', async () => {
    await outboundStock({ code: 'M1', qty: 10 })
    const [url, init] = captureFetch()
    expect(url).toMatch(/\/api\/inventory\/outbound$/)
    expect(init.method).toBe('POST')
  })

  it('createInventoryItem() sends POST', async () => {
    await createInventoryItem({ code: 'N1', name: 'New Part' })
    const [url, init] = captureFetch()
    expect(url).toMatch(/\/api\/inventory$/)
    expect(init.method).toBe('POST')
  })

  it('createEquipment() sends POST', async () => {
    await createEquipment({ name: 'CNC-5' })
    const [url, init] = captureFetch()
    expect(url).toMatch(/\/api\/equipment$/)
    expect(init.method).toBe('POST')
  })
})

describe('GET API functions - correct URL construction', () => {
  const originalFetch = globalThis.fetch

  beforeEach(() => {
    globalThis.fetch = vi.fn(() =>
      Promise.resolve({
        ok: true,
        json: () => Promise.resolve({})
      })
    )
    setAuthToken(null)
  })

  afterEach(() => {
    globalThis.fetch = originalFetch
  })

  it('fetchDashboardKpi() builds correct URL with range param', async () => {
    await fetchDashboardKpi('month')
    const [url] = captureFetch()
    expect(url).toMatch(/\/api\/dashboard\/kpi\?range=month$/)
  })

  it('fetchLineBalanceSummary() uses correct endpoint', async () => {
    await fetchLineBalanceSummary()
    const [url] = captureFetch()
    expect(url).toMatch(/\/api\/line-balance\/summary$/)
  })

  it('fetchWorktimeTrend() passes days parameter', async () => {
    await fetchWorktimeTrend(14)
    const [url] = captureFetch()
    expect(url).toMatch(/\/api\/v1\/worktime\/trend\?days=14$/)
  })

  it('fetchStationTimeline() uses correct endpoint', async () => {
    await fetchStationTimeline()
    const [url] = captureFetch()
    expect(url).toMatch(/\/api\/stations\/timeline$/)
  })

  it('fetchTherbligDistribution() uses correct endpoint', async () => {
    await fetchTherbligDistribution()
    const [url] = captureFetch()
    expect(url).toMatch(/\/api\/v1\/worktime\/therblig-distribution$/)
  })

  it('fetchRecentWorktime() passes limit parameter', async () => {
    await fetchRecentWorktime(20)
    const [url] = captureFetch()
    expect(url).toMatch(/\/api\/v1\/worktime\/recent\?limit=20$/)
  })

  it('fetchBottleneckDiagnosis() uses correct endpoint', async () => {
    await fetchBottleneckDiagnosis()
    const [url] = captureFetch()
    expect(url).toMatch(/\/api\/line-balance\/bottleneck-diagnosis$/)
  })

  it('fetchWorktimeSummary() passes station and shift params', async () => {
    await fetchWorktimeSummary('ws01', 'afternoon')
    const [url] = captureFetch()
    expect(url).toMatch(
      /\/api\/v1\/worktime\/summary\?station=ws01&shift=afternoon$/
    )
  })

  it('fetchOperations() passes station and shift params', async () => {
    await fetchOperations('ws02', 'night')
    const [url] = captureFetch()
    expect(url).toMatch(
      /\/api\/v1\/worktime\/operations\?station=ws02&shift=night$/
    )
  })

  it('fetchTherbligDetail() includes operationId in path', async () => {
    await fetchTherbligDetail('OP-0042')
    const [url] = captureFetch()
    expect(url).toMatch(/\/api\/v1\/worktime\/therblig\/OP-0042$/)
  })

  it('fetchLineBalanceFull() passes lineId param', async () => {
    await fetchLineBalanceFull('line2')
    const [url] = captureFetch()
    expect(url).toMatch(/\/api\/line-balance\/full\?line=line2$/)
  })

  it('fetchAiContext() uses correct endpoint', async () => {
    await fetchAiContext()
    const [url] = captureFetch()
    expect(url).toMatch(/\/api\/dashboard\/ai-context$/)
  })

  it('fetchCurrentUser() uses /api/auth/me', async () => {
    await fetchCurrentUser()
    const [url] = captureFetch()
    expect(url).toMatch(/\/api\/auth\/me$/)
  })

  it('fetchOrders() serializes query params', async () => {
    await fetchOrders({ status: 'active', page: 2, pageSize: 20 })
    const [url] = captureFetch()
    expect(url).toContain('/api/orders?')
    expect(url).toContain('status=active')
    expect(url).toContain('page=2')
    expect(url).toContain('pageSize=20')
  })

  it('fetchOrder() includes id in path', async () => {
    await fetchOrder('PO-99')
    const [url] = captureFetch()
    expect(url).toMatch(/\/api\/orders\/PO-99$/)
  })

  it('fetchCustomers() serializes params', async () => {
    await fetchCustomers({ type: 'A', keyword: 'test' })
    const [url] = captureFetch()
    expect(url).toContain('/api/customers?')
    expect(url).toContain('type=A')
    expect(url).toContain('keyword=test')
  })

  it('fetchCustomerStats() uses correct endpoint', async () => {
    await fetchCustomerStats()
    const [url] = captureFetch()
    expect(url).toMatch(/\/api\/customers\/stats$/)
  })

  it('fetchInventory() serializes params including boolean', async () => {
    await fetchInventory({ category: 'raw', lowStockOnly: true })
    const [url] = captureFetch()
    expect(url).toContain('category=raw')
    expect(url).toContain('lowStockOnly=true')
  })

  it('fetchInventoryStats() uses correct endpoint', async () => {
    await fetchInventoryStats()
    const [url] = captureFetch()
    expect(url).toMatch(/\/api\/inventory\/stats$/)
  })

  it('fetchEquipment() uses correct endpoint', async () => {
    await fetchEquipment()
    const [url] = captureFetch()
    expect(url).toMatch(/\/api\/equipment$/)
  })

  it('fetchEquipmentStats() uses correct endpoint', async () => {
    await fetchEquipmentStats()
    const [url] = captureFetch()
    expect(url).toMatch(/\/api\/equipment\/stats$/)
  })

  it('fetchReportKpi() passes period param', async () => {
    await fetchReportKpi('quarter')
    const [url] = captureFetch()
    expect(url).toMatch(/\/api\/reports\/kpi\?period=quarter$/)
  })

  it('fetchMonthlyOutput() passes months param', async () => {
    await fetchMonthlyOutput(12)
    const [url] = captureFetch()
    expect(url).toMatch(/\/api\/reports\/monthly-output\?months=12$/)
  })

  it('fetchProductMix() uses correct endpoint', async () => {
    await fetchProductMix()
    const [url] = captureFetch()
    expect(url).toMatch(/\/api\/reports\/product-mix$/)
  })

  it('fetchTopCustomers() passes period param', async () => {
    await fetchTopCustomers('week')
    const [url] = captureFetch()
    expect(url).toMatch(/\/api\/reports\/top-customers\?period=week$/)
  })

  it('fetchBoxplotData() uses correct endpoint', async () => {
    await fetchBoxplotData()
    const [url] = captureFetch()
    expect(url).toMatch(/\/api\/v1\/worktime\/boxplot\?station=all$/)
  })

  it('fetchBoxplotData() passes station param', async () => {
    await fetchBoxplotData('WS-01')
    const [url] = captureFetch()
    expect(url).toMatch(/\/api\/v1\/worktime\/boxplot\?station=WS-01$/)
  })

  it('fetchHeatmapData() uses correct endpoint', async () => {
    await fetchHeatmapData()
    const [url] = captureFetch()
    expect(url).toMatch(/\/api\/v1\/worktime\/heatmap\?station=all$/)
  })

  it('fetchHeatmapData() passes station param', async () => {
    await fetchHeatmapData('WS-02')
    const [url] = captureFetch()
    expect(url).toMatch(/\/api\/v1\/worktime\/heatmap\?station=WS-02$/)
  })
})

describe('sendAiChat() - sends chat through backend proxy', () => {
  const originalFetch = globalThis.fetch

  beforeEach(() => {
    globalThis.fetch = vi.fn(() =>
      Promise.resolve({
        ok: true,
        json: () => Promise.resolve({ content: 'Hello!', model: 'deepseek-chat' })
      })
    )
    setAuthToken(null)
  })

  afterEach(() => {
    globalThis.fetch = originalFetch
  })

  it('calls backend /api/v1/ai/chat with messages and options', async () => {
    const messages = [{ role: 'user', content: 'hello' }]
    const result = await sendAiChat(messages, { temperature: 0.5 })
    const [url, init] = captureFetch()
    expect(url).toMatch(/\/api\/v1\/ai\/chat$/)
    expect(init.method).toBe('POST')
    expect(init.headers['Authorization']).toBeUndefined()
    const body = JSON.parse(init.body)
    expect(body.messages).toEqual(messages)
    expect(body.temperature).toBe(0.5)
    expect(body.max_tokens).toBe(2048)
  })

  it('injects auth token when set', async () => {
    setAuthToken('jwt-internal')
    await sendAiChat([{ role: 'user', content: 'test' }])
    const [, init] = captureFetch()
    expect(init.headers['Authorization']).toBe('Bearer jwt-internal')
  })

  it('uses default options when none provided', async () => {
    await sendAiChat([])
    const [, init] = captureFetch()
    const body = JSON.parse(init.body)
    expect(body.temperature).toBe(0.7)
    expect(body.max_tokens).toBe(2048)
  })
})

describe('fetchAiStatus()', () => {
  const originalFetch = globalThis.fetch

  beforeEach(() => {
    globalThis.fetch = vi.fn(() =>
      Promise.resolve({
        ok: true,
        json: () => Promise.resolve({ configured: true, model: 'deepseek-chat' })
      })
    )
  })

  afterEach(() => {
    globalThis.fetch = originalFetch
  })

  it('uses correct endpoint', async () => {
    await fetchAiStatus()
    const [url] = captureFetch()
    expect(url).toMatch(/\/api\/v1\/ai\/status$/)
  })
})
