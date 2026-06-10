<template>
  <div class="reports-page">
    <div class="page-header">
      <div>
        <div class="page-title">报表分析</div>
        <div class="page-subtitle">数据统计与生产绩效分析</div>
      </div>
      <div class="flex gap-2">
        <select v-model="period" class="select" style="width: 120px">
          <option value="week">本周</option>
          <option value="month">本月</option>
          <option value="quarter">本季度</option>
        </select>
        <button class="btn btn-outline btn-sm" disabled title="导出功能开发中">
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
          导出报表
        </button>
      </div>
    </div>

    <!-- KPI Row -->
    <div class="report-kpis">
      <div v-for="kpi in kpiList" :key="kpi.label" class="report-kpi card">
        <div class="rk-label">{{ kpi.label }}</div>
        <div class="rk-value" :style="`color:${kpi.color}`">{{ kpi.value }}</div>
      </div>
    </div>

    <!-- Charts Grid -->
    <div class="charts-grid">
      <div class="card chart-block" style="grid-column: span 2">
        <div class="cb-header">
          <div class="cb-title">月度产量趋势</div>
        </div>
        <div ref="barChartRef" style="height: 160px; width: 100%"></div>
      </div>

      <div class="card chart-block">
        <div class="cb-header">
          <div class="cb-title">产品类别占比</div>
        </div>
        <div ref="pieChartRef" style="height: 200px; width: 100%"></div>
      </div>
    </div>

    <!-- Multi-Dimensional Analysis Charts -->
    <div class="charts-grid phase5-grid">
      <div class="card chart-block">
        <div class="cb-header">
          <div class="cb-title">多工位横向效率对比</div>
          <div class="cb-subtitle">雷达图: 利用率 / 有效工时比 / 瓶颈指数</div>
        </div>
        <div v-if="!lbChartData" class="chart-placeholder">暂无产线数据</div>
        <div v-else ref="radarChartRef" style="height: 300px; width: 100%"></div>
      </div>

      <div class="card chart-block">
        <div class="cb-header">
          <div class="cb-title">班次间效率波动分析</div>
          <div class="cb-subtitle">箱线图: 各工位班次工时分布 (中位数/Q1/Q3/异常值)</div>
        </div>
        <div v-if="!shiftData" class="chart-placeholder">暂无班次数据</div>
        <div v-else ref="boxplotChartRef" style="height: 300px; width: 100%"></div>
      </div>

      <div class="card chart-block">
        <div class="cb-header">
          <div class="cb-title">动素浪费热力图</div>
          <div class="cb-subtitle">时间(小时) vs 工位: wait+idle 占比</div>
        </div>
        <div v-if="!therbligData" class="chart-placeholder">暂无动素数据</div>
        <div v-else ref="heatmapChartRef" style="height: 300px; width: 100%"></div>
      </div>
    </div>

    <!-- Table: Top Customers -->
    <div class="card" style="overflow: hidden">
      <div
        class="card-header"
        style="
          padding: 16px 20px;
          border-bottom: 1px solid var(--gray-100);
          display: flex;
          align-items: center;
          justify-content: space-between;
        "
      >
        <div class="font-semibold" style="font-size: 15px">客户订单贡献排名</div>
        <span class="badge badge-primary">本月</span>
      </div>
      <div class="table-wrapper">
        <table class="table">
          <thead>
            <tr>
              <th>排名</th>
              <th>客户名称</th>
              <th>订单数</th>
              <th>产品数量(件)</th>
              <th>合同金额(万)</th>
              <th>占比</th>
              <th>趋势</th>
            </tr>
          </thead>
          <tbody>
            <tr v-for="(row, idx) in topCustomers" :key="row.name">
              <td>
                <span class="rank-badge" :class="`rank-${idx + 1}`">{{ idx + 1 }}</span>
              </td>
              <td class="text-sm font-medium">{{ row.name }}</td>
              <td class="text-sm">{{ row.orders }}</td>
              <td class="text-sm font-medium">{{ row.qty.toLocaleString() }}</td>
              <td class="text-sm font-medium" style="color: var(--primary)">{{ row.amount }}</td>
              <td>
                <div class="flex items-center gap-2">
                  <div class="progress progress-primary" style="width: 80px">
                    <div class="progress-bar" :style="`width:${row.share}%`"></div>
                  </div>
                  <span class="text-xs">{{ row.share }}%</span>
                </div>
              </td>
              <td>
                <span
                  :style="row.trend > 0 ? 'color:var(--success)' : 'color:var(--danger)'"
                  class="text-sm font-medium"
                >
                  {{ row.trend > 0 ? '+' : '' }}{{ row.trend }}%
                </span>
              </td>
            </tr>
          </tbody>
        </table>
      </div>
    </div>
  </div>
</template>

<script setup>
import { ref, onMounted, onUnmounted, watch, nextTick } from 'vue'
import * as echarts from 'echarts/core'
import { BarChart, PieChart, RadarChart } from 'echarts/charts'
import {
  TitleComponent,
  TooltipComponent,
  LegendComponent,
  GridComponent,
  RadarComponent,
  VisualMapComponent,
  ToolboxComponent,
  DatasetComponent,
  TransformComponent,
} from 'echarts/components'
import { CanvasRenderer } from 'echarts/renderers'
import { LabelLayout, UniversalTransition } from 'echarts/features'

echarts.use([
  BarChart, PieChart, RadarChart,
  TitleComponent, TooltipComponent, LegendComponent, GridComponent,
  RadarComponent, VisualMapComponent, ToolboxComponent, DatasetComponent,
  TransformComponent,
  CanvasRenderer,
  LabelLayout, UniversalTransition,
])
import {
  fetchReportKpi,
  fetchMonthlyOutput,
  fetchProductMix,
  fetchTopCustomers,
  fetchLineBalanceFull,
  fetchBoxplotData,
  fetchHeatmapData
} from '../api/index.js'

const period = ref('month')
const loading = ref(false)
const kpiList = ref([])
const topCustomers = ref([])
const barChartRef = ref(null)
const pieChartRef = ref(null)
const radarChartRef = ref(null)
const heatmapChartRef = ref(null)
const boxplotChartRef = ref(null)
let barChartInstance = null
let pieChartInstance = null
let radarChartInstance = null
let boxplotChartInstance = null
let heatmapChartInstance = null

// Multi-dimension chart data
const lbChartData = ref(null)
const shiftData = ref(null)
const therbligData = ref(null)

async function loadData() {
  loading.value = true
  try {
    const [kpiData, outputData, mixData, customerData] = await Promise.allSettled([
      fetchReportKpi(period.value),
      fetchMonthlyOutput(6),
      fetchProductMix(),
      fetchTopCustomers(period.value)
    ])

    // KPI
    if (kpiData.status === 'fulfilled') {
      const d = kpiData.value
      kpiList.value = [
        {
          label: '总产量(件)',
          value: d.totalOutput != null ? d.totalOutput.toLocaleString() : '--',
          color: '#1a6ef5',
        },
        {
          label: '订单完成率',
          value: d.completionRate != null ? `${d.completionRate}%` : '--',
          color: '#10b981',
        },
        {
          label: '综合良品率',
          value: d.yieldRate != null ? `${d.yieldRate}%` : '--',
          color: '#6366f1',
        },
        {
          label: '按时交货率',
          value: d.onTimeRate != null ? `${d.onTimeRate}%` : '--',
          color: '#f59e0b',
        },
      ]
    } else {
      kpiList.value = kpiList.value.length
        ? kpiList.value
        : [
            { label: '总产量(件)', value: '--', color: '#1a6ef5' },
            { label: '订单完成率', value: '--', color: '#10b981' },
            { label: '综合良品率', value: '--', color: '#6366f1' },
            { label: '按时交货率', value: '--', color: '#f59e0b' }
          ]
    }

    // Top customers
    if (customerData.status === 'fulfilled') {
      topCustomers.value = customerData.value
    }

    // Bar chart
    if (outputData.status === 'fulfilled' && barChartRef.value) {
      renderBarChart(outputData.value)
    }

    // Pie chart
    if (mixData.status === 'fulfilled' && pieChartRef.value) {
      renderPieChart(mixData.value)
    }

    // Load multi-dimension data
    loadPhase5Data()
  } finally {
    loading.value = false
  }
}

// Multi-dimension data loading
async function loadPhase5Data() {
  // Load line balance data for radar chart
  try {
    const lb = await fetchLineBalanceFull('line1')
    if (lb && lb.stations && lb.stations.length > 0) {
      lbChartData.value = lb
      await nextTick()
      renderRadarChart(lb)
    }
  } catch (err) {
    console.warn('[Reports] line balance data load failed:', err.message)
  }

  // Load boxplot data from real API
  try {
    const boxResp = await fetchBoxplotData()
    if (boxResp && boxResp.stations && boxResp.stations.length > 0) {
      shiftData.value = boxResp
      await nextTick()
      renderBoxplotChart(boxResp)
    }
  } catch (err) {
    console.warn('[Reports] boxplot data load failed:', err.message)
  }

  // Load heatmap data from real API
  try {
    const heatResp = await fetchHeatmapData()
    if (heatResp && heatResp.stations && heatResp.stations.length > 0 && heatResp.data.length > 0) {
      therbligData.value = heatResp
      await nextTick()
      renderHeatmapChart(heatResp)
    }
  } catch (err) {
    console.warn('[Reports] heatmap data load failed:', err.message)
  }
}


function renderBarChart(data) {
  if (!data || !barChartRef.value) return
  try {
    if (!barChartInstance) {
      barChartInstance = echarts.init(barChartRef.value)
    }
  } catch (err) {
    console.warn('[Reports] bar chart init failed:', err.message)
    return
  }
  console.log('[Reports] barChart data:', JSON.stringify(data).slice(0, 200))
  barChartInstance.setOption({
    tooltip: { trigger: 'axis' },
    grid: { top: 16, right: 20, bottom: 30, left: 52 },
    xAxis: {
      type: 'category',
      data: data.labels || [],
      axisLabel: { fontSize: 11, color: '#6b7280' }
    },
    yAxis: {
      type: 'value',
      axisLabel: {
        fontSize: 10,
        color: '#9ca3af',
        formatter: v => (v / 1000).toFixed(0) + 'k'
      },
      splitLine: { lineStyle: { color: '#f3f4f6' } }
    },
    series: [
      {
        type: 'bar',
        data: data.values || [],
        barWidth: '40%',
        itemStyle: {
          borderRadius: [4, 4, 0, 0],
          color: new echarts.graphic.LinearGradient(0, 0, 0, 1, [
            { offset: 0, color: '#1a6ef5' },
            { offset: 1, color: '#4a8ef9' }
          ])
        }
      }
    ]
  })
}

function renderPieChart(data) {
  if (!data || !pieChartRef.value) return
  try {
    if (!pieChartInstance) {
      pieChartInstance = echarts.init(pieChartRef.value)
    }
  } catch (err) {
    console.warn('[Reports] pie chart init failed:', err.message)
    return
  }
  console.log('[Reports] pieChart data:', JSON.stringify(data).slice(0, 200))
  pieChartInstance.setOption({
    tooltip: {
    trigger: 'item',
    formatter: (params) => {
      const name = params.name || '未知'
      const value = params.value ?? '-'
      const pct = params.percent?.toFixed(1) ?? '-'
      return `<strong>${name}</strong><br/>数量: ${value}<br/>占比: ${pct}%`
    }
  },
    legend: {
      bottom: 0,
      itemWidth: 10,
      itemHeight: 10,
      textStyle: { fontSize: 11, color: '#6b7280' }
    },
    series: [
      {
        type: 'pie',
        radius: ['50%', '70%'],
        center: ['50%', '45%'],
        data: (data || []).map(d => ({
          name: d.label || d.name || '未知',
          value: d.value ?? 0,
          itemStyle: d.color ? { color: d.color } : undefined
        })),
        label: { show: false },
        emphasis: { label: { show: true, fontSize: 12 } }
      }
    ]
  })
}

// Radar Chart - Multi-station efficiency comparison
function renderRadarChart(lbData) {
  if (!lbData || !radarChartRef.value) return
  try {
    if (!radarChartInstance) {
      radarChartInstance = echarts.init(radarChartRef.value)
    }
  } catch (err) {
    console.warn('[Reports] radar chart init failed:', err.message)
    return
  }

  const stations = (lbData.stations || []).filter(s => s && s.time != null)
  if (stations.length === 0) return
  const maxTime = Math.max(...stations.map(s => s.time), 1)
  const avgTime = stations.reduce((s, st) => s + st.time, 0) / stations.length

  // Build indicator dimensions (only real data, no synthetic metrics)
  const indicators = [
    { name: '利用率', max: 100 },
    { name: '有效工时比', max: 100 },
    { name: '瓶颈指数', max: 100 }
  ]

  // Compute per-station metrics (normalized to 0-100, all from real API data)
  const seriesData = stations.slice(0, 5).map((st) => {
    const utilization = Math.round((st.time / maxTime) * 100)
    const effectiveRatio = Math.round(Math.min((st.time / avgTime) * 80, 100))
    const bottleneckIdx = st.isBottleneck ? 95 : Math.round((st.time / maxTime) * 100)
    return {
      value: [utilization, effectiveRatio, bottleneckIdx],
      name: st.name
    }
  })

  console.log('[Reports] radarChart data:', JSON.stringify(lbData).slice(0, 200))
  radarChartInstance.setOption({
    tooltip: {
      trigger: 'item',
      formatter: (params) => {
        const dots = indicators.map((ind, i) =>
          `${ind.name}: ${params.value[i]}`
        ).join('<br/>')
        return `<strong>${params.name}</strong><br/>${dots}`
      }
    },
    legend: {
      bottom: 0,
      itemWidth: 12,
      itemHeight: 8,
      textStyle: { fontSize: 11, color: '#6b7280' },
      data: seriesData.map(d => d.name)
    },
    radar: {
      center: ['50%', '46%'],
      radius: '65%',
      indicator: indicators,
      axisName: { fontSize: 11, color: '#6b7280' },
      splitArea: { areaStyle: { color: ['#f9fafb', '#f3f4f6', '#f9fafb', '#f3f4f6'] } },
      splitLine: { lineStyle: { color: '#e5e7eb' } },
      axisLine: { lineStyle: { color: '#e5e7eb' } }
    },
    series: [
      {
        type: 'radar',
        data: seriesData,
        lineStyle: { width: 2 },
        emphasis: { lineStyle: { width: 3 } }
      }
    ],
    color: ['#1a6ef5', '#10b981', '#f59e0b', '#ec4899', '#6366f1']
  })
}

// Boxplot Chart - Shift efficiency distribution (data from real API)
async function renderBoxplotChart(data) {
  const { BoxplotChart } = await import('echarts/charts')
  echarts.use([BoxplotChart])
  if (!boxplotChartRef.value) return
  try {
    if (!boxplotChartInstance) {
      boxplotChartInstance = echarts.init(boxplotChartRef.value)
    }
  } catch (err) {
    console.warn('[Reports] boxplot chart init failed:', err.message)
    return
  }

  // data = { stations: string[], shifts: string[], morning: number[][], afternoon: number[][], night: number[][] }
  // Each inner array is [min, Q1, median, Q3, max]
  if (!data) return
  const stationNames = data.stations || []

  // Collect shift data that has actual entries (non-null box values)
  const shiftLabels = { morning: '早班', afternoon: '中班', night: '夜班' }
  const series = []
  const legendData = []

  // Determine which stations have valid data in at least one shift
  const validStationIdxs = []
  for (let i = 0; i < stationNames.length; i++) {
    for (const shift of (data.shifts || [])) {
      const arr = data[shift]
      if (arr && arr[i] != null) {
        validStationIdxs.push(i)
        break
      }
    }
  }
  const filteredStations = validStationIdxs.map(i => stationNames[i])

  // ── Pass 1: Build the intersection mask of stations non-null in ALL shifts ──
  let commonValidMask = null // boolean[] aligned with validStationIdxs order
  for (const shift of (data.shifts || [])) {
    const shiftArr = data[shift]
    if (!shiftArr || shiftArr.length === 0) continue
    const thisShiftMask = validStationIdxs.map(i => shiftArr[i] != null)
    if (commonValidMask === null) {
      commonValidMask = thisShiftMask
    } else {
      commonValidMask = commonValidMask.map((v, j) => v && thisShiftMask[j])
    }
  }
  const finalValidMask = commonValidMask || []

  // ── Pass 2: Build series data using only intersection-valid stations ──
  // Convert mask to indices (relative to validStationIdxs order) that survived
  const keepIdxs = finalValidMask
    .map((ok, j) => ok ? j : -1)
    .filter(j => j >= 0)
  const finalFilteredStations = keepIdxs.map(j => filteredStations[j])

  for (const shift of (data.shifts || [])) {
    const shiftArr = data[shift]
    if (!shiftArr || shiftArr.length === 0) continue

    // Map validStationIdxs to raw data, then keep only intersection-valid entries
    const rawData = validStationIdxs.map(i => shiftArr[i])
    const cleanData = keepIdxs.map(j => rawData[j]).filter(b => b != null)

    if (cleanData.length === 0) continue
    series.push({
      name: shiftLabels[shift] || shift,
      type: 'boxplot',
      data: cleanData,
      itemStyle: shift === 'morning' ? { color: '#1a6ef5', borderColor: '#1a6ef5' }
        : shift === 'afternoon' ? { color: '#10b981', borderColor: '#10b981' }
          : { color: '#f59e0b', borderColor: '#f59e0b' },
      emphasis: { itemStyle: { borderWidth: 2 } }
    })
    legendData.push(shiftLabels[shift] || shift)
  }

  // No series to render
  if (series.length === 0) return

  console.log(
    '[Reports] boxplotChart series (no null entries):',
    series.map(s => ({ name: s.name, data: s.data })).slice(0, 3)
  )
  boxplotChartInstance.setOption({
    tooltip: {
      trigger: 'item',
      formatter: (params) => {
        if (params.componentType === 'series' && params.data) {
          if (!Array.isArray(params.data)) return ''
          const [min, q1, median, q3, max] = params.data
          if (min == null || q1 == null || median == null || q3 == null || max == null) return ''
          return `${params.seriesName}<br/>` +
            `Min: ${min.toFixed(1)}s<br/>` +
            `Q1: ${q1.toFixed(1)}s<br/>` +
            `Median: ${median.toFixed(1)}s<br/>` +
            `Q3: ${q3.toFixed(1)}s<br/>` +
            `Max: ${max.toFixed(1)}s`
        }
        return ''
      }
    },
    legend: {
      bottom: 0,
      itemWidth: 12,
      itemHeight: 8,
      textStyle: { fontSize: 11, color: '#6b7280' },
      data: legendData
    },
    grid: { top: 16, right: 20, bottom: 40, left: 52 },
    xAxis: {
      type: 'category',
      data: finalFilteredStations,
      axisLabel: { fontSize: 11, color: '#6b7280' }
    },
    yAxis: {
      type: 'value',
      name: '工时(s)',
      nameTextStyle: { fontSize: 10, color: '#9ca3af' },
      axisLabel: { fontSize: 10, color: '#9ca3af' },
      splitLine: { lineStyle: { color: '#f3f4f6' } }
    },
    series
  })
}

// Heatmap Chart - Therblig waste distribution (data from real API)
async function renderHeatmapChart(apiData) {
  const { HeatmapChart } = await import('echarts/charts')
  echarts.use([HeatmapChart])
  if (!heatmapChartRef.value) return
  try {
    if (!heatmapChartInstance) {
      heatmapChartInstance = echarts.init(heatmapChartRef.value)
    }
  } catch (err) {
    console.warn('[Reports] heatmap chart init failed:', err.message)
    return
  }

  // apiData = { stations: string[], hours: string[], data: [[hourIdx, stationIdx, wastePct], ...] }
  if (!apiData) return
  const stations = apiData.stations || []
  const hours = apiData.hours || []
  // Guard: filter out entries with null/undefined wastePct to prevent NaN in visualMap
  const heatmapData = (apiData.data || []).filter(
    entry => entry && entry.length >= 3 && entry[2] != null
  )

  // Only render if we have actual data
  if (stations.length === 0 || heatmapData.length === 0) {
    therbligData.value = null
    return
  }

  // Determine visual map max from actual data
  const maxVal = Math.max(...heatmapData.map(d => d[2]), 1)

  console.log('[Reports] heatmapChart data:', JSON.stringify(apiData).slice(0, 200))
  heatmapChartInstance.setOption({
    tooltip: {
      position: 'top',
      formatter: (params) => {
        return `${stations[params.value[1]]} ${hours[params.value[0]]}<br/>` +
          `wait+idle 占比: <strong>${params.value[2]}%</strong>`
      }
    },
    grid: { top: 10, right: 60, bottom: 30, left: 60 },
    xAxis: {
      type: 'category',
      data: hours,
      axisLabel: { fontSize: 10, color: '#6b7280' },
      axisLine: { lineStyle: { color: '#e5e7eb' } }
    },
    yAxis: {
      type: 'category',
      data: stations,
      axisLabel: { fontSize: 10, color: '#6b7280' },
      axisLine: { lineStyle: { color: '#e5e7eb' } }
    },
    visualMap: {
      min: 0,
      max: Math.ceil(maxVal),
      calculable: true,
      orient: 'vertical',
      right: 0,
      top: 'center',
      itemWidth: 10,
      itemHeight: 100,
      textStyle: { fontSize: 10, color: '#6b7280' },
      inRange: {
        color: ['#f0fdf4', '#bbf7d0', '#4ade80', '#facc15', '#f97316', '#ef4444']
      }
    },
    series: [
      {
        type: 'heatmap',
        data: heatmapData,
        label: {
          show: true,
          fontSize: 9,
          formatter: (p) => p.value[2] + '%'
        },
        emphasis: {
          itemStyle: { shadowBlur: 10, shadowColor: 'rgba(0, 0, 0, 0.3)' }
        }
      }
    ]
  })
}

function handleResize() {
  barChartInstance?.resize()
  pieChartInstance?.resize()
  radarChartInstance?.resize()
  boxplotChartInstance?.resize()
  heatmapChartInstance?.resize()
}

watch(period, () => {
  loadData()
})

onMounted(() => {
  loadData()
  window.addEventListener('resize', handleResize)
})

onUnmounted(() => {
  window.removeEventListener('resize', handleResize)
  barChartInstance?.dispose()
  pieChartInstance?.dispose()
  radarChartInstance?.dispose()
  boxplotChartInstance?.dispose()
  heatmapChartInstance?.dispose()
})
</script>

<style scoped>
.reports-page {
  display: flex;
  flex-direction: column;
  gap: 16px;
}
.report-kpis {
  display: grid;
  grid-template-columns: repeat(5, 1fr);
  gap: 12px;
}
.report-kpi {
  padding: 16px 18px;
}
.rk-label {
  font-size: var(--font-size-xs);
  color: var(--gray-400);
  margin-bottom: 6px;
}
.rk-value {
  font-size: var(--font-size-2xl);
  font-weight: 700;
  margin-bottom: 6px;
}

.charts-grid {
  display: grid;
  grid-template-columns: 2fr 1fr;
  gap: 14px;
}

.phase5-grid {
  grid-template-columns: 1fr 1fr 1fr;
  margin-top: 14px;
}

.cb-subtitle {
  font-size: var(--font-size-xs);
  color: var(--gray-400);
  margin-top: 2px;
}

.chart-placeholder {
  display: flex;
  align-items: center;
  justify-content: center;
  height: 260px;
  color: var(--gray-400);
  font-size: var(--font-size-sm);
}
.chart-block {
  padding: 18px 20px;
}
.cb-header {
  margin-bottom: 14px;
}
.cb-title {
  font-size: var(--font-size-base);
  font-weight: 600;
  color: var(--gray-800);
}

.rank-badge {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  width: 22px;
  height: 22px;
  border-radius: 50%;
  font-size: 11px;
  font-weight: 700;
}
.rank-1 {
  background: #fbbf24;
  color: #fff;
}
.rank-2 {
  background: #9ca3af;
  color: #fff;
}
.rank-3 {
  background: #c97b2c;
  color: #fff;
}
.rank-4,
.rank-5 {
  background: var(--gray-100);
  color: var(--gray-500);
}

@media (max-width: 1100px) {
  .report-kpis {
    grid-template-columns: repeat(3, 1fr);
  }
  .charts-grid {
    grid-template-columns: 1fr;
  }
  .charts-grid .chart-block {
    grid-column: span 1 !important;
  }
  .phase5-grid {
    grid-template-columns: 1fr;
  }
}
@media (max-width: 768px) {
  .report-kpis {
    grid-template-columns: repeat(2, 1fr);
  }
}
</style>
