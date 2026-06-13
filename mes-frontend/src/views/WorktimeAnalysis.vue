<template>
  <div class="worktime-page">
    <!-- Page Header -->
    <div class="page-header">
      <div>
        <div class="page-title">工位工时分析</div>
        <div class="page-subtitle">动素分解 · MOD法标准工时 · 实际工时对比</div>
      </div>
      <div class="flex gap-2 items-center">
        <select v-model="selectedStation" class="select" style="width: 140px" @change="loadData">
          <option value="all">全部工位</option>
          <option v-for="s in stations" :key="s.value" :value="s.value">{{ s.label }}</option>
        </select>
        <select v-model="selectedShift" class="select" style="width: 120px" @change="loadData">
          <option v-for="s in metaShifts" :key="s.value" :value="s.value">{{ s.label }}</option>
        </select>
        <button class="btn btn-primary btn-sm" :disabled="loading" @click="exportWorktimePdf">
          <svg
            width="14"
            height="14"
            viewBox="0 0 24 24"
            fill="none"
            stroke="currentColor"
            stroke-width="2"
          >
            <path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4" />
            <polyline points="7 10 12 15 17 10" />
            <line x1="12" y1="15" x2="12" y2="3" />
          </svg>
          导出PDF
        </button>
        <button class="btn btn-danger btn-sm" :disabled="loading || cleaning" @click="confirmCleanup">
          <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
            <polyline points="3 6 5 6 21 6" />
            <path d="M19 6l-1 14a2 2 0 0 1-2 2H8a2 2 0 0 1-2-2L5 6" />
            <path d="M10 11v6" />
            <path d="M14 11v6" />
            <path d="M9 6V4a1 1 0 0 1 1-1h4a1 1 0 0 1 1 1v2" />
          </svg>
          {{ cleaning ? '清理中...' : '一键清理' }}
        </button>
      </div>
    </div>

    <!-- 错误提示 -->
    <div v-if="errorMsg" class="error-banner">
      <svg
        width="16"
        height="16"
        viewBox="0 0 24 24"
        fill="none"
        stroke="currentColor"
        stroke-width="2"
      >
        <circle cx="12" cy="12" r="10" />
        <line x1="12" y1="8" x2="12" y2="12" />
        <line x1="12" y1="16" x2="12.01" y2="16" />
      </svg>
      {{ errorMsg }}
    </div>

    <!-- Summary KPI -->
    <div class="summary-grid">
      <div v-for="s in summaryCards" :key="s.key" class="summary-card card">
        <div
          class="summary-icon"
          :style="`color:${s.color}; background:${s.color}15`"
          v-html="s.icon"
        ></div>
        <div class="summary-body">
          <div class="summary-value" :style="`color:${s.color}`">
            <span v-if="loading" class="skeleton-text"></span>
            <span v-else-if="s.value !== null">{{ s.value }}</span>
            <span v-else class="no-data">--</span>
          </div>
          <div class="summary-label">{{ s.label }}</div>
        </div>
      </div>
    </div>

    <!-- AI ECRS 改善建议 -->
    <div v-if="ecrsResult" class="card ecrs-panel">
      <div class="panel-header">
        <div>
          <div class="chart-title">AI 动素优化建议</div>
          <div class="panel-subtitle">基于 ECRS 框架的智能分析</div>
        </div>
        <button class="btn btn-ghost btn-sm" @click="ecrsResult = null; ecrsTaskId = null">
          关闭
        </button>
      </div>
      <div v-if="ecrsLoading" class="loading-block">正在分析中...</div>
      <div v-else-if="ecrsError" class="ecrs-error">{{ ecrsError }}</div>
      <div v-else class="ecrs-content">
        <pre class="ecrs-text">{{ ecrsResult }}</pre>
      </div>
    </div>

    <!-- Main Content -->
    <div class="analysis-layout">
      <!-- Left: Therblig动素明细 -->
      <div class="card therblig-panel">
        <div class="panel-header">
          <div>
            <div class="chart-title">Therblig 动素分解</div>
            <div v-if="activeRecord" class="panel-subtitle">
              {{ activeRecord.operation }} · {{ activeRecord.station }}
            </div>
            <div v-else class="panel-subtitle no-data">请在右侧选择工序</div>
          </div>
          <button
            v-if="activeRecord && !ecrsResult"
            class="btn btn-primary btn-xs"
            :disabled="ecrsLoading"
            @click="requestEcrsAnalysis"
          >
            AI ECRS分析
          </button>
        </div>

        <div v-if="loadingDetail" class="loading-block">加载动素数据...</div>
        <div v-else-if="!activeRecord || !thermRows.length" class="loading-block no-data">
          {{ activeRecord ? '暂无动素数据' : '请先从右侧工序列表选择一条记录' }}
        </div>
        <template v-else>
          <div class="therblig-table">
            <div class="therblig-head">
              <span>动素</span>
              <span>类型</span>
              <span>MOD数</span>
              <span>标准时间(s)</span>
              <span>实际时间(s)</span>
              <span>占比</span>
            </div>
            <div
              v-for="row in thermRows"
              :key="row.id"
              class="therblig-row"
              :class="{ 'row-waste': row.isWaste }"
            >
              <div class="therblig-name">
                <span class="therblig-symbol" :style="`background:${row.color}`">{{
                  row.symbol
                }}</span>
                {{ row.name }}
              </div>
              <div>
                <span class="badge" :class="row.isWaste ? 'badge-warning' : 'badge-primary'">
                  {{ row.isWaste ? '非增值' : '增值' }}
                </span>
              </div>
              <div class="mono">{{ row.mod }}</div>
              <div class="mono">{{ row.standardSeconds }}</div>
              <div class="mono" :class="row.actual > row.standardSeconds * 1.1 ? 'text-danger' : ''">
                {{ row.actual }}
              </div>
              <div class="pct-bar-wrap">
                <div class="pct-bar" :style="`width:${row.pct}%; background:${row.color}`"></div>
                <span class="pct-label">{{ row.pct }}%</span>
              </div>
            </div>
          </div>

          <div class="therblig-footer">
            <div class="tf-item">
              <span class="tf-label">宽放率</span>
              <span class="tf-value">{{ (allowanceRate * 100).toFixed(0) }}%</span>
            </div>
            <div class="tf-item">
              <span class="tf-label">标准工时(MOD法)</span>
              <span class="tf-value tf-highlight">{{ standardTime }}s</span>
            </div>
            <div class="tf-item">
              <span class="tf-label">实际工时</span>
              <span
                class="tf-value"
                :class="
                  actualVsStd > 110
                    ? 'text-danger'
                    : actualVsStd < 90
                      ? 'text-warning'
                      : 'text-success'
                "
              >
                {{ activeRecord.actual }}s(效率{{ actualVsStd }}%)
              </span>
            </div>
          </div>
        </template>
      </div>

      <!-- Right Panel -->
      <div class="right-panel">
        <!-- 工时对比图 -->
        <div class="card chart-card">
          <div class="chart-header">
            <div>
              <div class="chart-title">各工位工时对比</div>
              <div class="chart-subtitle">标准工时 vs 实际工时(秒/件)</div>
            </div>
          </div>
          <div class="chart-body">
            <div v-if="loading" class="chart-placeholder">加载中...</div>
            <div v-else-if="!filteredOps.length" class="chart-placeholder no-data">暂无数据</div>
            <canvas v-else ref="compareChart" height="180"></canvas>
          </div>
        </div>

        <!-- 工序明细表 -->
        <div class="card ops-table-card">
          <div class="panel-header">
            <div class="chart-title">工序工时明细</div>
            <div class="flex gap-2">
              <input
                v-model="searchOp"
                type="text"
                class="search-input-sm"
                placeholder="搜索工序..."
              />
            </div>
          </div>
          <div class="table-wrapper">
            <table class="table">
              <thead>
                <tr>
                  <th>工序</th>
                  <th>工位</th>
                  <th>MOD数</th>
                  <th>标准工时</th>
                  <th>实际工时</th>
                  <th>效率</th>
                  <th>非增值占比</th>
                  <th>操作</th>
                </tr>
              </thead>
              <tbody>
                <tr v-if="loading">
                  <td colspan="8" class="td-center">
                    <span
                      class="skeleton-text"
                      style="width: 180px; height: 14px; display: inline-block"
                    ></span>
                  </td>
                </tr>
                <tr v-else-if="!filteredOps.length">
                  <td colspan="8" class="td-center no-data">
                    {{ operations.length ? '无匹配结果' : '暂无工序数据 - 请连接后端服务' }}
                  </td>
                </tr>
                <tr
                  v-for="op in filteredOps"
                  :key="op.id"
                  class="op-row"
                  :class="{ 'row-active': activeRecord && activeRecord.id === op.id }"
                  @click="selectRecord(op)"
                >
                  <td>{{ op.operation }}</td>
                  <td>
                    <span class="station-tag">{{ op.station }}</span>
                  </td>
                  <td class="mono">{{ op.modTotal }}</td>
                  <td class="mono">{{ op.standard }}s</td>
                  <td class="mono" :class="op.efficiency > 110 ? 'text-danger' : ''">
                    {{ op.actual }}s
                  </td>
                  <td>
                    <div class="eff-cell">
                      <div class="mini-progress">
                        <div
                          class="mini-bar"
                          :class="
                            op.efficiency > 110
                              ? 'bar-danger'
                              : op.efficiency >= 90
                                ? 'bar-success'
                                : 'bar-warning'
                          "
                          :style="`width:${Math.min(op.efficiency, 120)}%`"
                        ></div>
                      </div>
                      <span
                        class="eff-val"
                        :class="
                          op.efficiency > 110
                            ? 'text-danger'
                            : op.efficiency >= 90
                              ? 'text-success'
                              : 'text-warning'
                        "
                      >
                        {{ op.efficiency }}%
                      </span>
                    </div>
                  </td>
                  <td>
                    <span
                      :class="
                        op.wastePct > 25
                          ? 'text-danger'
                          : op.wastePct > 15
                            ? 'text-warning'
                            : 'text-success'
                      "
                    >
                      {{ op.wastePct }}%
                    </span>
                  </td>
                  <td class="action-cell">
                    <button class="btn btn-ghost btn-xs" @click.stop="selectRecord(op)">
                      分析
                    </button>
                    <button class="btn btn-ghost btn-xs calibrate-btn" @click.stop="calibrateHandler(op)">
                      校准
                    </button>
                  </td>
                </tr>
              </tbody>
            </table>
          </div>
        </div>
      </div>
    </div>
  </div>
</template>

<script setup>
import { ref, computed, onMounted, onUnmounted, watch, nextTick } from 'vue'
import {
  fetchWorktimeSummary,
  fetchOperations,
  fetchTherbligDetail,
  submitAiTask,
  fetchTaskStatus,
  downloadBlob,
  cleanupWorktimeData,
  calibrateWorktime,
  fetchMeta,
  fetchStations
} from '../api/index.js'
import { ElMessageBox } from 'element-plus'
import { useConfirm } from '../composables/useConfirm.js'
import DOMPurify from 'dompurify'

const stations = ref([])
const metaShifts = ref([])

const selectedStation = ref('all')
const selectedShift = ref('morning')
const searchOp = ref('')
const compareChart = ref(null)
let resizeHandler = null

const loading = ref(false)
const loadingDetail = ref(false)
const cleaning = ref(false)
const errorMsg = ref('')

const { openConfirm } = useConfirm()

// ─── ECRS 优化建议状态 ──────────────────────────────────────────────────────
const ecrsResult = ref(null)
const ecrsTaskId = ref(null)
const ecrsLoading = ref(false)
const ecrsError = ref('')
let ecrsPollTimer = null
let ecrsPollCount = 0
const ECRS_MAX_POLLS = 150 // 2s * 150 = 5min timeout

const summaryRaw = ref(null)
const operations = ref([])
const activeRecord = ref(null)
const thermRows = ref([])
const allowanceRate = ref(15)

function formatStdTime(hours) {
  const seconds = hours * 3600
  if (seconds < 60) return seconds.toFixed(1) + 's'
  if (seconds < 3600) return (seconds / 60).toFixed(1) + 'min'
  return hours.toFixed(2) + 'h'
}

// ─── Summary Cards(从 API 数据派生) ─────────────────────────────────────────
const summaryCards = computed(() => {
  const d = summaryRaw.value
  return [
    {
      key: 'total_ops',
      label: '工序数',
      value: d ? d.totalOps : null,
      color: '#1a6ef5',
      icon: DOMPurify.sanitize(`<svg width="22" height="22" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z"/><polyline points="14 2 14 8 20 8"/></svg>`)
    },
    {
      key: 'avg_efficiency',
      label: '平均效率',
      value: d ? d.avgEfficiency + '%' : null,
      color: '#10b981',
      icon: DOMPurify.sanitize(`<svg width="22" height="22" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><polyline points="22 12 18 12 15 21 9 3 6 12 2 12"/></svg>`)
    },
    {
      key: 'waste_ratio',
      label: '非增值占比',
      value: d ? d.wasteRatio + '%' : null,
      color: '#f59e0b',
      icon: DOMPurify.sanitize(`<svg width="22" height="22" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><circle cx="12" cy="12" r="10"/><line x1="12" y1="8" x2="12" y2="12"/><line x1="12" y1="16" x2="12.01" y2="16"/></svg>`)
    },
    {
      key: 'total_stdtime',
      label: '总标准工时',
      value: d ? formatStdTime(d.totalStdTimeHours) : null,
      color: '#6366f1',
      icon: DOMPurify.sanitize(`<svg width="22" height="22" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><circle cx="12" cy="12" r="10"/><polyline points="12 6 12 12 16 14"/></svg>`)
    }
  ]
})

// ─── Therblig 计算（计算下沉 — 公式在后端，前端不复算） ───────────────────────
const activeDetail = ref(null)  // 存储 fetchTherbligDetail 的完整返回

const efficiency = computed(() => activeDetail.value?.efficiency ?? null)
const efficiencyPct = computed(() => efficiency.value != null ? Math.round(efficiency.value * 100) : null)
const standardTime = computed(() => activeDetail.value?.standardTime ?? null)
const actualVsStd = computed(() => efficiencyPct.value != null ? efficiencyPct.value : '--')

// ─── Filter ───────────────────────────────────────────────────────────────────
const filteredOps = computed(() => {
  let list = operations.value
  if (searchOp.value) {
    list = list.filter(
      o => o.operation.includes(searchOp.value) || o.station.includes(searchOp.value)
    )
  }
  return list
})

// ─── Data Loading ─────────────────────────────────────────────────────────────
async function loadData() {
  loading.value = true
  errorMsg.value = ''
  activeRecord.value = null
  thermRows.value = []

  const [summaryResult, opsResult] = await Promise.allSettled([
    fetchWorktimeSummary(selectedStation.value, selectedShift.value),
    fetchOperations(selectedStation.value, selectedShift.value)
  ])

  if (summaryResult.status === 'fulfilled') {
    summaryRaw.value = summaryResult.value
  } else {
    summaryRaw.value = null
  }

  if (opsResult.status === 'fulfilled') {
    operations.value = opsResult.value
  } else {
    operations.value = []
    errorMsg.value = '工序数据加载失败,请确认后端服务已启动'
  }

  loading.value = false
  await nextTick()
  drawCompareChart()
}

async function selectRecord(op) {
  activeRecord.value = op
  thermRows.value = []
  allowanceRate.value = 15
  activeDetail.value = null  // 清空旧详情
  loadingDetail.value = true

  try {
    const detail = await fetchTherbligDetail(op.id)
    activeDetail.value = detail  // 保存完整返回供 standardTime/efficiency 使用
    thermRows.value = detail.rows || []
    allowanceRate.value = detail.allowanceRate ?? 15
  } catch {
    errorMsg.value = `动素数据加载失败(工序 ${op.id})`
  } finally {
    loadingDetail.value = false
  }
}

// ─── 标准工时校准 ──────────────────────────────────────────────────────────
async function calibrateHandler(op) {
  // P1-5: Replace sync window.prompt() with async ElMessageBox.prompt()
  // window.prompt blocks UI thread — swap to modal dialog
  let input = null
  try {
    const { value } = await ElMessageBox.prompt(
      `请输入工序"${op.operation}"的新标准工时（秒）：`,
      '标准工时校准',
      {
        confirmButtonText: '确认',
        cancelButtonText: '取消',
        inputValue: String(op.standard),
        inputPattern: /^\d+(\.\d+)?$/,
        inputErrorMessage: '请输入大于 0 的有效数值'
      }
    )
    input = value
  } catch {
    // User cancelled the prompt — silently return
    return
  }
  if (input === null || input === '') return
  const newValue = parseFloat(input)
  if (isNaN(newValue) || newValue <= 0) {
    errorMsg.value = '请输入大于 0 的有效数值'
    return
  }
  try {
    await calibrateWorktime(op.id, newValue * 1000)
    await loadData()
  } catch (err) {
    errorMsg.value = '校准失败: ' + (err.message || '未知错误')
  }
}

// ─── PDF 导出 ──────────────────────────────────────────────────────────────
function exportWorktimePdf() {
  downloadBlob(
    '/api/reports/worktime/pdf',
    `worktime_analysis_${selectedStation.value}_${selectedShift.value}.pdf`,
    { station: selectedStation.value, shift: selectedShift.value }
  )
}

// ─── 一键清理 ────────────────────────────────────────────────────────────────
async function confirmCleanup() {
  const ok = await openConfirm({
    title: '确认清理',
    message: '确定要一键清理所有工时分析数据吗？\n\n此操作将：\n• 删除所有工序工时记录\n• 删除所有动素(Therblig)分解数据\n• 保留原始过程段数据(用于重新计算)\n\n此操作不可撤销！'
  })
  if (!ok) return
  cleaning.value = true
  errorMsg.value = ''
  try {
    const result = await cleanupWorktimeData()
    console.log('清理完成:', result)
    // 清理后重新加载数据
    activeRecord.value = null
    thermRows.value = []
    await loadData()
  } catch (err) {
    errorMsg.value = '清理失败: ' + (err.message || '未知错误')
  } finally {
    cleaning.value = false
  }
}

// ─── AI ECRS 动素优化分析 ──────────────────────────────────────────────────
async function requestEcrsAnalysis() {
  if (!activeRecord.value) return
  ecrsLoading.value = true
  ecrsError.value = ''
  ecrsResult.value = null

  try {
    const res = await submitAiTask('therblig_optimization', {
      operation_id: activeRecord.value.id,
      station: activeRecord.value.station,
      operation: activeRecord.value.operation
    })
    ecrsTaskId.value = res.task_id
    startEcrsPolling(res.task_id)
  } catch (err) {
    ecrsError.value = '提交分析任务失败: ' + (err.message || '未知错误')
    ecrsLoading.value = false
  }
}

function startEcrsPolling(taskId) {
  stopEcrsPolling()
  ecrsPollCount = 0
  ecrsPollTimer = setInterval(async () => {
    ecrsPollCount++
    if (ecrsPollCount >= ECRS_MAX_POLLS) {
      ecrsError.value = '分析超时,请稍后重试'
      ecrsLoading.value = false
      stopEcrsPolling()
      return
    }
    try {
      const status = await fetchTaskStatus(taskId)
      if (status.status === 'completed') {
        ecrsResult.value = typeof status.result === 'string'
          ? status.result
          : JSON.stringify(status.result, null, 2)
        ecrsLoading.value = false
        stopEcrsPolling()
      } else if (status.status === 'failed') {
        ecrsError.value = '分析失败: ' + (status.error || '未知错误')
        ecrsLoading.value = false
        stopEcrsPolling()
      }
      // status === 'pending' | 'processing' -> keep polling
    } catch {
      ecrsError.value = '查询任务状态失败'
      ecrsLoading.value = false
      stopEcrsPolling()
    }
  }, 2000)
}

function stopEcrsPolling() {
  if (ecrsPollTimer) {
    clearInterval(ecrsPollTimer)
    ecrsPollTimer = null
  }
}

// ─── Chart ────────────────────────────────────────────────────────────────────
function drawCompareChart() {
  const canvas = compareChart.value
  if (!canvas || !filteredOps.value.length) return
  const ctx = canvas.getContext('2d')
  const W = canvas.offsetWidth || 400
  const H = 180
  const dpr = window.devicePixelRatio || 1
  canvas.width = W * dpr
  canvas.height = H * dpr
  canvas.style.width = W + 'px'
  canvas.style.height = H + 'px'
  ctx.scale(dpr, dpr)

  const data = filteredOps.value.slice(0, 6)
  const pad = { top: 20, right: 16, bottom: 36, left: 40 }
  const chartW = W - pad.left - pad.right
  const chartH = H - pad.top - pad.bottom
  const maxVal = Math.max(...data.map(d => Math.max(d.standard, d.actual))) + 10
  const groupW = chartW / data.length
  const barW = groupW * 0.32

  ctx.clearRect(0, 0, W, H)

  // Grid
  ctx.strokeStyle = '#f3f4f6'
  ctx.lineWidth = 1
  for (let i = 0; i <= 4; i++) {
    const y = pad.top + (chartH / 4) * i
    ctx.beginPath()
    ctx.moveTo(pad.left, y)
    ctx.lineTo(pad.left + chartW, y)
    ctx.stroke()
    const val = Math.round(maxVal - (maxVal / 4) * i)
    ctx.fillStyle = '#9ca3af'
    ctx.font = '10px sans-serif'
    ctx.textAlign = 'right'
    ctx.fillText(val + 's', pad.left - 4, y + 4)
  }

  data.forEach((op, i) => {
    const cx = pad.left + groupW * i + groupW / 2
    const x1 = cx - barW - 2
    const x2 = cx + 2

    const h1 = (op.standard / maxVal) * chartH
    ctx.fillStyle = '#93c5fd'
    ctx.beginPath()
    ctx.roundRect(x1, pad.top + chartH - h1, barW, h1, [3, 3, 0, 0])
    ctx.fill()

    const h2 = (op.actual / maxVal) * chartH
    ctx.fillStyle = op.actual > op.standard ? '#fca5a5' : '#6ee7b7'
    ctx.beginPath()
    ctx.roundRect(x2, pad.top + chartH - h2, barW, h2, [3, 3, 0, 0])
    ctx.fill()

    ctx.fillStyle = '#6b7280'
    ctx.font = '10px sans-serif'
    ctx.textAlign = 'center'
    ctx.fillText(op.station, cx, H - 8)
  })

  // Legend
  ctx.fillStyle = '#93c5fd'
  ctx.fillRect(pad.left, 4, 10, 8)
  ctx.fillStyle = '#6b7280'
  ctx.font = '10px sans-serif'
  ctx.textAlign = 'left'
  ctx.fillText('标准工时', pad.left + 13, 12)
  ctx.fillStyle = '#6ee7b7'
  ctx.fillRect(pad.left + 65, 4, 10, 8)
  ctx.fillStyle = '#6b7280'
  ctx.fillText('实际工时', pad.left + 78, 12)
}

onMounted(async () => {
  // 先加载元数据（工位/班次），再加载业务数据
  // 不设硬编码 fallback：元数据加载失败时显示错误提示
  try {
    const meta = await fetchMeta()
    stations.value = (await fetchStations()).map(s => ({
        value: s.name,
        label: `编号${s.name} - ${s.worker}(${s.line}-${s.shift})`
      }))
    metaShifts.value = (meta.shifts || []).map(s => ({ value: s.value, label: s.label }))
  } catch {
    errorMsg.value = '元数据加载失败，请刷新重试'
  }
  loadData()
  // P2 #82: debounce resize handler (200ms)
  let resizeTimer = null
  resizeHandler = () => {
    if (resizeTimer) clearTimeout(resizeTimer)
    resizeTimer = setTimeout(drawCompareChart, 200)
  }
  window.addEventListener('resize', resizeHandler)
})

onUnmounted(() => {
  stopEcrsPolling()
  if (resizeHandler) {
    window.removeEventListener('resize', resizeHandler)
    resizeHandler = null
  }
})

watch(filteredOps, () => {
  nextTick(drawCompareChart)
})
</script>

<style scoped>
.worktime-page {
  display: flex;
  flex-direction: column;
  gap: 20px;
}

.error-banner {
  display: flex;
  align-items: center;
  gap: 8px;
  padding: 10px 16px;
  background: #fff7ed;
  border: 1px solid #fed7aa;
  border-radius: 8px;
  font-size: var(--font-size-sm);
  color: #c2410c;
}

.skeleton-text {
  display: inline-block;
  width: 60px;
  height: 1em;
  background: linear-gradient(90deg, #e5e7eb 25%, #f3f4f6 50%, #e5e7eb 75%);
  background-size: 200% 100%;
  animation: shimmer 1.4s infinite;
  border-radius: 4px;
  vertical-align: middle;
}
@keyframes shimmer {
  0% {
    background-position: 200% 0;
  }
  100% {
    background-position: -200% 0;
  }
}

.no-data {
  color: var(--gray-400);
  font-size: var(--font-size-sm);
}

.summary-grid {
  display: grid;
  grid-template-columns: repeat(4, 1fr);
  gap: 14px;
}
.summary-card {
  display: flex;
  align-items: center;
  gap: 14px;
  padding: 16px 20px;
}
.summary-icon {
  width: 44px;
  height: 44px;
  border-radius: 10px;
  display: flex;
  align-items: center;
  justify-content: center;
  flex-shrink: 0;
}
.summary-value {
  font-size: 22px;
  font-weight: 700;
  line-height: 1.2;
  min-height: 1.2em;
}
.summary-label {
  font-size: var(--font-size-xs);
  color: var(--gray-500);
  margin-top: 2px;
}

.analysis-layout {
  display: flex;
  gap: 16px;
  align-items: flex-start;
}
.therblig-panel {
  flex: 0 0 480px;
}
.right-panel {
  flex: 1;
  min-width: 0;
  display: flex;
  flex-direction: column;
  gap: 16px;
}

.panel-header {
  padding: 16px 20px;
  border-bottom: 1px solid var(--gray-100);
}
.panel-subtitle {
  font-size: var(--font-size-xs);
  color: var(--gray-500);
  margin-top: 2px;
}

.loading-block {
  padding: 40px 20px;
  text-align: center;
  font-size: var(--font-size-sm);
  color: var(--gray-400);
}

.therblig-table {
  padding: 0 4px;
}
.therblig-head,
.therblig-row {
  display: grid;
  grid-template-columns: 2fr 1fr 0.8fr 1.2fr 1.2fr 1.4fr;
  gap: 8px;
  padding: 8px 16px;
  align-items: center;
  font-size: var(--font-size-xs);
}
.therblig-head {
  color: var(--gray-400);
  font-weight: 600;
  font-size: 11px;
  background: var(--gray-50);
  text-transform: uppercase;
  letter-spacing: 0.05em;
}
.therblig-row {
  border-bottom: 1px solid var(--gray-100);
  transition: background 0.1s;
}
.therblig-row:hover {
  background: var(--gray-50);
}
.row-waste {
  background: #fffbeb;
}
.row-waste:hover {
  background: #fef3c7;
}

.therblig-name {
  display: flex;
  align-items: center;
  gap: 8px;
  color: var(--gray-700);
  font-weight: 500;
}
.therblig-symbol {
  width: 22px;
  height: 22px;
  border-radius: 5px;
  display: flex;
  align-items: center;
  justify-content: center;
  font-size: 10px;
  font-weight: 700;
  color: #fff;
  flex-shrink: 0;
}
.mono {
  font-family: monospace;
  color: var(--gray-700);
}
.pct-bar-wrap {
  display: flex;
  align-items: center;
  gap: 5px;
}
.pct-bar {
  height: 6px;
  border-radius: 3px;
  min-width: 2px;
  max-width: 60px;
}
.pct-label {
  font-size: 11px;
  color: var(--gray-500);
}

.therblig-footer {
  display: flex;
  flex-direction: column;
  gap: 6px;
  padding: 14px 16px;
  background: var(--gray-50);
  border-top: 1px solid var(--gray-100);
}
.tf-item {
  display: flex;
  justify-content: space-between;
  align-items: center;
  font-size: var(--font-size-sm);
}
.tf-label {
  color: var(--gray-500);
}
.tf-value {
  font-weight: 600;
  color: var(--gray-800);
}
.tf-highlight {
  color: var(--primary);
  font-size: 15px;
}

.ops-table-card {
  padding: 0;
}
.search-input-sm {
  height: 30px;
  padding: 0 10px;
  border: 1px solid var(--gray-200);
  border-radius: 6px;
  font-size: var(--font-size-xs);
  outline: none;
  background: var(--gray-50);
}
.station-tag {
  font-size: 11px;
  padding: 2px 7px;
  background: var(--primary-bg);
  color: var(--primary);
  border-radius: 4px;
  font-weight: 600;
}
.op-row {
  cursor: pointer;
  transition: background 0.1s;
}
.op-row:hover {
  background: var(--gray-50);
}
.row-active {
  background: #e8f0fe !important;
}
.td-center {
  text-align: center;
  padding: 20px;
}

.action-cell {
  display: flex;
  gap: 6px;
  align-items: center;
}
.calibrate-btn {
  color: var(--gray-500);
}
.calibrate-btn:hover {
  color: var(--primary);
}

.eff-cell {
  display: flex;
  align-items: center;
  gap: 6px;
}
.mini-progress {
  width: 50px;
  height: 5px;
  background: var(--gray-200);
  border-radius: 3px;
  overflow: hidden;
}
.mini-bar {
  height: 100%;
  border-radius: 3px;
}
.bar-success {
  background: var(--success);
}
.bar-warning {
  background: var(--warning);
}
.bar-danger {
  background: var(--danger);
}
.eff-val {
  font-size: 12px;
  font-weight: 600;
  min-width: 36px;
}

.text-danger {
  color: var(--danger);
}
.text-warning {
  color: var(--warning);
}
.text-success {
  color: var(--success);
}

.chart-card {
  padding: 20px;
}
.chart-header {
  display: flex;
  justify-content: space-between;
  align-items: flex-start;
  margin-bottom: 14px;
}
.chart-title {
  font-size: var(--font-size-base);
  font-weight: 600;
  color: var(--gray-800);
}
.chart-subtitle {
  font-size: var(--font-size-xs);
  color: var(--gray-400);
  margin-top: 2px;
}
.chart-body {
  min-height: 180px;
}
.chart-body canvas {
  width: 100% !important;
}
.chart-placeholder {
  display: flex;
  align-items: center;
  justify-content: center;
  height: 180px;
  color: var(--gray-400);
  font-size: var(--font-size-sm);
}

.btn-xs {
  padding: 3px 8px;
  font-size: 11px;
  height: 24px;
}

@media (max-width: 1200px) {
  .analysis-layout {
    flex-direction: column;
  }
  .therblig-panel {
    flex: none;
    width: 100%;
  }
  .summary-grid {
    grid-template-columns: repeat(2, 1fr);
  }
}
@media (max-width: 600px) {
  .summary-grid {
    grid-template-columns: 1fr 1fr;
  }
}

/* ECRS Panel */
.ecrs-panel {
  border: 1px solid var(--primary-bg);
  border-radius: 10px;
  overflow: hidden;
}
.ecrs-panel .panel-header {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
}
.ecrs-content {
  padding: 16px 20px;
}
.ecrs-text {
  font-size: var(--font-size-sm);
  line-height: 1.7;
  white-space: pre-wrap;
  word-break: break-word;
  color: var(--gray-700);
  background: var(--gray-50);
  border-radius: 8px;
  padding: 16px;
  max-height: 320px;
  overflow-y: auto;
  font-family: inherit;
}
.ecrs-error {
  padding: 16px 20px;
  color: var(--danger);
  font-size: var(--font-size-sm);
}
</style>
