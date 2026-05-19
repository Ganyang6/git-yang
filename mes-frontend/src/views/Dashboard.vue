<template>
  <div class="dashboard">
    <!-- Page Header -->
    <div class="page-header">
      <div>
        <div class="page-title">生产工时看板</div>
        <div class="page-subtitle">
          实时工时测定数据
          <span v-if="lastUpdate"> · 最后更新：{{ lastUpdate }}</span>
          <span
            v-if="wsConnected"
            class="ws-indicator ws-connected"
            title="WebSocket connected - real-time updates active"
          >LIVE</span>
          <span
            v-else
            class="ws-indicator ws-disconnected"
            title="WebSocket disconnected - using polling"
          >OFFLINE</span>
        </div>
      </div>
      <div class="flex gap-2 items-center">
        <select v-model="dateRange" class="select" style="width: 140px" @change="loadAll">
          <option value="today">今日</option>
          <option value="week">本周</option>
          <option value="month">本月</option>
        </select>
        <button class="btn btn-primary btn-sm" :disabled="loading" @click="loadAll">
          <svg
            width="14"
            height="14"
            viewBox="0 0 24 24"
            fill="none"
            stroke="currentColor"
            stroke-width="2.5"
            :class="{ spin: loading }"
          >
            <path d="M23 4v6h-6" />
            <path d="M1 20v-6h6" />
            <path d="M3.51 9a9 9 0 0 1 14.85-3.36L23 10M1 14l4.64 4.36A9 9 0 0 0 20.49 15" />
          </svg>
          {{ loading ? '加载中...' : '刷新数据' }}
        </button>
      </div>
    </div>

    <!-- 全局错误提示 -->
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
      <span class="error-hint">请确认后端服务已启动（{{ apiBase }}）</span>
    </div>

    <!-- KPI Cards -->
    <div class="kpi-grid">
      <div
        v-for="kpi in kpiCards"
        :key="kpi.key"
        class="kpi-card card"
        :style="`--accent: ${kpi.color}`"
      >
        <div class="kpi-header">
          <div
            class="kpi-icon"
            :style="`background: ${kpi.color}15; color: ${kpi.color}`"
          >
            <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" v-html="kpi.iconSvg"></svg>
          </div>
          <template v-if="kpi.trend !== null">
            <div class="kpi-trend" :class="kpi.trendUp ? 'trend-up' : 'trend-down'">
              <svg
                v-if="kpi.trendUp"
                width="12"
                height="12"
                viewBox="0 0 24 24"
                fill="none"
                stroke="currentColor"
                stroke-width="2.5"
              >
                <polyline points="18 15 12 9 6 15" />
              </svg>
              <svg
                v-else
                width="12"
                height="12"
                viewBox="0 0 24 24"
                fill="none"
                stroke="currentColor"
                stroke-width="2.5"
              >
                <polyline points="6 9 12 15 18 9" />
              </svg>
              {{ Math.abs(kpi.trend) }}%
            </div>
          </template>
        </div>
        <div class="kpi-value">
          <span v-if="loading" class="skeleton-text"></span>
          <span v-else-if="kpi.value !== null">{{ kpi.value }}</span>
          <span v-else class="no-data">--</span>
        </div>
        <div class="kpi-label">{{ kpi.label }}</div>
        <div class="kpi-footer">
          <span>{{ kpi.compareLabel }}</span>
          <div class="progress progress-primary" style="flex: 1; margin: 0 8px">
            <div
              class="progress-bar"
              :style="`width: ${kpi.progress !== null ? kpi.progress : 0}%`"
            ></div>
          </div>
          <span>{{ kpi.progress !== null ? kpi.progress + '%' : '--' }}</span>
        </div>
      </div>
    </div>

    <!-- Anomaly Alert Card -->
    <div v-if="anomalyEvents.length" class="card anomaly-banner">
      <div class="anomaly-header">
        <div class="anomaly-title">
          <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
            <path d="M10.29 3.86L1.82 18a2 2 0 0 0 1.71 3h16.94a2 2 0 0 0 1.71-3L13.71 3.86a2 2 0 0 0-3.42 0z"/>
            <line x1="12" y1="9" x2="12" y2="13"/>
            <line x1="12" y1="17" x2="12.01" y2="17"/>
          </svg>
          异常告警
          <span class="badge badge-danger">{{ anomalyEvents.length }}</span>
        </div>
        <button class="btn btn-ghost btn-xs" @click="dismissAnomalies">全部忽略</button>
      </div>
      <div class="anomaly-list">
        <div v-for="(ev, idx) in anomalyEvents.slice(0, 5)" :key="ev.id || idx" class="anomaly-item">
          <div class="anomaly-meta">
            <span class="anomaly-station">{{ ev.station_id || ev.station || '--' }}</span>
            <span class="anomaly-type">{{ ev.action || ev.type || '异常' }}</span>
            <span class="anomaly-time">{{ formatAnomalyTime(ev) }}</span>
          </div>
          <div class="anomaly-desc">{{ ev.description || ev.message || ev.reason || '检测到异常行为' }}</div>
        </div>
        <div v-if="anomalyEvents.length > 5" class="anomaly-more">
          还有 {{ anomalyEvents.length - 5 }} 条异常事件
        </div>
      </div>
    </div>

    <!-- Charts Row -->
    <div class="charts-row">
      <!-- 生产线平衡率山积图 -->
      <div class="card chart-card chart-gauge">
        <div class="chart-header">
          <div>
            <div class="chart-title">生产线平衡率</div>
            <div class="chart-subtitle">各工位工时负荷分布</div>
          </div>
          <template v-if="balanceSummary">
            <span
              class="badge"
              :class="
                balanceSummary.balanceRate >= 85
                  ? 'badge-success'
                  : balanceSummary.balanceRate >= 70
                    ? 'badge-warning'
                    : 'badge-danger'
              "
            >
              {{
                balanceSummary.balanceRate >= 85
                  ? '优秀'
                  : balanceSummary.balanceRate >= 70
                    ? '一般'
                    : '需改善'
              }}
            </span>
          </template>
        </div>
        <div class="chart-body gauge-body">
          <div v-if="loading" class="chart-placeholder">加载中...</div>
          <div v-else-if="!balanceSummary" class="chart-placeholder no-data-placeholder">
            暂无数据<br />请连接后端服务
          </div>
          <canvas v-else ref="balanceChart" height="180"></canvas>
        </div>
        <div class="gauge-footer">
          <div class="gauge-stat">
            <div class="gauge-stat-value" style="color: #1a6ef5">
              {{ balanceSummary ? balanceSummary.balanceRate + '%' : '--' }}
            </div>
            <div class="gauge-stat-label">平衡率</div>
          </div>
          <div class="gauge-divider"></div>
          <div class="gauge-stat">
            <div class="gauge-stat-value" style="color: #ef4444">
              {{ balanceSummary ? balanceSummary.bottleneckStation : '--' }}
            </div>
            <div class="gauge-stat-label">瓶颈工位</div>
          </div>
          <div class="gauge-divider"></div>
          <div class="gauge-stat">
            <div class="gauge-stat-value" style="color: #10b981">
              {{ balanceSummary ? balanceSummary.smoothIndex : '--' }}
            </div>
            <div class="gauge-stat-label">平滑指数</div>
          </div>
        </div>
      </div>

      <!-- 工时趋势 -->
      <div class="card chart-card chart-main">
        <div class="chart-header">
          <div>
            <div class="chart-title">标准工时 vs 实际工时</div>
            <div class="chart-subtitle">近7日趋势对比（秒/件）</div>
          </div>
          <div class="chart-legend">
            <span class="legend-item"
              ><i class="legend-dot" style="background: #1a6ef5"></i>实际工时</span
            >
            <span class="legend-item"
              ><i class="legend-dot legend-dot-dash" style="background: #f59e0b"></i>标准工时</span
            >
          </div>
        </div>
        <div class="chart-body">
          <div v-if="loading" class="chart-placeholder">加载中...</div>
          <div v-else-if="!worktimeTrend" class="chart-placeholder no-data-placeholder">
            暂无数据
          </div>
          <canvas v-else ref="worktimeChart" height="180"></canvas>
        </div>
      </div>
    </div>

    <!-- 人机时间线 + 动素分布 -->
    <div class="charts-row">
      <!-- 人机时间线 -->
      <div class="card chart-card" style="flex: 1.4; min-width: 0">
        <div class="chart-header">
          <div>
            <div class="chart-title">人机协作时间线</div>
            <div class="chart-subtitle">当前班次 · 各工位人工/设备时间分配</div>
          </div>
          <router-link to="/line-balance" class="btn btn-ghost btn-sm">详细分析</router-link>
        </div>
        <div class="timeline-container">
          <template v-if="loading">
            <div v-for="i in 4" :key="i" class="timeline-row">
              <div class="timeline-label skeleton-text" style="width: 40px; height: 12px"></div>
              <div class="timeline-bar-wrap"><div class="skeleton-bar"></div></div>
              <div style="width: 60px"></div>
            </div>
          </template>
          <template v-else-if="stationTimeline && stationTimeline.length">
            <div v-for="station in stationTimeline" :key="station.id" class="timeline-row">
              <div class="timeline-label">{{ station.name }}</div>
              <div class="timeline-bar-wrap">
                <div
                  v-for="seg in station.segments"
                  :key="seg.type"
                  class="timeline-seg"
                  :class="`seg-${seg.type}`"
                  :style="`width:${seg.pct}%`"
                  :title="`${seg.label}: ${seg.time}s`"
                ></div>
              </div>
              <div class="timeline-oee">OEE {{ station.oee }}%</div>
            </div>
          </template>
          <div v-else class="chart-placeholder no-data-placeholder" style="height: 80px">
            暂无时间线数据
          </div>
          <div class="timeline-legend">
            <span class="tl-item seg-work">有效作业</span>
            <span class="tl-item seg-wait">等待</span>
            <span class="tl-item seg-machine">设备运行</span>
            <span class="tl-item seg-idle">空闲</span>
          </div>
        </div>
      </div>

      <!-- 动素分布饼图 -->
      <div class="card chart-card" style="width: 240px; flex-shrink: 0">
        <div class="chart-header">
          <div>
            <div class="chart-title">动素时间分布</div>
            <div class="chart-subtitle">Therblig 动素占比</div>
          </div>
        </div>
        <div class="chart-body" style="display: flex; align-items: center; justify-content: center">
          <div v-if="loading" class="chart-placeholder" style="height: 180px">加载中...</div>
          <div
            v-else-if="!thermData || !thermData.length"
            class="chart-placeholder no-data-placeholder"
            style="height: 180px"
          >
            暂无数据
          </div>
          <canvas v-else ref="thermChart" width="180" height="180"></canvas>
        </div>
        <div v-if="thermData && thermData.length" class="therm-legend">
          <div v-for="item in thermData" :key="item.label" class="therm-legend-item">
            <div class="therm-dot" :style="`background:${item.color}`"></div>
            <span class="therm-label">{{ item.label }}</span>
            <span class="therm-value">{{ item.pct }}%</span>
          </div>
        </div>
      </div>
    </div>

    <!-- Bottom Row: 最新工序记录 + 瓶颈诊断 -->
    <div class="bottom-row">
      <!-- 最新工序记录 -->
      <div class="card bottom-card">
        <div class="card-header">
          <div class="chart-title">最新工序工时记录</div>
          <router-link to="/worktime" class="btn btn-ghost btn-sm">查看全部</router-link>
        </div>
        <div class="table-wrapper">
          <table class="table">
            <thead>
              <tr>
                <th>工序编号</th>
                <th>工序名称</th>
                <th>工位</th>
                <th>实际工时</th>
                <th>标准工时</th>
                <th>效率</th>
                <th>状态</th>
              </tr>
            </thead>
            <tbody>
              <tr v-if="loading">
                <td colspan="7" class="td-center">
                  <span
                    class="skeleton-text"
                    style="width: 200px; height: 14px; display: inline-block"
                  ></span>
                </td>
              </tr>
              <tr v-else-if="!recentWorktime || !recentWorktime.length">
                <td colspan="7" class="td-center no-data">暂无工序数据 — 请连接后端服务后刷新</td>
              </tr>
              <tr v-for="rec in recentWorktime" :key="rec.id">
                <td>
                  <span class="order-id">{{ rec.id }}</span>
                </td>
                <td>{{ rec.operation }}</td>
                <td>{{ rec.station }}</td>
                <td>{{ rec.actual }}s</td>
                <td>{{ rec.standard }}s</td>
                <td>
                  <div class="flex items-center gap-2">
                    <div class="progress progress-primary" style="width: 60px">
                      <div
                        class="progress-bar"
                        :class="rec.efficiency >= 100 ? 'bar-danger' : ''"
                        :style="`width:${Math.min(rec.efficiency, 100)}%`"
                      ></div>
                    </div>
                    <span
                      class="text-xs"
                      :style="`color:${rec.efficiency > 100 ? 'var(--danger)' : rec.efficiency >= 90 ? 'var(--success)' : 'var(--warning)'}`"
                    >
                      {{ rec.efficiency }}%
                    </span>
                  </div>
                </td>
                <td>
                  <span
                    class="badge"
                    :class="
                      rec.efficiency >= 90 && rec.efficiency <= 110
                        ? 'badge-success'
                        : rec.efficiency > 110
                          ? 'badge-danger'
                          : 'badge-warning'
                    "
                  >
                    {{
                      rec.efficiency >= 90 && rec.efficiency <= 110
                        ? '正常'
                        : rec.efficiency > 110
                          ? '较快'
                          : '超时'
                    }}
                  </span>
                </td>
              </tr>
            </tbody>
          </table>
        </div>
      </div>

      <!-- 瓶颈诊断卡 -->
      <div class="card bottom-card" style="min-width: 300px; max-width: 340px; flex-shrink: 0">
        <div class="card-header">
          <div class="chart-title">瓶颈诊断</div>
          <router-link to="/line-balance" class="btn btn-ghost btn-sm">ECRS建议</router-link>
        </div>
        <div class="bottleneck-list">
          <div v-if="loading" class="no-data" style="padding: 20px 0; text-align: center">
            加载中...
          </div>
          <div
            v-else-if="!bottleneckDiag || !bottleneckDiag.length"
            class="no-data"
            style="padding: 20px 0; text-align: center"
          >
            暂无诊断数据
          </div>
          <div v-for="item in bottleneckDiag" :key="item.station" class="bottleneck-item">
            <div class="bottleneck-header">
              <div class="bn-station">{{ item.station }}</div>
              <div class="bn-tag" :class="`bn-${item.level}`">{{ item.levelLabel }}</div>
            </div>
            <div class="bn-reason">
              <svg
                width="13"
                height="13"
                viewBox="0 0 24 24"
                fill="none"
                stroke="currentColor"
                stroke-width="2"
              >
                <circle cx="12" cy="12" r="10" />
                <line x1="12" y1="8" x2="12" y2="12" />
                <line x1="12" y1="16" x2="12.01" y2="16" />
              </svg>
              {{ item.reason }}
            </div>
            <div class="bn-suggest">
              <svg
                width="13"
                height="13"
                viewBox="0 0 24 24"
                fill="none"
                stroke="currentColor"
                stroke-width="2"
              >
                <polyline points="9 11 12 14 22 4" />
                <path d="M21 12v7a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h11" />
              </svg>
              {{ item.suggest }}
            </div>
          </div>
        </div>
      </div>
    </div>
  </div>
</template>

<script setup>
import { ref, computed, onMounted, onUnmounted, watch, nextTick } from 'vue'
import DOMPurify from 'dompurify'
import {
  fetchDashboardKpi,
  fetchLineBalanceSummary,
  fetchWorktimeTrend,
  fetchStationTimeline,
  fetchTherbligDistribution,
  fetchRecentWorktime,
  fetchBottleneckDiagnosis,
  fetchAnomalyEvents
} from '../api/index.js'
import { useWebSocket } from '../composables/useWebSocket.js'
import { useSSE } from '../composables/useSSE.js'
import {
  drawBalanceChart,
  drawWorktimeChart,
  drawThermChart
} from '../composables/useDashboardCharts.js'

const dateRange = ref('today')
const lastUpdate = ref('')
const loading = ref(false)
const errorMsg = ref('')
const wsConnected = ref(false)
const apiBase = import.meta.env.VITE_API_BASE || 'http://localhost:8000'

// chart refs
const balanceChart = ref(null)
const worktimeChart = ref(null)
const thermChart = ref(null)
let resizeHandler = null

// ─── Data State ───────────────────────────────────────────────────────────────
const kpiRaw = ref(null)
const balanceSummary = ref(null)
const worktimeTrend = ref(null)
const wsMetrics = ref({}) // P1-4: Separate data source for WebSocket real-time metrics
const stationTimeline = ref(null)
const thermData = ref(null)
const recentWorktime = ref(null)
const bottleneckDiag = ref(null)
const anomalyEvents = ref([])

// ─── KPI Cards（从 API 数据派生） ─────────────────────────────────────────────
const KPI_ICONS = {
  utilization: '<path d="M17 21v-2a4 4 0 0 0-4-4H5a4 4 0 0 0-4 4v2"/><circle cx="9" cy="7" r="4"/><path d="M23 21v-2a4 4 0 0 0-3-3.87"/><path d="M16 3.13a4 4 0 0 1 0 7.75"/>',
  stdtime: '<circle cx="12" cy="12" r="10"/><polyline points="12 6 12 12 16 14"/>',
  balance: '<line x1="18" y1="20" x2="18" y2="10"/><line x1="12" y1="20" x2="12" y2="4"/><line x1="6" y1="20" x2="6" y2="14"/>',
  waitloss: '<path d="M10.29 3.86L1.82 18a2 2 0 0 0 1.71 3h16.94a2 2 0 0 0 1.71-3L13.71 3.86a2 2 0 0 0-3.42 0z"/><line x1="12" y1="9" x2="12" y2="13"/><line x1="12" y1="17" x2="12.01" y2="17"/>'
}

// Sanitize KPI SVG icons (P0-5: v-html XSS prevention)
const SANITIZED_ICONS = Object.fromEntries(
  Object.entries(KPI_ICONS).map(([k, v]) => [k, DOMPurify.sanitize(v)])
)

const kpiCards = computed(() => {
  const d = kpiRaw.value
  return [
    {
      key: 'utilization',
      label: '人工稼动率',
      value: d ? d.utilization + '%' : null,
      trend: d?.trends?.utilization ?? null,
      trendUp: d?.trends ? d.trends.utilization > 0 : false,
      progress: d ? Math.round(d.utilization) : null,
      compareLabel: '较上班次',
      color: '#1a6ef5',
      iconSvg: SANITIZED_ICONS.utilization
    },
    {
      key: 'stdtime',
      label: '标准工时达成率',
      value: d ? d.stdtimeAchievement + '%' : null,
      trend: d?.trends?.stdtimeAchievement ?? null,
      trendUp: d?.trends ? d.trends.stdtimeAchievement > 0 : false,
      progress: d ? Math.round(d.stdtimeAchievement) : null,
      compareLabel: '较目标',
      color: '#10b981',
      iconSvg: SANITIZED_ICONS.stdtime
    },
    {
      key: 'balance',
      label: '生产线平衡率',
      value: d ? d.balanceRate + '%' : null,
      trend: d?.trends?.balanceRate ?? null,
      trendUp: d?.trends ? d.trends.balanceRate > 0 : false,
      progress: d ? Math.round(d.balanceRate) : null,
      compareLabel: '较昨日',
      color: '#6366f1',
      iconSvg: SANITIZED_ICONS.balance
    },
    {
      key: 'waitloss',
      label: '等待损失时间',
      value: d ? d.waitLossMinutes + 'min' : null,
      trend: d?.trends?.waitLossMinutes ?? null,
      trendUp: d?.trends ? d.trends.waitLossMinutes < 0 : false,
      progress: d ? Math.round((d.waitLossMinutes / 60) * 100) : null,
      compareLabel: '等待占比',
      color: '#ef4444',
      iconSvg: SANITIZED_ICONS.waitloss
    }
  ]
})

// ─── Data Loading ─────────────────────────────────────────────────────────────
async function loadAll() {
  loading.value = true
  errorMsg.value = ''
  try {
    const results = await Promise.allSettled([
      fetchDashboardKpi(dateRange.value),
      fetchLineBalanceSummary(),
      fetchWorktimeTrend(7),
      fetchStationTimeline(),
      fetchTherbligDistribution(),
      fetchRecentWorktime(8),
      fetchBottleneckDiagnosis(),
      fetchAnomalyEvents({ limit: 10 })
    ])

    const [kpi, balance, trend, timeline, therm, recent, bottleneck, anomaly] = results

    if (kpi.status === 'fulfilled') kpiRaw.value = kpi.value
    if (balance.status === 'fulfilled') balanceSummary.value = balance.value
    if (trend.status === 'fulfilled') worktimeTrend.value = trend.value
    if (timeline.status === 'fulfilled') stationTimeline.value = timeline.value
    if (therm.status === 'fulfilled') thermData.value = therm.value
    if (recent.status === 'fulfilled') recentWorktime.value = recent.value
    if (bottleneck.status === 'fulfilled') bottleneckDiag.value = bottleneck.value
    if (anomaly.status === 'fulfilled') {
      const data = anomaly.value
      anomalyEvents.value = Array.isArray(data) ? data : (data.events || [])
    }

  const failCount = results.filter(r => r.status === 'rejected').length
  if (failCount === results.length) {
    errorMsg.value = '无法连接后端服务，所有数据请求失败'
  } else if (failCount > 0) {
    errorMsg.value = `${failCount} 个接口请求失败，部分数据未加载`
  }

  const now = new Date()
  lastUpdate.value = now.toLocaleTimeString('zh-CN', {
    hour: '2-digit',
    minute: '2-digit',
    second: '2-digit'
  })
  loading.value = false

  await nextTick()
  // P2-1: drawCharts is also triggered by watch below, but call it here for initial render
  // when watchers haven't fired yet
  drawCharts()
  } catch {
    errorMsg.value = '数据加载出现异常'
    loading.value = false
  }
}

// ─── Anomaly Helpers ─────────────────────────────────────────────────────────
function formatAnomalyTime(ev) {
  const ts = ev.timestamp || ev.detected_at || ev.created_at
  if (!ts) return ''
  const d = new Date(ts)
  if (isNaN(d.getTime())) return String(ts)
  return d.toLocaleTimeString('zh-CN', { hour: '2-digit', minute: '2-digit', second: '2-digit' })
}

function dismissAnomalies() {
  anomalyEvents.value = []
}

// ─── Chart Drawing ────────────────────────────────────────────────────────────
// P2 #79: Chart drawing functions extracted to composables/useDashboardCharts.js

function drawCharts() {
  setTimeout(() => {
    drawBalanceChart(balanceChart.value, balanceSummary.value)
    drawWorktimeChart(worktimeChart.value, worktimeTrend.value)
    drawThermChart(thermChart.value, thermData.value)
  }, 50)
}

onMounted(() => {
  loadAll()
  let _resizeTimer = null
  resizeHandler = () => {
    if (_resizeTimer) clearTimeout(_resizeTimer)
    _resizeTimer = setTimeout(() => {
      drawBalanceChart(balanceChart.value, balanceSummary.value)
      drawWorktimeChart(worktimeChart.value, worktimeTrend.value)
    }, 200)
  }
  window.addEventListener('resize', resizeHandler)
})

onUnmounted(() => {
  if (resizeHandler) {
    window.removeEventListener('resize', resizeHandler)
    resizeHandler = null
  }
})

watch([balanceSummary, worktimeTrend, thermData], () => {
  nextTick(drawCharts)
})

// ─── Real-time WebSocket Integration ──────────────────────────────────────────
const {
  isConnected: wsIsConnected,
} = useWebSocket({
  url: '/ws/metrics',
  subscribe: 'metrics',
  autoConnect: true,
  onMessage: onWsMessage
})

// Sync ws connection state for display
watch(wsIsConnected, (val) => {
  wsConnected.value = val
})

function onWsMessage(data) {
  if (!data || !data.type) return

  // Handle metrics updates from WebSocket (mes:metrics stream via backend)
  if (data.type === 'metrics') {
    const metrics = data.data || data

    // Update KPI cards with real-time data
    if (kpiRaw.value && metrics) {
      kpiRaw.value = {
        ...kpiRaw.value,
        utilization: metrics.human_utilization != null
          ? Math.round(metrics.human_utilization * 100)
          : kpiRaw.value.utilization,
        stdtimeAchievement: metrics.stdtime_achievement != null
          ? Math.round(metrics.stdtime_achievement * 100)
          : kpiRaw.value.stdtimeAchievement,
        balanceRate: metrics.line_balance_rate != null
          ? Math.round(metrics.line_balance_rate * 100)
          : kpiRaw.value.balanceRate,
        waitLossMinutes: metrics.wait_ratio != null && metrics.shift_total_seconds
          ? Math.round(metrics.wait_ratio * metrics.shift_total_seconds / 60)
          : kpiRaw.value.waitLossMinutes
      }
    }

    // P1-4: Store real-time metrics in dedicated wsMetrics, NOT in worktimeTrend.
    // worktimeTrend is for actual/standard worktime (seconds) from /api/worktime/trend.
    // Mixing human_utilization (0-100%) into trend.utilization corrupts Y-axis scale.
    if (metrics.human_utilization != null || metrics.oee != null) {
      wsMetrics.value = {
        ...wsMetrics.value,
        human_utilization: metrics.human_utilization != null
          ? Math.round(metrics.human_utilization * 100)
          : wsMetrics.value.human_utilization,
        oee: metrics.oee != null
          ? Math.round(metrics.oee * 100)
          : wsMetrics.value.oee
      }
    }

    // Update lastUpdate timestamp
    const now = new Date()
    lastUpdate.value = now.toLocaleTimeString('zh-CN', {
      hour: '2-digit',
      minute: '2-digit',
      second: '2-digit'
    })
  }
}

// ─── SSE Event Integration (Alerts) ──────────────────────────────────────────
useSSE({
  url: '/sse/events',
  autoConnect: true,
  onEvent: onSseEvent
})

function onSseEvent(event) {
  if (!event || !event.data) return

  // Dispatch custom events for AppToast to pick up (AppToast is mounted in App.vue)
  if (event.type === 'alert') {
    const d = event.data
    const level = d.level || 'info'
    const title = d.title || 'System Alert'
    const message = d.message || 'An alert was received'
    window.dispatchEvent(
      new CustomEvent('mes:toast', {
        detail: { level, title, message }
      })
    )
  } else if (event.type === 'equipment_status_change') {
    const d = event.data
    window.dispatchEvent(
      new CustomEvent('mes:toast', {
        detail: {
          level: 'warning',
          title: 'Equipment Status Change',
          message: `${d.equipment || 'Equipment'} is now ${d.status || 'unknown'}`
        }
      })
    )
  } else if (event.type === 'analysis_complete') {
    const d = event.data
    window.dispatchEvent(
      new CustomEvent('mes:toast', {
        detail: {
          level: 'success',
          title: 'Analysis Complete',
          message: d.summary || 'AI analysis has finished'
        }
      })
    )
  } else if (event.type === 'anomaly_detected') {
    const d = event.data
    anomalyEvents.value = [d, ...anomalyEvents.value].slice(0, 20)
    window.dispatchEvent(
      new CustomEvent('mes:toast', {
        detail: {
          level: 'warning',
          title: 'Anomaly Detected',
          message: `${d.station_id || d.station || 'Unknown'}: ${d.description || d.message || 'Abnormal behavior detected'}`
        }
      })
    )
  }
}
</script>

<style scoped>
.dashboard {
  display: flex;
  flex-direction: column;
  gap: 20px;
}

/* Error Banner */
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
.error-hint {
  color: #9ca3af;
  font-size: var(--font-size-xs);
  margin-left: 4px;
}

/* WebSocket Connection Indicator */
.ws-indicator {
  display: inline-flex;
  align-items: center;
  gap: 4px;
  font-size: 10px;
  font-weight: 700;
  letter-spacing: 0.5px;
  padding: 2px 8px;
  border-radius: 10px;
  margin-left: 8px;
  vertical-align: middle;
}
.ws-connected {
  background: rgba(16, 185, 129, 0.12);
  color: #059669;
}
.ws-connected::before {
  content: '';
  display: inline-block;
  width: 6px;
  height: 6px;
  border-radius: 50%;
  background: #10b981;
  animation: ws-pulse 2s infinite;
}
.ws-disconnected {
  background: rgba(107, 114, 128, 0.12);
  color: #6b7280;
}
@keyframes ws-pulse {
  0%, 100% { opacity: 1; }
  50% { opacity: 0.4; }
}

/* Skeleton */
.skeleton-text {
  display: inline-block;
  background: linear-gradient(90deg, #e5e7eb 25%, #f3f4f6 50%, #e5e7eb 75%);
  background-size: 200% 100%;
  animation: shimmer 1.4s infinite;
  border-radius: 4px;
  height: 1em;
  vertical-align: middle;
}
.skeleton-bar {
  height: 100%;
  width: 100%;
  background: linear-gradient(90deg, #e5e7eb 25%, #f3f4f6 50%, #e5e7eb 75%);
  background-size: 200% 100%;
  animation: shimmer 1.4s infinite;
}
@keyframes shimmer {
  0% {
    background-position: 200% 0;
  }
  100% {
    background-position: -200% 0;
  }
}

/* No Data */
.no-data {
  color: var(--gray-400);
  font-size: var(--font-size-sm);
}
.chart-placeholder {
  display: flex;
  align-items: center;
  justify-content: center;
  width: 100%;
  height: 180px;
  color: var(--gray-400);
  font-size: var(--font-size-sm);
}
.no-data-placeholder {
  flex-direction: column;
  gap: 4px;
  font-size: var(--font-size-sm);
  color: var(--gray-400);
  text-align: center;
}
.td-center {
  text-align: center;
  padding: 20px;
}

/* Spin */
.spin {
  animation: spin 1s linear infinite;
}
@keyframes spin {
  from {
    transform: rotate(0deg);
  }
  to {
    transform: rotate(360deg);
  }
}

/* KPI Grid */
.kpi-grid {
  display: grid;
  grid-template-columns: repeat(4, 1fr);
  gap: 16px;
}
.kpi-card {
  padding: 20px;
  position: relative;
  overflow: hidden;
  transition: var(--transition-fast);
  border-top: 3px solid var(--accent);
}
.kpi-card:hover {
  box-shadow: var(--shadow);
  transform: translateY(-2px);
}
.kpi-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  margin-bottom: 12px;
}
.kpi-icon {
  width: 40px;
  height: 40px;
  border-radius: 10px;
  display: flex;
  align-items: center;
  justify-content: center;
}
.kpi-trend {
  display: flex;
  align-items: center;
  gap: 2px;
  font-size: var(--font-size-xs);
  font-weight: 600;
  padding: 3px 8px;
  border-radius: 20px;
}
.trend-up {
  color: var(--success);
  background: var(--success-bg);
}
.trend-down {
  color: var(--danger);
  background: var(--danger-bg);
}
.kpi-value {
  font-size: var(--font-size-3xl);
  font-weight: 700;
  color: var(--gray-900);
  line-height: 1;
  margin-bottom: 4px;
  min-height: 1.2em;
}
.kpi-label {
  font-size: var(--font-size-sm);
  color: var(--gray-500);
  margin-bottom: 14px;
}
.kpi-footer {
  display: flex;
  align-items: center;
  gap: 6px;
  font-size: var(--font-size-xs);
  color: var(--gray-400);
}

/* Charts */
.charts-row {
  display: flex;
  gap: 16px;
}
.chart-main {
  flex: 1;
  min-width: 0;
}
.chart-gauge {
  width: 300px;
  flex-shrink: 0;
}
.chart-card {
  padding: 20px;
}
.chart-header {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  margin-bottom: 16px;
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
.chart-legend {
  display: flex;
  gap: 12px;
  align-items: center;
}
.legend-item {
  display: flex;
  align-items: center;
  gap: 5px;
  font-size: var(--font-size-xs);
  color: var(--gray-500);
}
.legend-dot {
  width: 10px;
  height: 3px;
  border-radius: 2px;
  display: block;
}
.legend-dot-dash {
  background-image: repeating-linear-gradient(
    90deg,
    currentColor 0,
    currentColor 4px,
    transparent 4px,
    transparent 8px
  );
  background-color: transparent !important;
}
.chart-body canvas {
  width: 100% !important;
}

/* Gauge Footer */
.gauge-body {
  display: flex;
  justify-content: center;
}
.gauge-footer {
  display: flex;
  align-items: center;
  justify-content: space-around;
  padding-top: 12px;
  border-top: 1px solid var(--gray-100);
  margin-top: 8px;
}
.gauge-stat {
  text-align: center;
}
.gauge-stat-value {
  font-size: 20px;
  font-weight: 700;
  line-height: 1.2;
}
.gauge-stat-label {
  font-size: var(--font-size-xs);
  color: var(--gray-400);
  margin-top: 2px;
}
.gauge-divider {
  width: 1px;
  height: 32px;
  background: var(--gray-200);
}

/* Timeline */
.timeline-container {
  display: flex;
  flex-direction: column;
  gap: 10px;
}
.timeline-row {
  display: flex;
  align-items: center;
  gap: 10px;
}
.timeline-label {
  width: 52px;
  font-size: var(--font-size-xs);
  color: var(--gray-600);
  font-weight: 500;
  flex-shrink: 0;
}
.timeline-bar-wrap {
  flex: 1;
  height: 22px;
  border-radius: 4px;
  overflow: hidden;
  display: flex;
  background: var(--gray-100);
}
.timeline-seg {
  height: 100%;
  transition: width 0.3s ease;
  cursor: default;
}
.seg-work {
  background: #1a6ef5;
}
.seg-wait {
  background: #f59e0b;
}
.seg-machine {
  background: #10b981;
}
.seg-idle {
  background: #e5e7eb;
}
.timeline-oee {
  width: 60px;
  font-size: var(--font-size-xs);
  color: var(--gray-500);
  text-align: right;
  flex-shrink: 0;
}
.timeline-legend {
  display: flex;
  gap: 14px;
  padding-top: 6px;
}
.tl-item {
  display: flex;
  align-items: center;
  gap: 5px;
  font-size: var(--font-size-xs);
  color: var(--gray-500);
}
.tl-item::before {
  content: '';
  display: inline-block;
  width: 12px;
  height: 8px;
  border-radius: 2px;
}
.tl-item.seg-work::before {
  background: #1a6ef5;
}
.tl-item.seg-wait::before {
  background: #f59e0b;
}
.tl-item.seg-machine::before {
  background: #10b981;
}
.tl-item.seg-idle::before {
  background: #e5e7eb;
}

/* Therblig Legend */
.therm-legend {
  padding: 8px 0 0;
  display: flex;
  flex-direction: column;
  gap: 5px;
}
.therm-legend-item {
  display: flex;
  align-items: center;
  gap: 8px;
  font-size: var(--font-size-xs);
}
.therm-dot {
  width: 8px;
  height: 8px;
  border-radius: 50%;
  flex-shrink: 0;
}
.therm-label {
  flex: 1;
  color: var(--gray-600);
}
.therm-value {
  font-weight: 600;
  color: var(--gray-700);
}

/* Bottom Row */
.bottom-row {
  display: flex;
  gap: 16px;
}
.bottom-card {
  flex: 1;
  min-width: 0;
  padding: 0;
  overflow: hidden;
}
.card-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 16px 20px;
  border-bottom: 1px solid var(--gray-100);
}
.order-id {
  font-family: monospace;
  font-size: var(--font-size-xs);
  color: var(--primary);
}
.bar-danger {
  background: var(--danger) !important;
}

/* Bottleneck Diagnosis */
.bottleneck-list {
  padding: 8px 16px 16px;
  display: flex;
  flex-direction: column;
  gap: 12px;
}
.bottleneck-item {
  background: var(--gray-50);
  border-radius: 8px;
  padding: 12px;
  border-left: 3px solid transparent;
}
.bottleneck-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  margin-bottom: 6px;
}
.bn-station {
  font-size: var(--font-size-sm);
  font-weight: 600;
  color: var(--gray-800);
}
.bn-tag {
  font-size: 11px;
  font-weight: 600;
  padding: 2px 8px;
  border-radius: 10px;
}
.bn-critical {
  background: var(--danger-bg);
  color: var(--danger);
}
.bn-warning {
  background: var(--warning-bg);
  color: var(--warning);
}
.bottleneck-item:has(.bn-critical) {
  border-left-color: var(--danger);
}
.bottleneck-item:has(.bn-warning) {
  border-left-color: var(--warning);
}
.bn-reason {
  display: flex;
  align-items: flex-start;
  gap: 5px;
  font-size: var(--font-size-xs);
  color: var(--gray-600);
  margin-bottom: 6px;
  line-height: 1.5;
}
.bn-suggest {
  display: flex;
  align-items: flex-start;
  gap: 5px;
  font-size: var(--font-size-xs);
  color: var(--success);
  line-height: 1.5;
}

/* Anomaly Alert Banner */
.anomaly-banner {
  padding: 0;
  border: 1px solid var(--danger-bg);
  background: linear-gradient(135deg, #fff5f5 0%, #ffffff 100%);
}
.anomaly-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 12px 16px;
  border-bottom: 1px solid var(--danger-bg);
}
.anomaly-title {
  display: flex;
  align-items: center;
  gap: 8px;
  font-size: var(--font-size-sm);
  font-weight: 600;
  color: var(--danger);
}
.anomaly-list {
  display: flex;
  flex-direction: column;
  gap: 8px;
  padding: 12px 16px;
}
.anomaly-item {
  display: flex;
  flex-direction: column;
  gap: 4px;
  padding: 8px 12px;
  background: var(--gray-50);
  border-radius: 6px;
  border-left: 3px solid var(--danger);
}
.anomaly-meta {
  display: flex;
  align-items: center;
  gap: 10px;
  font-size: var(--font-size-xs);
}
.anomaly-station {
  font-weight: 600;
  color: var(--gray-700);
}
.anomaly-type {
  padding: 1px 6px;
  border-radius: 4px;
  background: var(--danger-bg);
  color: var(--danger);
  font-size: 10px;
  font-weight: 600;
}
.anomaly-time {
  color: var(--gray-400);
  margin-left: auto;
}
.anomaly-desc {
  font-size: var(--font-size-xs);
  color: var(--gray-600);
  line-height: 1.5;
}
.anomaly-more {
  text-align: center;
  font-size: var(--font-size-xs);
  color: var(--gray-400);
  padding-top: 4px;
}

/* Responsive */
@media (max-width: 1300px) {
  .kpi-grid {
    grid-template-columns: repeat(2, 1fr);
  }
  .chart-gauge {
    width: 260px;
  }
}
@media (max-width: 1000px) {
  .charts-row {
    flex-direction: column;
  }
  .chart-gauge {
    width: 100%;
  }
  .bottom-row {
    flex-direction: column;
  }
}
@media (max-width: 600px) {
  .kpi-grid {
    grid-template-columns: 1fr 1fr;
  }
}
</style>
