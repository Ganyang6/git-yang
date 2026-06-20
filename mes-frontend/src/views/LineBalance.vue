<template>
  <div class="lb-page">
    <!-- Page Header -->
    <div class="page-header">
      <div>
        <div class="page-title">生产线平衡分析</div>
        <div class="page-subtitle">平衡率 · 平滑指数 · 瓶颈诊断 · ECRS改善建议</div>
      </div>
      <div class="flex gap-2">
        <select v-model="selectedLine" class="select" style="width: 150px" @change="loadData">
          <option v-for="l in metaLines" :key="l.value" :value="l.value">{{ l.label }}</option>
        </select>
        <button
          class="btn btn-outline btn-sm"
          :disabled="!stations.length"
          @click="showSimulate = !showSimulate"
        >
          <svg
            width="14"
            height="14"
            viewBox="0 0 24 24"
            fill="none"
            stroke="currentColor"
            stroke-width="2"
          >
            <path d="M11 4H4a2 2 0 0 0-2 2v14a2 2 0 0 0 2 2h14a2 2 0 0 0 2-2v-7" />
            <path d="M18.5 2.5a2.121 2.121 0 0 1 3 3L12 15l-4 1 1-4 9.5-9.5z" />
          </svg>
          What-If 仿真
        </button>
        <button class="btn btn-primary btn-sm" @click="exportLineBalancePdf" :disabled="exporting">
          <span v-if="exporting" class="spinner-sm"></span>
          <svg
            v-else
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
          {{ exporting ? '导出中...' : '导出PDF' }}
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

    <!-- KPI Strip -->
    <div class="lb-kpi-strip">
      <div class="lb-kpi-item">
        <div class="lb-kpi-label">生产线平衡率</div>
        <div
          class="lb-kpi-value"
          :class="
            !lbData
              ? ''
              : balanceRate >= 85
                ? 'val-success'
                : balanceRate >= 70
                  ? 'val-warning'
                  : 'val-danger'
          "
        >
          <span v-if="loading" class="skeleton-text"></span>
          <span v-else-if="lbData !== null">{{ balanceRate }}%</span>
          <span v-else class="no-data">--</span>
        </div>
        <div class="lb-kpi-bar">
          <div
            class="lb-kpi-fill"
            :class="balanceRate >= 85 ? 'fill-success' : 'fill-warning'"
            :style="`width:${lbData ? balanceRate : 0}%`"
          ></div>
        </div>
      </div>
      <div class="lb-kpi-divider"></div>
      <div class="lb-kpi-item">
        <div class="lb-kpi-label">平滑指数（SI）</div>
        <div class="lb-kpi-value val-info">
          <span v-if="loading" class="skeleton-text"></span>
          <span v-else-if="lbData">{{ smoothIndex }}</span>
          <span v-else class="no-data">--</span>
        </div>
        <div class="lb-kpi-hint">目标 &lt; 30</div>
      </div>
      <div class="lb-kpi-divider"></div>
      <div class="lb-kpi-item">
        <div class="lb-kpi-label">节拍时间（Takt）</div>
        <div class="lb-kpi-value val-primary">
          <span v-if="loading" class="skeleton-text"></span>
          <span v-else-if="lbData">{{ lbData.taktTime }}s</span>
          <span v-else class="no-data">--</span>
        </div>
        <div v-if="lbData" class="lb-kpi-hint">需求: {{ lbData.dailyDemand }}件/日</div>
      </div>
      <div class="lb-kpi-divider"></div>
      <div class="lb-kpi-item">
        <div class="lb-kpi-label">瓶颈工位</div>
        <div class="lb-kpi-value val-danger">
          <span v-if="loading" class="skeleton-text"></span>
          <span v-else-if="lbData && lbData.bottleneck">{{ getStationDisplayName(lbData.bottleneck) }}</span>
          <span v-else class="no-data">--</span>
        </div>
        <div v-if="lbData && lbData.bottleneck" class="lb-kpi-hint">
          工时 {{ bottleneckStation?.time ?? '-' }}s
        </div>
      </div>
      <div class="lb-kpi-divider"></div>
      <div class="lb-kpi-item">
        <div class="lb-kpi-label">损失产能</div>
        <div class="lb-kpi-value val-warning">
          <span v-if="loading" class="skeleton-text"></span>
          <span v-else-if="lbData">{{ lbData.lostCapacity }}件/日</span>
          <span v-else class="no-data">--</span>
        </div>
        <div v-if="lbData" class="lb-kpi-hint">
          约合 ¥{{ (lbData.lostValue || 0).toLocaleString() }}
        </div>
      </div>
    </div>

    <!-- Main Charts -->
    <div class="lb-charts">
      <!-- Balance Chart -->
      <div class="card lb-bar-card">
        <div class="card-header-inner">
          <div>
            <div class="chart-title">工位工时分布（山积图）</div>
            <div class="chart-subtitle">蓝柱=当前工时，橙线=节拍时间，红柱=超节拍工位</div>
          </div>
        </div>
        <div v-if="loading" class="chart-placeholder">加载中...</div>
        <div v-else-if="!stations.length" class="chart-placeholder no-data">
          暂无工位数据 -- 请连接后端服务
        </div>
        <canvas v-else ref="lbChart" height="200"></canvas>
      </div>

      <!-- What-If Panel -->
      <div v-if="showSimulate && stations.length" class="card whatif-card">
        <div class="card-header-inner">
          <div class="chart-title">What-If 仿真</div>
          <div class="chart-subtitle">拖动调整工时，实时预测平衡率</div>
        </div>
        <div class="whatif-list">
          <div v-for="st in simulateStations" :key="st.id" class="whatif-row">
            <span class="whatif-name">{{ getStationDisplayName(st.name) }}</span>
            <input
              v-model.number="st.simTime"
              type="range"
              class="whatif-slider"
              :min="10"
              :max="Math.max(...stations.map(s => s.time)) + 30"
              @input="recalcSimulate"
            />
            <span class="whatif-val">{{ st.simTime }}s</span>
          </div>
        </div>
        <div class="whatif-result">
          <span>仿真平衡率：</span>
          <strong :class="simBalance >= 85 ? 'val-success' : 'val-warning'"
            >{{ simBalance }}%</strong
          >
          <span style="margin-left: 12px">仿真SI：</span>
          <strong class="val-info">{{ simSI }}</strong>
        </div>
      </div>
    </div>

    <!-- Line Layout 2D Visualization -->
    <div v-if="stations.length" class="card layout-card">
      <div class="card-header-inner">
        <div>
          <div class="chart-title">产线布局</div>
          <div class="chart-subtitle">方块大小=工时，颜色=平衡状态，点击工位查看详情</div>
        </div>
      </div>
      <div class="layout-container">
        <svg
          ref="layoutSvg"
          :viewBox="`0 0 ${svgWidth} ${svgHeight}`"
          class="layout-svg"
        >
          <defs>
            <filter id="shadow" x="-5%" y="-5%" width="115%" height="115%">
              <feDropShadow dx="1" dy="2" stdDeviation="3" flood-opacity="0.1" />
            </filter>
            <marker
              id="arrowhead"
              markerWidth="8"
              markerHeight="6"
              refX="8"
              refY="3"
              orient="auto"
            >
              <polygon points="0 0, 8 3, 0 6" fill="#9ca3af" />
            </marker>
          </defs>

          <!-- Connection lines between stations -->
          <line
            v-for="(conn, idx) in layoutConnections"
            :key="'conn-' + idx"
            :x1="conn.x1"
            :y1="conn.y1"
            :x2="conn.x2"
            :y2="conn.y2"
            stroke="#d1d5db"
            stroke-width="2"
            marker-end="url(#arrowhead)"
            stroke-dasharray="6 3"
          />

          <!-- Animated workpiece dots -->
          <circle
            v-for="(dot, idx) in animatedDots"
            :key="'dot-' + dot.id"
            r="4"
            :fill="dot.color"
            :cx="dot.cx"
            :cy="dot.cy"
            opacity="0.8"
          />

          <!-- Station blocks -->
          <g
            v-for="st in layoutStations"
            :key="st.id"
            class="station-block"
            :transform="`translate(${st.x}, ${st.y})`"
            @mouseenter="hoveredStation = st.stationId"
            @mouseleave="hoveredStation = null"
          >
            <rect
              :width="st.w"
              :height="st.h"
              :rx="8"
              :fill="st.bgColor"
              :stroke="st.borderColor"
              stroke-width="2"
              filter="url(#shadow)"
              class="station-rect"
            />
            <text
              :x="st.w / 2"
              :y="st.h / 2 - 8"
              text-anchor="middle"
              :font-size="st.fontSize"
              font-weight="700"
              :fill="st.textColor"
            >{{ getStationDisplayName(st.name) }}</text>
            <text
              :x="st.w / 2"
              :y="st.h / 2 + 12"
              text-anchor="middle"
              font-size="11"
              :fill="st.timeColor"
            >{{ st.time }}s</text>
            <text
              v-if="st.isBottleneck"
              :x="st.w / 2"
              :y="st.h / 2 + 28"
              text-anchor="middle"
              font-size="9"
              fill="#ef4444"
              font-weight="600"
            >瓶颈</text>
          </g>
        </svg>

        <!-- Tooltip on hover -->
        <div
          v-if="hoveredStation !== null && stationTooltip"
          class="layout-tooltip"
          :style="{ left: stationTooltip.x + 'px', top: stationTooltip.y + 'px' }"
        >
          <div class="tooltip-title">{{ stationTooltip.name }}</div>
          <div class="tooltip-row">
            <span class="tooltip-label">工时:</span>
            <span class="tooltip-value">{{ stationTooltip.time }}s</span>
          </div>
          <div class="tooltip-row">
            <span class="tooltip-label">占比:</span>
            <span class="tooltip-value">{{ stationTooltip.pct }}%</span>
          </div>
          <div class="tooltip-row">
            <span class="tooltip-label">状态:</span>
            <span class="tooltip-value" :class="stationTooltip.statusClass">{{ stationTooltip.statusLabel }}</span>
          </div>
        </div>
      </div>
    </div>

    <!-- ECRS Table + Causal Analysis -->
    <div class="lb-bottom">
      <!-- Bottleneck Causal Analysis -->
      <div class="card causal-card">
        <div class="card-header-inner">
          <div class="chart-title">瓶颈因果推断</div>
          <div class="chart-subtitle">基于规则引擎的自动诊断</div>
        </div>
        <div v-if="loading" class="chart-placeholder">加载中...</div>
        <div v-else-if="!causalData.length" class="chart-placeholder no-data">暂无诊断数据</div>
        <div v-else class="causal-list">
          <div v-for="c in causalData" :key="c.id" class="causal-item">
            <div class="causal-station">{{ getStationDisplayName(c.station) }}</div>
            <div class="causal-flow">
              <div class="causal-cond">
                <div class="causal-cond-label">观测条件</div>
                <div class="causal-cond-content">{{ c.condition }}</div>
              </div>
              <div class="causal-arrow">
                <svg
                  width="20"
                  height="20"
                  viewBox="0 0 24 24"
                  fill="none"
                  stroke="currentColor"
                  stroke-width="2"
                >
                  <polyline points="9 18 15 12 9 6" />
                </svg>
              </div>
              <div class="causal-cause">
                <div class="causal-cond-label" style="color: var(--danger)">推断原因</div>
                <div class="causal-cond-content">{{ c.cause }}</div>
              </div>
              <div class="causal-arrow">
                <svg
                  width="20"
                  height="20"
                  viewBox="0 0 24 24"
                  fill="none"
                  stroke="currentColor"
                  stroke-width="2"
                >
                  <polyline points="9 18 15 12 9 6" />
                </svg>
              </div>
              <div class="causal-action">
                <div class="causal-cond-label" style="color: var(--success)">推荐措施</div>
                <div class="causal-cond-content">{{ c.action }}</div>
              </div>
            </div>
            <div class="causal-impact">
              预计节省 <strong>{{ c.saving }}</strong> · 平衡率提升
              <strong>{{ c.improvement }}</strong>
            </div>
          </div>
        </div>
      </div>

      <!-- ECRS Table -->
      <div class="card ecrs-card">
        <div class="card-header-inner">
          <div class="chart-title">ECRS 改善建议清单</div>
          <div class="chart-subtitle">消除 / 合并 / 重排 / 简化</div>
        </div>
        <div class="table-wrapper">
          <table class="table">
            <thead>
              <tr>
                <th>ECRS</th>
                <th>工位</th>
                <th>改善内容</th>
                <th>预计节省</th>
                <th>难度</th>
                <th>优先级</th>
                <th>状态</th>
              </tr>
            </thead>
            <tbody>
              <tr v-if="loading">
                <td colspan="7" class="td-center">
                  <span
                    class="skeleton-text"
                    style="width: 160px; height: 14px; display: inline-block"
                  ></span>
                </td>
              </tr>
              <tr v-else-if="!ecrsList.length">
                <td colspan="7" class="td-center no-data">暂无 ECRS 数据</td>
              </tr>
              <tr v-for="ecrs in ecrsList" :key="ecrs.id">
                <td>
                  <span class="ecrs-tag" :class="`ecrs-${ecrs.type}`">{{ ecrs.typeLabel }}</span>
                </td>
                <td>
                  <span class="station-tag">{{ getStationDisplayName(ecrs.station) }}</span>
                </td>
                <td style="max-width: 200px; color: var(--gray-700)">{{ ecrs.content }}</td>
                <td>
                  <span class="text-success font-bold">{{ ecrs.saving }}</span>
                </td>
                <td>
                  <span class="difficulty-dots">
                    <span
                      v-for="n in 3"
                      :key="n"
                      class="dot"
                      :class="n <= ecrs.difficulty ? 'dot-filled' : ''"
                    ></span>
                  </span>
                </td>
                <td>
                  <span
                    class="badge"
                    :class="
                      ecrs.priority === 'P1'
                        ? 'badge-danger'
                        : ecrs.priority === 'P2'
                          ? 'badge-warning'
                          : 'badge-gray'
                    "
                  >
                    {{ ecrs.priority }}
                  </span>
                </td>
                <td>
                  <span
                    class="badge"
                    :class="
                      ecrs.status === 'done'
                        ? 'badge-success'
                        : ecrs.status === 'doing'
                          ? 'badge-primary'
                          : 'badge-gray'
                    "
                  >
                    {{
                      ecrs.status === 'done'
                        ? '已完成'
                        : ecrs.status === 'doing'
                          ? '进行中'
                          : '待处理'
                    }}
                  </span>
                </td>
              </tr>
            </tbody>
          </table>
        </div>
      </div>
    </div>
  </div>
</template>

<script setup>
import { ref, computed, onMounted, onUnmounted, watch, nextTick } from 'vue'
import { fetchLineBalanceFull, downloadBlob, fetchStations } from '../api/index.js'
import { useToast } from '../composables/useToast.js'

const stationsMeta = ref([])

const selectedLine = ref('')

// Station display data (from /api/stations)
const metaLines = computed(() => {
  const lines = [...new Set(stationsMeta.value.map(s => s.line))].filter(Boolean)
  return lines.map(l => ({ value: l, label: l }))
})

const stationDisplayMap = computed(() => {
  const map = {}
  for (const s of stationsMeta.value) {
    if (s.name) map[s.name] = s
  }
  return map
})

function getStationDisplayName(stationId) {
  if (!stationId || !stationsMeta.value.length) return stationId
  // 精确匹配优先：先用完整 stationId 查询
  let info = stationDisplayMap.value[stationId]
  if (info) {
    return `编号${info.name} - ${info.worker}(${info.line}-${info.shift})`
  }
  // 降级：提取数字后缀匹配（如 "w1" → "1"）
  const match = stationId.match(/(\d+)$/)
  const num = match ? String(parseInt(match[1], 10)) : stationId
  info = stationDisplayMap.value[num]
  if (info) {
    return `编号${info.name} - ${info.worker}(${info.line}-${info.shift})`
  }
  return stationId
}
const showSimulate = ref(false)
const lbChart = ref(null)
let resizeHandler = null

const { showToast } = useToast()

const loading = ref(false)
const exporting = ref(false)

// ─── PDF Export ──────────────────────────────────────────────────────────────
async function exportLineBalancePdf() {
  exporting.value = true
  try {
    await downloadBlob(
      '/api/reports/line-balance/pdf',
      `line_balance_${selectedLine.value}.pdf`,
      { line: selectedLine.value }
    )
  } catch {
    showToast('PDF 导出失败，请重试', 'error')
  } finally {
    exporting.value = false
  }
}
const errorMsg = ref('')

// ─── Raw API Data ─────────────────────────────────────────────────────────────
const lbData = ref(null)

// Derived
const stations = computed(() => lbData.value?.stations || [])
const causalData = computed(() => lbData.value?.causalRules || [])
const ecrsList = computed(() => lbData.value?.ecrsItems || [])

// P1-2: bottleneck is a string (station name); find the matching station from stations list
const bottleneckStation = computed(() => {
  if (!lbData.value?.bottleneck || !stations.value.length) return null
  return stations.value.find(s => s.name === lbData.value.bottleneck) || null
})

// 使用 API 返回的 balanceRate/smoothIndex （计算下沉 — 不自行复算）
const balanceRate = computed(() => lbData.value?.balanceRate != null ? lbData.value.balanceRate * 100 : null)
const smoothIndex = computed(() => lbData.value?.smoothIndex != null ? lbData.value.smoothIndex : null)

// ─── What-If Simulation ───────────────────────────────────────────────────────
const simulateStations = ref([])
const simBalance = ref(0)
const simSI = ref('0')

watch(stations, (newStations) => {
  // What-If simulation sync
  simulateStations.value = newStations.map(s => ({ ...s, simTime: s.time }))
  simBalance.value = balanceRate.value
  simSI.value = smoothIndex.value

  // Canvas chart redraw
  nextTick(drawLbChart)

  // Animation dots
  if (newStations.length > 0 && !animationFrameId && !document.hidden) {
    animateDots()
  }
})

// P2 #84: Pause animation when tab is not visible
function onVisibilityChange() {
  if (document.hidden) {
    if (animationFrameId) {
      cancelAnimationFrame(animationFrameId)
      animationFrameId = null
    }
  } else {
    if (stations.value.length > 0 && !animationFrameId) {
      animateDots()
    }
  }
}

function recalcSimulate() {
  const list = simulateStations.value
  if (!list.length) return
  const total = list.reduce((s, st) => s + st.simTime, 0)
  const max = Math.max(...list.map(s => s.simTime))
  simBalance.value = Math.round((total / (max * list.length)) * 1000) / 10
  const si = Math.sqrt(list.reduce((s, st) => s + Math.pow(max - st.simTime, 2), 0))
  simSI.value = si.toFixed(1)
  drawLbChart()
}

// ─── Line Layout Visualization ─────────────────────────────────────
const layoutSvg = ref(null)
const hoveredStation = ref(null)
const svgWidth = 900
const svgHeight = 140
let animationFrameId = null
const animatedDots = ref([])
let dotAnimProgress = 0

const layoutStations = computed(() => {
  const list = stations.value
  if (!list.length) return []
  const maxTime = Math.max(...list.map(s => s.time), 1)
  const avgTime = list.length ? list.reduce((s, st) => s + st.time, 0) / list.length : 1

  // Layout: horizontal flow, stations evenly distributed
  const padding = 40
  const gap = 60
  const availableW = svgWidth - padding * 2 - gap * (list.length - 1)
  const blockW = Math.min(Math.max(availableW / list.length, 80), 140)
  const totalLayoutW = blockW * list.length + gap * (list.length - 1)
  const startX = (svgWidth - totalLayoutW) / 2

  return list.map((st, i) => {
    const ratio = st.time / maxTime
    const blockH = Math.round(60 + ratio * 40) // 60-100px height
    const x = startX + i * (blockW + gap)
    const y = (svgHeight - blockH) / 2
    const avgRatio = st.time / avgTime

    let bgColor, borderColor, statusLabel
    if (avgRatio > 0.95) {
      bgColor = '#fef2f2'
      borderColor = '#ef4444'
      statusLabel = '瓶颈'
    } else if (avgRatio > 0.80) {
      bgColor = '#fffbeb'
      borderColor = '#f59e0b'
      statusLabel = '偏高'
    } else {
      bgColor = '#f0fdf4'
      borderColor = '#22c55e'
      statusLabel = '正常'
    }

    return {
      id: st.id || i,
      stationId: i,
      name: getStationDisplayName(st.name),
      time: showSimulate.value ? (simulateStations.value[i]?.simTime || st.time) : st.time,
      isBottleneck: st.isBottleneck,
      pct: Math.round((st.time / list.reduce((s, s2) => s + s2.time, 0)) * 100),
      x,
      y,
      w: blockW,
      h: blockH,
      bgColor,
      borderColor,
      textColor: '#1f2937',
      timeColor: avgRatio > 0.95 ? '#ef4444' : avgRatio > 0.80 ? '#f59e0b' : '#22c55e',
      fontSize: Math.min(Math.max(blockW / 8, 11), 14),
      statusLabel,
      cx: x + blockW / 2,
      cy: y + blockH / 2
    }
  })
})

const layoutConnections = computed(() => {
  const list = layoutStations.value
  if (list.length < 2) return []
  const connections = []
  for (let i = 0; i < list.length - 1; i++) {
    const from = list[i]
    const to = list[i + 1]
    connections.push({
      x1: from.x + from.w,
      y1: from.cy,
      x2: to.x,
      y2: to.cy
    })
  }
  return connections
})

const stationTooltip = computed(() => {
  if (hoveredStation.value === null) return null
  const st = layoutStations.value[hoveredStation.value]
  if (!st) return null
  const list = layoutStations.value
  const avgTime = list.length ? list.reduce((s, s2) => s + s2.time, 0) / list.length : 1
  const avgRatio = st.time / avgTime
  return {
    name: st.name,
    time: st.time,
    pct: st.pct,
    x: st.cx + 10,
    y: st.y - 10,
    statusLabel: st.statusLabel,
    statusClass: avgRatio > 0.95 ? 'val-danger' : avgRatio > 0.80 ? 'val-warning' : 'val-success'
  }
})

function animateDots() {
  const conns = layoutConnections.value
  if (!conns.length) return

  dotAnimProgress += 0.005
  if (dotAnimProgress > 1) dotAnimProgress -= 1

  const dots = conns.map((conn, i) => {
    const offset = (dotAnimProgress + i * 0.15) % 1
    const cx = conn.x1 + (conn.x2 - conn.x1) * offset
    const cy = conn.y1 + (conn.y2 - conn.y1) * offset
    return {
      id: `dot-${i}`,
      cx,
      cy,
      color: '#1a6ef5'
    }
  })
  animatedDots.value = dots
  animationFrameId = requestAnimationFrame(animateDots)
}

onUnmounted(() => {
  if (animationFrameId) {
    cancelAnimationFrame(animationFrameId)
    animationFrameId = null
  }
})

// ─── Data Loading ─────────────────────────────────────────────────────────────
async function loadData() {
  loading.value = true
  errorMsg.value = ''
  showSimulate.value = false

  try {
    lbData.value = await fetchLineBalanceFull(selectedLine.value)
  } catch (e) {
    lbData.value = null
    errorMsg.value = '线平衡数据加载失败，请确认后端服务已启动'
  } finally {
    loading.value = false
    await nextTick()
    drawLbChart()
  }
}

// ─── Chart Drawing ────────────────────────────────────────────────────────────
function drawLbChart() {
  const canvas = lbChart.value
  if (!canvas || !stations.value.length) return
  const ctx = canvas.getContext('2d')
  const W = canvas.offsetWidth || 600
  const H = 200
  const dpr = window.devicePixelRatio || 1
  canvas.width = W * dpr
  canvas.height = H * dpr
  canvas.style.width = W + 'px'
  canvas.style.height = H + 'px'
  ctx.scale(dpr, dpr)

  const takt = lbData.value?.taktTime
  const data = showSimulate.value
    ? simulateStations.value.map(s => ({ ...s, time: s.simTime }))
    : stations.value

  const maxVal = Math.max(...data.map(s => s.time), takt || 0) + 10
  const pad = { top: 20, right: 20, bottom: 36, left: 44 }
  const chartW = W - pad.left - pad.right
  const chartH = H - pad.top - pad.bottom
  const barW = (chartW / data.length) * 0.58
  const gap = chartW / data.length

  ctx.clearRect(0, 0, W, H)

  // Grid
  ctx.strokeStyle = '#f3f4f6'
  ctx.lineWidth = 1
  for (let i = 0; i <= 5; i++) {
    const y = pad.top + (chartH / 5) * i
    ctx.beginPath()
    ctx.moveTo(pad.left, y)
    ctx.lineTo(pad.left + chartW, y)
    ctx.stroke()
    const val = Math.round(maxVal - (maxVal / 5) * i)
    ctx.fillStyle = '#9ca3af'
    ctx.font = '10px sans-serif'
    ctx.textAlign = 'right'
    ctx.fillText(val + 's', pad.left - 4, y + 4)
  }

  // Takt line
  if (takt) {
    const taktY = pad.top + chartH - (takt / maxVal) * chartH
    ctx.beginPath()
    ctx.strokeStyle = '#f59e0b'
    ctx.lineWidth = 2
    ctx.setLineDash([6, 4])
    ctx.moveTo(pad.left, taktY)
    ctx.lineTo(pad.left + chartW, taktY)
    ctx.stroke()
    ctx.setLineDash([])
    ctx.fillStyle = '#f59e0b'
    ctx.font = 'bold 11px sans-serif'
    ctx.textAlign = 'right'
    ctx.fillText('Takt ' + takt + 's', pad.left + chartW - 4, taktY - 5)
  }

  // Bars
  data.forEach((s, i) => {
    const x = pad.left + gap * i + (gap - barW) / 2
    const barH = (s.time / maxVal) * chartH
    const y = pad.top + chartH - barH
    const isOver = takt ? s.time > takt : s.isBottleneck

    const grad = ctx.createLinearGradient(0, y, 0, y + barH)
    if (isOver) {
      grad.addColorStop(0, '#ef4444')
      grad.addColorStop(1, '#fca5a5')
    } else {
      grad.addColorStop(0, '#1a6ef5')
      grad.addColorStop(1, '#93c5fd')
    }
    ctx.fillStyle = grad
    ctx.beginPath()
    ctx.roundRect(x, y, barW, barH, [4, 4, 0, 0])
    ctx.fill()

    ctx.fillStyle = isOver ? '#ef4444' : '#374151'
    ctx.font = 'bold 11px sans-serif'
    ctx.textAlign = 'center'
    ctx.fillText(s.time + 's', x + barW / 2, y - 5)

    ctx.fillStyle = '#6b7280'
    ctx.font = '10px sans-serif'
    ctx.fillText(getStationDisplayName(s.name), x + barW / 2, H - 8)
  })
}

async function loadMeta() {
  try {
    stationsMeta.value = await fetchStations()
    if (metaLines.value.length > 0) {
      selectedLine.value = metaLines.value[0].value
    }
  } catch {
    errorMsg.value = '元数据加载失败'
  }
}

onMounted(async () => {
  await loadMeta()
  loadData()
  // P2 #83: debounce resize to avoid redundant redraws with stations watcher
  let resizeTimer = null
  resizeHandler = () => {
    if (resizeTimer) clearTimeout(resizeTimer)
    resizeTimer = setTimeout(drawLbChart, 200)
  }
  window.addEventListener('resize', resizeHandler)
  document.addEventListener('visibilitychange', onVisibilityChange)
})

onUnmounted(() => {
  document.removeEventListener('visibilitychange', onVisibilityChange)
  if (resizeHandler) {
    window.removeEventListener('resize', resizeHandler)
    resizeHandler = null
  }
})
</script>

<style scoped>
.lb-page {
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
.chart-placeholder {
  display: flex;
  align-items: center;
  justify-content: center;
  height: 180px;
  color: var(--gray-400);
  font-size: var(--font-size-sm);
}
.td-center {
  text-align: center;
  padding: 20px;
}

/* KPI Strip */
.lb-kpi-strip {
  display: flex;
  align-items: center;
  background: #fff;
  border-radius: var(--border-radius-lg);
  border: 1px solid var(--gray-200);
  padding: 20px 24px;
  gap: 0;
  box-shadow: var(--shadow-sm);
  overflow-x: auto;
}
.lb-kpi-item {
  flex: 1;
  min-width: 120px;
  text-align: center;
}
.lb-kpi-label {
  font-size: var(--font-size-xs);
  color: var(--gray-400);
  margin-bottom: 4px;
  white-space: nowrap;
}
.lb-kpi-value {
  font-size: 24px;
  font-weight: 700;
  line-height: 1.2;
  min-height: 1.2em;
}
.lb-kpi-bar {
  height: 4px;
  background: var(--gray-100);
  border-radius: 2px;
  margin-top: 6px;
  overflow: hidden;
}
.lb-kpi-fill {
  height: 100%;
  border-radius: 2px;
  transition: width 0.3s;
}
.lb-kpi-hint {
  font-size: 11px;
  color: var(--gray-400);
  margin-top: 4px;
}
.lb-kpi-divider {
  width: 1px;
  height: 48px;
  background: var(--gray-200);
  margin: 0 16px;
  flex-shrink: 0;
}

.val-success {
  color: var(--success);
}
.val-warning {
  color: var(--warning);
}
.val-danger {
  color: var(--danger);
}
.val-primary {
  color: var(--primary);
}
.val-info {
  color: var(--info, #0ea5e9);
}
.fill-success {
  background: var(--success);
}
.fill-warning {
  background: var(--warning);
}

/* Charts */
.lb-charts {
  display: flex;
  gap: 16px;
}
.lb-bar-card {
  flex: 1;
  min-width: 0;
  padding: 20px;
}
.whatif-card {
  width: 300px;
  flex-shrink: 0;
  padding: 20px;
}

.card-header-inner {
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

canvas {
  width: 100% !important;
}

/* What-If */
.whatif-list {
  display: flex;
  flex-direction: column;
  gap: 10px;
  margin-bottom: 14px;
}
.whatif-row {
  display: flex;
  align-items: center;
  gap: 8px;
}
.whatif-name {
  width: 50px;
  font-size: var(--font-size-xs);
  color: var(--gray-600);
  flex-shrink: 0;
}
.whatif-slider {
  flex: 1;
  accent-color: var(--primary);
}
.whatif-val {
  width: 30px;
  font-size: var(--font-size-xs);
  font-weight: 600;
  color: var(--gray-700);
  text-align: right;
}
.whatif-result {
  padding: 10px 12px;
  background: var(--gray-50);
  border-radius: 6px;
  font-size: var(--font-size-sm);
  color: var(--gray-600);
}
.whatif-result strong {
  font-size: 15px;
}

/* Bottom */
.lb-bottom {
  display: flex;
  gap: 16px;
}
.causal-card {
  flex: 1;
  min-width: 0;
  padding: 0;
  overflow: hidden;
}
.ecrs-card {
  flex: 1.2;
  min-width: 0;
  padding: 0;
  overflow: hidden;
}
.causal-card .card-header-inner,
.ecrs-card .card-header-inner {
  padding: 16px 20px;
  border-bottom: 1px solid var(--gray-100);
}

.causal-list {
  padding: 12px 16px;
  display: flex;
  flex-direction: column;
  gap: 14px;
}
.causal-item {
  border: 1px solid var(--gray-200);
  border-radius: 8px;
  padding: 12px;
}
.causal-station {
  font-size: var(--font-size-sm);
  font-weight: 600;
  color: var(--gray-800);
  margin-bottom: 10px;
}
.causal-flow {
  display: flex;
  align-items: flex-start;
  gap: 8px;
}
.causal-cond,
.causal-cause,
.causal-action {
  flex: 1;
  background: var(--gray-50);
  border-radius: 6px;
  padding: 8px;
}
.causal-cond-label {
  font-size: 10px;
  font-weight: 700;
  text-transform: uppercase;
  letter-spacing: 0.05em;
  color: var(--gray-400);
  margin-bottom: 4px;
}
.causal-cond-content {
  font-size: var(--font-size-xs);
  color: var(--gray-700);
  line-height: 1.5;
}
.causal-arrow {
  display: flex;
  align-items: center;
  color: var(--gray-300);
  flex-shrink: 0;
  padding-top: 20px;
}
.causal-impact {
  margin-top: 8px;
  font-size: var(--font-size-xs);
  color: var(--gray-500);
}
.causal-impact strong {
  color: var(--success);
}

/* ECRS */
.ecrs-tag {
  font-size: 11px;
  font-weight: 700;
  padding: 2px 8px;
  border-radius: 4px;
}
.ecrs-eliminate {
  background: #fee2e2;
  color: #ef4444;
}
.ecrs-combine {
  background: #e0e7ff;
  color: #6366f1;
}
.ecrs-rearrange {
  background: #fef3c7;
  color: #f59e0b;
}
.ecrs-simplify {
  background: #d1fae5;
  color: #10b981;
}

.station-tag {
  font-size: 11px;
  padding: 2px 7px;
  background: var(--primary-bg);
  color: var(--primary);
  border-radius: 4px;
  font-weight: 600;
}

.difficulty-dots {
  display: flex;
  gap: 3px;
}
.dot {
  width: 8px;
  height: 8px;
  border-radius: 50%;
  background: var(--gray-200);
}
.dot-filled {
  background: var(--primary);
}

.spinner-sm {
  display: inline-block;
  width: 14px;
  height: 14px;
  border: 2px solid rgba(255,255,255,0.3);
  border-top-color: #fff;
  border-radius: 50%;
  animation: spin 0.6s linear infinite;
}
@keyframes spin {
  to { transform: rotate(360deg); }
}

.font-bold {
  font-weight: 700;
}
.text-success {
  color: var(--success);
}

.btn-outline {
  border: 1px solid var(--gray-300);
  background: transparent;
  color: var(--gray-700);
}
.btn-outline:hover {
  background: var(--gray-50);
}

/* Line Layout Visualization */
.layout-card {
  padding: 20px;
  overflow: visible;
}
.layout-container {
  position: relative;
  overflow: visible;
}
.layout-svg {
  width: 100%;
  height: auto;
  display: block;
}
.station-block {
  cursor: pointer;
}
.station-rect {
  transition: opacity 0.2s, transform 0.2s;
}
.station-block:hover .station-rect {
  opacity: 0.85;
}
.layout-tooltip {
  position: absolute;
  background: #1f2937;
  color: #f9fafb;
  padding: 10px 14px;
  border-radius: 8px;
  font-size: 12px;
  line-height: 1.6;
  pointer-events: none;
  z-index: 10;
  white-space: nowrap;
  box-shadow: 0 4px 12px rgba(0, 0, 0, 0.15);
  transform: translateY(-100%);
}
.tooltip-title {
  font-weight: 700;
  font-size: 13px;
  margin-bottom: 4px;
}
.tooltip-row {
  display: flex;
  justify-content: space-between;
  gap: 12px;
}
.tooltip-label {
  color: #9ca3af;
}
.tooltip-value {
  font-weight: 600;
}

@media (max-width: 1100px) {
  .lb-charts {
    flex-direction: column;
  }
  .whatif-card {
    width: 100%;
  }
  .lb-bottom {
    flex-direction: column;
  }
  .causal-flow {
    flex-direction: column;
  }
  .causal-arrow {
    transform: rotate(90deg);
    padding: 0;
    align-self: center;
  }
}
@media (max-width: 700px) {
  .lb-kpi-strip {
    flex-wrap: wrap;
  }
  .lb-kpi-divider {
    display: none;
  }
}
</style>
