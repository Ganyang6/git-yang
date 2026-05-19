/**
 * useDashboardCharts - Canvas chart drawing logic for Dashboard
 *
 * Extracted from Dashboard.vue (P2 #79) to reduce single-file size.
 * Draws 3 charts: balance bar chart, worktime trend line, therblig donut.
 */

/**
 * HiDPI canvas scaling helper.
 * Returns a 2D context already scaled for devicePixelRatio.
 */
function setupCanvas(canvas, w, h) {
  const dpr = window.devicePixelRatio || 1
  canvas.width = w * dpr
  canvas.height = h * dpr
  canvas.style.width = w + 'px'
  canvas.style.height = h + 'px'
  const ctx = canvas.getContext('2d')
  ctx.scale(dpr, dpr)
  return ctx
}

/**
 * Draw line-balance bar chart on a canvas element.
 * @param {HTMLCanvasElement} canvas
 * @param {object} balanceSummary - { stations: [{name, time, isBottleneck}], taktTime }
 */
function drawBalanceChart(canvas, balanceSummary) {
  if (!canvas || !balanceSummary) return
  const stations = balanceSummary.stations
  if (!stations || !stations.length) return

  const W = canvas.offsetWidth || 280
  const H = 180
  const ctx = setupCanvas(canvas, W, H)

  const takt = balanceSummary.taktTime
  const maxTime = Math.max(...stations.map(s => s.time)) || 1
  const pad = { top: 16, right: 16, bottom: 32, left: 36 }
  const chartW = W - pad.left - pad.right
  const chartH = H - pad.top - pad.bottom
  const barW = (chartW / stations.length) * 0.55
  const gap = chartW / stations.length

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
    const val = Math.round(maxTime - (maxTime / 4) * i)
    ctx.fillStyle = '#9ca3af'
    ctx.font = '10px sans-serif'
    ctx.textAlign = 'right'
    ctx.fillText(val + 's', pad.left - 4, y + 4)
  }

  // Takt line
  if (takt) {
    const taktY = pad.top + chartH - (takt / maxTime) * chartH
    ctx.beginPath()
    ctx.strokeStyle = '#f59e0b'
    ctx.lineWidth = 1.5
    ctx.setLineDash([6, 4])
    ctx.moveTo(pad.left, taktY)
    ctx.lineTo(pad.left + chartW, taktY)
    ctx.stroke()
    ctx.setLineDash([])
    ctx.fillStyle = '#f59e0b'
    ctx.font = 'bold 10px sans-serif'
    ctx.textAlign = 'left'
    ctx.fillText('Takt', pad.left + chartW - 28, taktY - 4)
  }

  // Bars
  stations.forEach((s, i) => {
    const x = pad.left + gap * i + (gap - barW) / 2
    const barH = (s.time / maxTime) * chartH
    const y = pad.top + chartH - barH

    const grad = ctx.createLinearGradient(0, y, 0, y + barH)
    if (s.isBottleneck) {
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

    ctx.fillStyle = s.isBottleneck ? '#ef4444' : '#374151'
    ctx.font = 'bold 11px sans-serif'
    ctx.textAlign = 'center'
    ctx.fillText(s.time + 's', x + barW / 2, y - 4)

    ctx.fillStyle = '#6b7280'
    ctx.font = '10px sans-serif'
    ctx.fillText(s.name, x + barW / 2, H - 6)
  })
}

/**
 * Draw worktime trend line chart.
 * @param {HTMLCanvasElement} canvas
 * @param {object} trend - { labels: string[], actual: number[], standard: number[] }
 */
function drawWorktimeChart(canvas, worktimeTrend) {
  if (!canvas || !worktimeTrend) return
  const { labels, actual, standard } = worktimeTrend
  if (!labels || !labels.length || labels.length < 2) return

  const W = canvas.offsetWidth || 500
  const H = 180
  const ctx = setupCanvas(canvas, W, H)

  const pad = { top: 16, right: 20, bottom: 32, left: 40 }
  const chartW = W - pad.left - pad.right
  const chartH = H - pad.top - pad.bottom
  const allVals = [...actual, ...standard].filter(v => v != null)
  if (!allVals.length) return
  const minVal = Math.max(0, Math.min(...allVals) - 10)
  const maxVal = Math.max(...allVals) + 10

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
    const val = maxVal - ((maxVal - minVal) / 4) * i
    ctx.fillStyle = '#9ca3af'
    ctx.font = '10px sans-serif'
    ctx.textAlign = 'right'
    ctx.fillText(val.toFixed(0) + 's', pad.left - 4, y + 4)
  }

  function getX(i) {
    return pad.left + (chartW / (labels.length - 1)) * i
  }
  function getY(v) {
    return pad.top + chartH - ((v - minVal) / (maxVal - minVal)) * chartH
  }

  // Standard line (dashed)
  ctx.beginPath()
  ctx.strokeStyle = '#f59e0b'
  ctx.lineWidth = 1.5
  ctx.setLineDash([5, 4])
  standard.forEach((v, i) => {
    i === 0 ? ctx.moveTo(getX(i), getY(v)) : ctx.lineTo(getX(i), getY(v))
  })
  ctx.stroke()
  ctx.setLineDash([])

  // Actual area fill
  ctx.beginPath()
  ctx.moveTo(getX(0), getY(actual[0]))
  actual.forEach((v, i) => {
    if (i > 0) ctx.lineTo(getX(i), getY(v))
  })
  ctx.lineTo(getX(actual.length - 1), pad.top + chartH)
  ctx.lineTo(getX(0), pad.top + chartH)
  ctx.closePath()
  const grad = ctx.createLinearGradient(0, pad.top, 0, pad.top + chartH)
  grad.addColorStop(0, 'rgba(26,110,245,0.2)')
  grad.addColorStop(1, 'rgba(26,110,245,0)')
  ctx.fillStyle = grad
  ctx.fill()

  // Actual line
  ctx.beginPath()
  ctx.strokeStyle = '#1a6ef5'
  ctx.lineWidth = 2.5
  actual.forEach((v, i) => {
    i === 0 ? ctx.moveTo(getX(i), getY(v)) : ctx.lineTo(getX(i), getY(v))
  })
  ctx.stroke()

  // Dots
  actual.forEach((v, i) => {
    ctx.beginPath()
    ctx.arc(getX(i), getY(v), 4, 0, Math.PI * 2)
    const stdVal = standard[i] || standard[0]
    ctx.fillStyle = v > stdVal ? '#ef4444' : '#1a6ef5'
    ctx.fill()
    ctx.strokeStyle = '#fff'
    ctx.lineWidth = 2
    ctx.stroke()
  })

  // X labels
  ctx.fillStyle = '#9ca3af'
  ctx.font = '10px sans-serif'
  ctx.textAlign = 'center'
  labels.forEach((l, i) => {
    ctx.fillText(l, getX(i), H - 8)
  })
}

/**
 * Draw therblig distribution donut chart.
 * @param {HTMLCanvasElement} canvas
 * @param {Array} thermData - [{label, pct, color}]
 */
function drawThermChart(canvas, thermData) {
  if (!canvas || !thermData || !thermData.length) return

  const SIZE = 180
  const ctx = setupCanvas(canvas, SIZE, SIZE)

  const total = thermData.reduce((s, d) => s + d.pct, 0)
  let startAngle = -Math.PI / 2
  const cx = 90,
    cy = 90,
    r = 72,
    innerR = 46

  thermData.forEach(item => {
    const angle = (item.pct / total) * Math.PI * 2
    ctx.beginPath()
    ctx.moveTo(cx, cy)
    ctx.arc(cx, cy, r, startAngle, startAngle + angle)
    ctx.closePath()
    ctx.fillStyle = item.color
    ctx.fill()
    startAngle += angle
  })

  ctx.beginPath()
  ctx.arc(cx, cy, innerR, 0, Math.PI * 2)
  ctx.fillStyle = '#fff'
  ctx.fill()

  ctx.fillStyle = '#111827'
  ctx.font = 'bold 18px sans-serif'
  ctx.textAlign = 'center'
  ctx.textBaseline = 'middle'
  ctx.fillText(thermData.length + '类', cx, cy - 8)
  ctx.fillStyle = '#9ca3af'
  ctx.font = '11px sans-serif'
  ctx.fillText('动素', cx, cy + 10)
}

export {
  setupCanvas,
  drawBalanceChart,
  drawWorktimeChart,
  drawThermChart
}
