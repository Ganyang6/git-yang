/**
 * MES 前端统一数据访问层
 *
 * 规范：
 *   - 所有业务数据必须通过此文件中的函数获取
 *   - 禁止在组件中硬编码任何数值、百分比或状态
 *   - 接口地址统一从 VITE_API_BASE 环境变量读取
 *   - 未配置时默认连接本机后端 http://localhost:8000
 */

const BASE = import.meta.env.VITE_API_BASE || ''

let _token = null

/**
 * 设置认证 token（登录成功后调用）
 * @param {string | null} token
 */
export function setAuthToken(token) {
  _token = token
}

/**
 * 获取当前 token
 * @returns {string | null}
 */
export function getAuthToken() {
  return _token
}

async function request(path, options = {}) {
  const url = `${BASE}${path}`
  const headers = { 'Content-Type': 'application/json', ...options.headers }
  if (_token) {
    headers['Authorization'] = `Bearer ${_token}`
  }
  const controller = new AbortController()
  const timeout = setTimeout(() => controller.abort(), options.timeout || 15000)
  const fetchOptions = { headers, signal: controller.signal, ...options }
  delete fetchOptions.timeout
  let res
  try {
    res = await fetch(url, fetchOptions)
  } finally {
    clearTimeout(timeout)
  }
  if (!res.ok) {
    // P1 #58: 401 时清除 token 并跳转登录页
    if (res.status === 401) {
      localStorage.removeItem('mes_auth_token')
      _token = null
      window.location.hash = '#/login'
      throw new Error('认证已过期，请重新登录')
    }
    // P1 #59: 错误信息使用通用描述，不暴露后端原始响应
    let userMsg = `请求失败 (${res.status})`
    try {
      const body = await res.json()
      if (body && body.message) {
        userMsg = body.message
      }
    } catch {
      // response 不是 JSON，使用默认消息
    }
    if (res.status === 422) {
      const bodyText = await res.clone().text()
      console.error('422 response body:', bodyText)
    }
    throw new Error(userMsg)
  }
  const json = await res.json()
  // Unwrap the {code, message, data} envelope — callers expect the inner `data` payload
  if (json && typeof json === 'object' && 'code' in json && 'data' in json) {
    return json.data
  }
  return json
}

/**
 * POST/PUT 便捷方法
 */
function post(path, body) {
  return request(path, {
    method: 'POST',
    body: JSON.stringify(body)
  })
}

function put(path, body) {
  return request(path, {
    method: 'PUT',
    body: JSON.stringify(body)
  })
}

function del(path) {
  return request(path, { method: 'DELETE' })
}

/**
 * 一键清理所有工时分析数据
 * @returns {{ deletedTherbligDetails: number, deletedWorktimeRecords: number }}
 */
export function cleanupWorktimeData() {
  return del('/api/v1/worktime/cleanup')
}

/**
 * 校准标准工时
 * @param {string} operationId
 * @param {number} newStandardTime  新的标准工时（秒）
 * @returns {{ id, standard }}
 */
export function calibrateWorktime(operationId, newStandardTime) {
  return put(`/api/v1/worktime/operations/${operationId}`, {
    standard_ms: newStandardTime
  })
}

// ─── 看板 / KPI ──────────────────────────────────────────────────────────────

/**
 * 获取看板核心 KPI
 * @param {string} range  today | week | month
 * @returns {{ utilization, stdtimeAchievement, balanceRate, waitLossMinutes,
 *             trends: { utilization, stdtimeAchievement, balanceRate, waitLossMinutes } }}
 */
export function fetchDashboardKpi(range = 'today') {
  return request(`/api/dashboard/kpi?range=${range}`)
}

/**
 * 获取生产线平衡率概览
 * @returns {{ balanceRate, smoothIndex, bottleneckStation,
 *             stations: [{ name, time, isBottleneck }], taktTime }}
 */
export function fetchLineBalanceSummary() {
  return request('/api/line-balance/summary')
}

/**
 * 获取近 N 天工时趋势（实际 vs 标准，单位：秒/件）
 * @param {number} days
 * @returns {{ labels: string[], actual: number[], standard: number[] }}
 */
export function fetchWorktimeTrend(days = 7) {
  return request(`/api/v1/worktime/trend?days=${days}`)
}

/**
 * 获取人机协作时间线（当前班次）
 * @returns {Array<{ id, name, oee, segments: [{ type, label, time, pct }] }>}
 */
export function fetchStationTimeline() {
  return request('/api/stations/timeline')
}

/**
 * 获取 Therblig 动素时间分布（汇总）
 * @returns {Array<{ label, pct, color }>}
 */
export function fetchTherbligDistribution() {
  return request('/api/v1/worktime/therblig-distribution')
}

/**
 * 获取箱线图统计数据（按工位+班次的五数概括）
 * @param {string} station  all | 具体工位ID
 * @returns {{ stations: string[], shifts: string[], morning: number[][], afternoon: number[][], night: number[][] }}
 */
export function fetchBoxplotData(station = 'all') {
  return request(`/api/v1/worktime/boxplot?station=${station}`)
}

/**
 * 获取热力图统计数据（按工位+小时的浪费占比）
 * @param {string} station  all | 具体工位ID
 * @returns {{ stations: string[], hours: string[], data: number[][] }}
 */
export function fetchHeatmapData(station = 'all') {
  return request(`/api/v1/worktime/heatmap?station=${station}`)
}

/**
 * 获取最新工序工时记录
 * @param {number} limit
 * @returns {Array<{ id, operation, station, actual, standard, efficiency }>}
 */
export function fetchRecentWorktime(limit = 10) {
  return request(`/api/v1/worktime/recent?limit=${limit}`)
}

/**
 * 获取瓶颈诊断结果
 * @returns {Array<{ station, level, levelLabel, reason, suggest }>}
 */
export function fetchBottleneckDiagnosis() {
  return request('/api/line-balance/bottleneck-diagnosis')
}

// ─── 工时分析页 ───────────────────────────────────────────────────────────────

/**
 * 获取工时分析汇总统计
 * @param {string} station  all | ws01 | ws02 ...
 * @param {string} shift    morning | afternoon | night
 * @returns {{ totalOps, avgEfficiency, wasteRatio, totalStdTimeHours }}
 */
export function fetchWorktimeSummary(station = 'all', shift = 'morning') {
  return request(`/api/v1/worktime/summary?station=${station}&shift=${shift}`)
}

/**
 * 获取工序列表（含 MOD、标准/实际工时、效率、非增值占比）
 * @param {string} station
 * @param {string} shift
 * @returns {Array<{ id, operation, station, modTotal, standard, actual, efficiency, wastePct }>}
 */
export function fetchOperations(station = 'all', shift = 'morning') {
  return request(`/api/v1/worktime/operations?station=${station}&shift=${shift}`)
}

/**
 * 获取指定工序的 Therblig 动素明细
 * @param {string} operationId
 * @returns {{ allowanceRate, rows: [{ id, symbol, name, color, mod, actual, pct, isWaste }] }}
 */
export function fetchTherbligDetail(operationId) {
  return request(`/api/v1/worktime/therblig/${operationId}`)
}

// ─── 生产线平衡页 ─────────────────────────────────────────────────────────────

/**
 * 获取生产线平衡完整数据
 * @param {string} lineId  line1 | line2
 * @returns {{ balanceRate, smoothIndex, taktTime, dailyDemand, bottleneck,
 *             lostCapacity, lostValue,
 *             stations: [{ id, name, time, isBottleneck }],
 *             causalRules: [...], ecrsItems: [...] }}
 */
export function fetchLineBalanceFull(lineId = 'line1', shift) {
  let url = `/api/line-balance/full?line=${lineId}`
  if (shift) url += `&shift=${shift}`
  return request(url)
}

// ─── AI 对话页 ────────────────────────────────────────────────────────────────

/**
 * 获取注入给 AI 的实时产线上下文快照
 * @returns {{ balanceRate, bottleneckStation, taktTime, lostCapacity,
 *             utilization, stdtimeAchievement, wasteRatio }}
 */
export function fetchAiContext() {
  return request('/api/dashboard/ai-context')
}

/**
 * 发送消息给 AI（通过后端代理，API Key 不暴露到浏览器）
 * @param {Array<{role,content}>} messages
 * @param {{ temperature?: number, max_tokens?: number }} options
 * @returns {{ content: string, model: string, usage?: object }}
 */
export function sendAiChat(messages, options = {}) {
  return post('/api/v1/ai/chat', {
    messages,
    temperature: options.temperature ?? 0.7,
    max_tokens: options.max_tokens ?? 2048
  })
}

/**
 * 检查 AI 服务是否可用
 * @returns {{ configured: boolean, model: string, api_url: string }}
 */
export function fetchAiStatus() {
  return request('/api/v1/ai/status')
}

// ─── AI 异步任务 ─────────────────────────────────────────────────────

/**
 * 提交异步 AI 分析任务
 * @param {string} analysisType  worktime | line_balance | anomaly | report
 * @param {object} params        分析参数（station_id, period 等）
 * @returns {{ task_id: string }}
 */
export function submitAiTask(analysisType, params = {}) {
  return post('/api/ai/chat/submit', { analysis_type: analysisType, ...params })
}

/**
 * 查询异步任务状态和结果
 * @param {string} taskId
 * @returns {{ task_id: string, status: string, progress: number, result: object|null }}
 */
export function fetchTaskStatus(taskId) {
  return request(`/api/ai/task/${taskId}/status`)
}

/**
 * 获取用户的所有 AI 分析任务列表
 * @param {{ status?: string, page?: number, pageSize?: number }} params
 * @returns {{ items: Array, total: number }}
 */
export function fetchTasks(params = {}) {
  const filtered = Object.fromEntries(
    Object.entries(params).filter(([, v]) => v !== undefined && v !== null && v !== '')
  )
  const qs = new URLSearchParams(filtered).toString()
  return request(`/api/ai/tasks?${qs}`)
}

/**
 * Fetch AI health status
 * @returns {{ deepseek_ok: boolean, cache_hit_rate: number, task_success_rate: number, avg_response_ms: number }}
 */
export function fetchAiHealth() {
  return request('/api/ai/health')
}

// ─── 异常检测 ──────────────────────────────────────────────────────────────

/**
 * 查询历史异常事件
 * @param {{ station_id?: string, limit?: number }} params
 * @returns {{ events: Array, total: number, returned: number }}
 */
export function fetchAnomalyEvents(params = {}) {
  const filtered = Object.fromEntries(
    Object.entries(params).filter(([, v]) => v !== undefined && v !== null && v !== '')
  )
  const qs = new URLSearchParams(filtered).toString()
  return request(`/api/anomaly/events?${qs}`)
}

/**
 * 获取异常检测统计
 * @returns {{ total_anomalies: number, by_station: object, by_action: object }}
 */
export function fetchAnomalyStats() {
  return request('/api/anomaly/stats')
}

// ─── PDF 导出 ────────────────────────────────────────────────────────────────

/**
 * 通用 blob 下载请求 (PDF 等二进制文件)
 * @param {string} path API 路径
 * @param {string} filename 下载文件名
 * @param {object} params 查询参数
 */
export function downloadBlob(path, filename, params = {}) {
  const url = `${BASE}${path}`
  const headers = {}
  if (_token) {
    headers['Authorization'] = `Bearer ${_token}`
  }
  const filtered = Object.fromEntries(
    Object.entries(params).filter(([, v]) => v !== undefined && v !== null && v !== '')
  )
  const qs = new URLSearchParams(filtered).toString()
  const fullUrl = qs ? `${url}?${qs}` : url

  return fetch(fullUrl, { headers })
    .then(res => {
      if (!res.ok) throw new Error(`HTTP ${res.status}`)
      return res.blob()
    })
    .then(blob => {
      const link = document.createElement('a')
      link.href = URL.createObjectURL(blob)
      link.download = filename
      document.body.appendChild(link)
      link.click()
      document.body.removeChild(link)
      URL.revokeObjectURL(link.href)
    })
    .catch(err => {
      console.error('Download failed:', err)
      window.dispatchEvent(
        new CustomEvent('mes:toast', {
          detail: { level: 'error', title: '下载失败', message: err.message || '文件下载出现异常' }
        })
      )
      throw err
    })
}

// ─── 认证 ──────────────────────────────────────────────────────────────────

/**
 * 登录
 * @param {string} username
 * @param {string} password
 * @returns {{ token, user: { id, name, role } }}
 */
export function login(username, password) {
  return post('/api/auth/login', { username, password })
}

/**
 * 获取当前用户信息
 * @returns {{ id, name, role }}
 */
export function fetchCurrentUser() {
  return request('/api/auth/me')
}

// ─── 生产订单 ──────────────────────────────────────────────────────────────

/**
 * 获取订单列表
 * @param {{ status?: string, priority?: string, keyword?: string, dateFrom?: string, dateTo?: string, page?: number, pageSize?: number }} params
 * @returns {{ items: Array, total: number, page: number, pageSize: number }}
 */
export function fetchOrders(params = {}) {
  const filtered = Object.fromEntries(
    Object.entries(params).filter(([, v]) => v !== undefined && v !== null && v !== '')
  )
  const qs = new URLSearchParams(filtered).toString()
  return request(`/api/orders?${qs}`)
}

/**
 * 获取单个订单详情
 * @param {string} id
 */
export function fetchOrder(id) {
  return request(`/api/orders/${id}`)
}

/**
 * 创建订单
 * @param {{ product, code, spec, customer, qty, dueDate, priority, status, remark }} data
 */
export function createOrder(data) {
  return post('/api/orders', data)
}

/**
 * 更新订单
 * @param {string} id
 * @param {object} data
 */
export function updateOrder(id, data) {
  return put(`/api/orders/${id}`, data)
}

/**
 * 删除订单
 * @param {string} id
 */
export function deleteOrder(id) {
  return del(`/api/orders/${id}`)
}

// ─── 客户管理 ──────────────────────────────────────────────────────────────

/**
 * 获取客户列表
 * @param {{ type?: string, level?: string, keyword?: string }} params
 * @returns {Array<{ id, name, contact, phone, city, type, level, orders, amount, lastOrder, status }>}
 */
export function fetchCustomers(params = {}) {
  const filtered = Object.fromEntries(
    Object.entries(params).filter(([, v]) => v !== undefined && v !== null && v !== '')
  )
  const qs = new URLSearchParams(filtered).toString()
  return request(`/api/customers?${qs}`).then(data => data?.items || data || [])
}

/**
 * 获取客户统计
 * @returns {{ total, active, saCount, totalAmount }}
 */
export function fetchCustomerStats() {
  return request('/api/customers/stats')
}

/**
 * 创建客户
 * @param {{ name, contact, phone, city, type, level, remark }} data
 */
export function createCustomer(data) {
  return post('/api/customers', data)
}

/**
 * 更新客户
 * @param {string} id
 * @param {object} data
 */
export function updateCustomer(id, data) {
  return put(`/api/customers/${id}`, data)
}

/**
 * 删除客户
 * @param {string} id
 */
export function deleteCustomer(id) {
  return del(`/api/customers/${id}`)
}

// ─── 库存管理 ──────────────────────────────────────────────────────────────

/**
 * 获取物料列表
 * @param {{ category?: string, warehouse?: string, keyword?: string, lowStockOnly?: boolean }} params
 * @returns {Array<{ code, name, spec, category, unit, stock, safeStock, location, price, lastIn }>}
 */
export function fetchInventory(params = {}) {
  const filtered = Object.fromEntries(
    Object.entries(params).filter(([, v]) => v !== undefined && v !== null && v !== '')
  )
  const qs = new URLSearchParams(filtered).toString()
  return request(`/api/inventory?${qs}`)
}

/**
 * 获取库存统计
 * @returns {{ totalItems, lowStockCount, totalValue, warehouseCount }}
 */
export function fetchInventoryStats() {
  return request('/api/inventory/stats')
}

/**
 * 入库操作
 * @param {{ code, qty, remark }} data
 */
export function inboundStock(data) {
  return post('/api/inventory/inbound', data)
}

/**
 * 出库操作
 * @param {{ code, qty, remark }} data
 */
export function outboundStock(data) {
  return post('/api/inventory/outbound', data)
}

/**
 * 新增物料
 * @param {{ code, name, spec, category, unit, safeStock, location, price }} data
 */
export function createInventoryItem(data) {
  return post('/api/inventory', data)
}

/**
 * 删除物料
 * @param {string} code
 */
export function deleteInventoryItem(code) {
  return del(`/api/inventory/${code}`)
}

// ─── 工位管理 ──────────────────────────────────────────────────────────────

/**
 * 获取工位列表
 * @returns {Promise<Array<{ id, name, worker, line, shift }>>}
 */
export function fetchStations() {
  return request('/api/stations').then(data => data?.items || data || [])
}

/**
 * 新增工位
 * @param {{ name, worker, line, shift }} data
 */
export function createStation(data) {
  return post('/api/stations', data)
}

/**
 * 更新工位（编号不可改）
 * @param {number} id
 * @param {{ worker, line, shift }} data
 */
export function updateStation(id, data) {
  return put(`/api/stations/${id}`, data)
}

/**
 * 删除工位
 * @param {number} id
 */
export function deleteStation(id) {
  return del(`/api/stations/${id}`)
}

// ─── 设备管理 ──────────────────────────────────────────────────────────────

/**
 * 获取设备列表
 * @returns {Array<{ id, name, model, workshop, status, oee, utilization, faultCount, mtbf, todayUtil, nextMaint }>}
 */
export function fetchEquipment() {
  return request('/api/equipment').then(data => data?.items || data || [])
}

/**
 * 获取设备状态概览
 * @returns {{ running: number, idle: number, maintenance: number, avgOee: number }}
 */
export function fetchEquipmentStats() {
  return request('/api/equipment/stats')
}

/**
 * 新增设备
 * @param {{ name, model, workshop }} data
 */
export function createEquipment(data) {
  return post('/api/equipment', data)
}

/**
 * Delete equipment by ID
 * @param {number} id
 */
export function deleteEquipment(id) {
  return del(`/api/equipment/${id}`)
}

/**
 * Update equipment by ID
 * @param {number} id
 * @param {object} data
 */
export function updateEquipment(id, data) {
  return put(`/api/equipment/${id}`, data)
}

// ─── 视频分析 ──────────────────────────────────────────────────────────────

/**
 * Allowed video MIME types (validated client-side as first filter)
 */
const VIDEO_MIME_TYPES = new Set([
  'video/mp4',
  'video/avi',
  'video/quicktime',
  'video/x-msvideo',
  'video/x-matroska',
  'video/x-mkv'
])

/**
 * Allowed video file extensions
 */
const VIDEO_EXTENSIONS = new Set(['mp4', 'avi', 'mov', 'mkv'])

/**
 * Validate video file type by MIME and extension
 * @param {File} file
 * @returns {{ valid: boolean, reason?: string }}
 */
export function validateVideoFile(file) {
  if (!file) {
    return { valid: false, reason: 'No file selected' }
  }
  const ext = file.name.split('.').pop().toLowerCase()
  if (!VIDEO_EXTENSIONS.has(ext)) {
    return { valid: false, reason: `Unsupported format: .${ext}. Allowed: mp4, avi, mov, mkv` }
  }
  if (file.type && !VIDEO_MIME_TYPES.has(file.type)) {
    return { valid: false, reason: `Unsupported MIME type: ${file.type}` }
  }
  return { valid: true }
}

/**
 * Upload video file for analysis
 * @param {File} file        Video file to upload
 * @param {string} stationId  Target station ID (e.g. 'WS-01')
 * @returns {{ task_id: string, filename: string, size: number, status: string }}
 */
export function uploadVideo(file, stationId = '', shift = 'morning', line = '') {
  const url = `${BASE}/api/v1/video/upload`
  const formData = new FormData()
  formData.append('file', file)
  formData.append('station_id', stationId)
  formData.append('shift', shift)
  formData.append('line', line)

  const headers = {}
  if (_token) {
    headers['Authorization'] = `Bearer ${_token}`
  }
  // Do NOT set Content-Type — let browser auto-set multipart boundary

  return fetch(url, { method: 'POST', headers, body: formData })
    .then((res) => {
      if (!res.ok) {
        let userMsg = `Upload failed (${res.status})`
        return res.json().catch(() => {}).then((body) => {
          if (body && body.message) userMsg = body.message
          throw new Error(userMsg)
        })
      }
      return res.json()
    })
    .then((json) => {
      if (json && typeof json === 'object' && 'code' in json && 'data' in json) {
        return json.data
      }
      return json
    })
}

/**
 * Fetch all video analysis tasks
 * @returns {{ items: Array, total: number }}
 */
export function fetchVideoTasks() {
  return request('/api/v1/video/tasks')
}

/**
 * Fetch single video task detail
 * @param {string} taskId
 * @returns {{ task_id: string, status: string, progress: number, ... }}
 */
export function fetchVideoTask(taskId) {
  return request(`/api/v1/video/tasks/${taskId}`)
}

/**
 * Cancel a processing video task
 * @param {string} taskId
 * @returns {{ status: string }}
 */
export function cancelVideoTask(taskId) {
  return request(`/api/v1/video/tasks/${taskId}/cancel`, { method: 'POST' })
}

/**
 * Subscribe to video processing progress via SSE
 *
 * Uses fetch + ReadableStream (not EventSource) to pass JWT via Authorization
 * header instead of URL query parameter (P0-4 security fix).
 *
 * @param {string} taskId
 * @param {function} onProgress  Callback: (data: { progress, status, ... }) => void
 * @param {{ autoConnect?: boolean }} options
 * @returns {{ close: function }}
 */
export function streamVideoProgress(taskId, onProgress, options = {}) {
  const { autoConnect = true } = options

  let abortController = null
  let reader = null

  async function connect() {
    if (reader) return

    const t = _token || localStorage.getItem('mes_auth_token')
    const baseUrl = import.meta.env.VITE_API_BASE || ''
    const url = `${baseUrl}/api/v1/video/tasks/${taskId}/stream`

    abortController = new AbortController()
    const headers = {}
    if (t) headers['Authorization'] = `Bearer ${t}`

    try {
      const response = await fetch(url, {
        headers,
        signal: abortController.signal,
      })

      if (!response.ok) {
        if (response.status === 401) {
          localStorage.removeItem('mes_auth_token')
          _token = null
          window.location.hash = '#/login'
        }
        return
      }

      reader = response.body.getReader()
      const decoder = new TextDecoder()
      let buffer = ''

      while (true) {
        const { done, value } = await reader.read()
        if (done) break

        buffer += decoder.decode(value, { stream: true })

        const lines = buffer.split('\n')
        buffer = lines.pop() || ''

        for (const line of lines) {
          if (!line.startsWith('data: ')) continue

          const dataStr = line.slice(6).trim()
          if (!dataStr) continue

          try {
            const data = JSON.parse(dataStr)
            if (onProgress) onProgress(data)
          } catch {
            // Skip malformed JSON lines
          }
        }
      }
    } catch (err) {
      if (err.name !== 'AbortError') {
        console.warn('[streamVideoProgress] error:', err.message)
      }
    }
  }

  function close() {
    if (abortController) {
      abortController.abort()
      abortController = null
    }
    reader = null
  }

  if (autoConnect) {
    Promise.resolve().then(() => connect())
  }

  return { close, connect }
}

/**
 * 获取元数据（工位、班次、产线、阈值等）
 * 解决前端硬编码问题，新增工位后下拉自动更新
 * @returns {Promise<{ stations: Array, shifts: Array, lines: Array, mod_unit: number, thresholds: object }>}
 */
export function fetchMeta() {
  return request('/api/meta')
}

// ─── 报表分析 ──────────────────────────────────────────────────────────────

/**
 * 获取报表 KPI 指标
 * @param {string} period  week | month | quarter
 * @returns {{ totalOutput, completionRate, yieldRate, onTimeRate, oee,
 *             changes: { totalOutput, completionRate, yieldRate, onTimeRate, oee } }}
 */
export function fetchReportKpi(period = 'month') {
  return request(`/api/reports/kpi?period=${period}`)
}

/**
 * 获取月度产量趋势
 * @param {number} months
 * @returns {{ labels: string[], values: number[] }}
 */
export function fetchMonthlyOutput(months = 6) {
  return request(`/api/reports/monthly-output?months=${months}`)
}

/**
 * 获取产品类别占比
 * @returns {Array<{ label, value, color }>}
 */
export function fetchProductMix() {
  return request('/api/reports/product-mix')
}

/**
 * 获取客户订单贡献排名
 * @param {string} period  week | month | quarter
 * @returns {Array<{ name, orders, qty, amount, share, trend }>}
 */
export function fetchTopCustomers(period = 'month') {
  return request(`/api/reports/top-customers?period=${period}`)
}

// ─── 枚举值 ──────────────────────────────────────────────────────────────

/**
 * 获取客户类型列表
 * @returns {Promise<Array<string>>}
 */
export function fetchCustomerTypes() {
  return request('/api/enums/customers/types')
}

/**
 * 获取客户级别列表
 * @returns {Promise<Array<string>>}
 */
export function fetchCustomerLevels() {
  return request('/api/enums/customers/levels')
}

/**
 * 获取订单状态列表
 * @returns {Promise<Array<string>>}
 */
export function fetchOrderStatuses() {
  return request('/api/enums/orders/statuses')
}

/**
 * 获取订单优先级列表
 * @returns {Promise<Array<string>>}
 */
export function fetchOrderPriorities() {
  return request('/api/enums/orders/priorities')
}
