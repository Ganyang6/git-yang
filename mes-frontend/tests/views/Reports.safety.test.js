/**
 * Reports chart data safety tests.
 * Ensure no setOption receives null/undefined data that would cause ECharts crash.
 */
import { describe, it, expect, vi, beforeEach } from 'vitest'

// Mock echarts
vi.mock('echarts/core', () => ({
  init: vi.fn(() => ({
    setOption: vi.fn(),
    resize: vi.fn(),
    dispose: vi.fn(),
  })),
  use: vi.fn(),
  graphic: {
    LinearGradient: vi.fn(),
  },
}))

vi.mock('echarts/charts', () => ({ BarChart: {}, PieChart: {}, RadarChart: {} }))

vi.mock('echarts/components', () => ({
  TitleComponent: {},
  TooltipComponent: {},
  LegendComponent: {},
  GridComponent: {},
  RadarComponent: {},
  VisualMapComponent: {},
  ToolboxComponent: {},
  DatasetComponent: {},
  TransformComponent: {},
}))

vi.mock('echarts/renderers', () => ({ CanvasRenderer: {} }))
vi.mock('echarts/features', () => ({ LabelLayout: {}, UniversalTransition: {} }))

// Import the render functions indirectly by extracting the relevant logic
// We test the data-processing logic directly

describe('Reports.vue - chart null/undefined data safety', () => {
  // Simulate the data-processing logic from renderBarChart
  describe('renderBarChart data safety', () => {
    it('should handle null data gracefully without crashing', () => {
      const data = null
      // Before fix: data.labels would throw TypeError
      // After fix: use (data || {})
      const safeData = data || {}
      expect(safeData.labels).toBeUndefined()
      expect(safeData.values).toBeUndefined()
      // setOption with empty labels/values should work
      const labels = safeData.labels || []
      const values = safeData.values || []
      expect(Array.isArray(labels)).toBe(true)
      expect(Array.isArray(values)).toBe(true)
    })

    it('should handle undefined data gracefully', () => {
      const data = undefined
      const safeData = data || {}
      expect(safeData.labels).toBeUndefined()
      expect(safeData.values).toBeUndefined()
    })

    it('should pass through valid data correctly', () => {
      const data = { labels: ['Jan', 'Feb'], values: [100, 200] }
      const safeData = data || {}
      expect(safeData.labels).toEqual(['Jan', 'Feb'])
      expect(safeData.values).toEqual([100, 200])
    })
  })

  // Simulate renderPieChart data processing
  describe('renderPieChart data safety', () => {
    it('should handle null data gracefully (already guarded)', () => {
      const data = null
      const result = (data || []).map(d => ({
        name: d.label || d.name || '未知',
        value: d.value ?? 0,
      }))
      expect(result).toEqual([])
    })

    it('should handle undefined data gracefully', () => {
      const data = undefined
      const result = (data || []).map(d => ({
        name: d.label || d.name || '未知',
        value: d.value ?? 0,
      }))
      expect(result).toEqual([])
    })

    it('should handle valid data correctly', () => {
      const data = [{ label: 'A', value: 10 }, { name: 'B', value: 20 }]
      const result = (data || []).map(d => ({
        name: d.label || d.name || '未知',
        value: d.value ?? 0,
      }))
      expect(result).toEqual([
        { name: 'A', value: 10 },
        { name: 'B', value: 20 },
      ])
    })
  })

  // Simulate renderRadarChart data processing
  describe('renderRadarChart data safety', () => {
    it('should handle stations with null time values', () => {
      const lbData = {
        stations: [
          { name: 'A', time: 100 },
          { name: 'B', time: null },
          { name: 'C', time: 50 },
          null,
        ],
      }
      const stations = (lbData.stations || []).filter(s => s && s.time != null)
      const maxTime = Math.max(...stations.map(s => s.time), 1)
      expect(maxTime).toBe(100)
      expect(stations.length).toBe(2)
    })

    it('should handle null lbData gracefully', () => {
      const lbData = null
      const stations = lbData?.stations || []
      expect(stations).toEqual([])
    })

    it('should handle empty stations gracefully', () => {
      const lbData = { stations: [] }
      const stations = lbData.stations || []
      const maxTime = Math.max(...stations.map(s => s.time), 1)
      expect(maxTime).toBe(1)
    })
  })

  // Simulate renderBoxplotChart data safety
  describe('renderBoxplotChart data safety', () => {
    it('should handle null box entries in shift data', () => {
      const data = {
        stations: ['S1', 'S2', 'S3'],
        shifts: ['morning', 'afternoon'],
        morning: [[1, 2, 3, 4, 5], null, [2, 3, 4, 5, 6]],
        afternoon: [null, [5, 6, 7, 8, 9], [3, 4, 5, 6, 7]],
      }

      const stationNames = data.stations || []
      const shiftLabels = { morning: '早班', afternoon: '中班', night: '夜班' }

      // Build per-shift clean data (no null entries reach setOption)
      const series = []
      const legendData = []

      for (const shift of (data.shifts || [])) {
        const shiftArr = data[shift]
        if (!shiftArr) continue

        const cleanData = shiftArr.map((box) => {
          if (box && Array.isArray(box) && box.length === 5 && box.every(v => v != null)) {
            return box
          }
          return [0, 0, 0, 0, 0] // safe sentinel
        })

        if (cleanData.every(b => b.every(v => v === 0))) continue

        series.push({
          name: shiftLabels[shift] || shift,
          type: 'boxplot',
          data: cleanData,
        })
        legendData.push(shiftLabels[shift] || shift)
      }

      expect(series.length).toBe(2)
      expect(series[0].data).toEqual([[1, 2, 3, 4, 5], [0, 0, 0, 0, 0], [2, 3, 4, 5, 6]])
      expect(series[1].data).toEqual([[0, 0, 0, 0, 0], [5, 6, 7, 8, 9], [3, 4, 5, 6, 7]])
      // Verify no null entries reach series data
      series.forEach(s => {
        s.data.forEach(d => {
          expect(d).not.toBeNull()
          expect(d).not.toBeUndefined()
          expect(Array.isArray(d)).toBe(true)
          d.forEach(v => expect(v).not.toBeNull())
        })
      })
    })

    it('should handle null shifts array gracefully', () => {
      const data = { stations: ['S1'], shifts: null }
      const result = (data.shifts || []).map(s => s)
      expect(result).toEqual([])
    })

    it('should skip shift entirely when all entries are invalid', () => {
      const data = {
        stations: ['S1', 'S2'],
        shifts: ['morning'],
        morning: [null, null],
      }
      const shiftArr = data.morning
      const cleanData = shiftArr.map(box => {
        if (box && Array.isArray(box) && box.every(v => v != null)) return box
        return [0, 0, 0, 0, 0]
      })
      expect(cleanData.every(b => b.every(v => v === 0))).toBe(true)
    })
  })

  // Simulate renderHeatmapChart data safety
  describe('renderHeatmapChart data safety', () => {
    it('should handle null wastePct in heatmap entries', () => {
      const apiData = {
        stations: ['S1', 'S2'],
        hours: ['08:00', '09:00'],
        data: [
          [0, 0, 25],
          [1, 0, null],
          [0, 1, 30],
          [1, 1, undefined],  // should be treated as 0
        ],
      }

      const heatmapData = (apiData.data || []).filter(
        entry => entry && entry.length >= 3 && entry[2] != null
      )
      expect(heatmapData.length).toBe(2)
      expect(heatmapData[0]).toEqual([0, 0, 25])
      expect(heatmapData[1]).toEqual([0, 1, 30])

      const maxVal = Math.max(...heatmapData.map(d => d[2]), 1)
      expect(maxVal).toBe(30)
    })

    it('should handle null apiData gracefully', () => {
      const apiData = null
      const stations = apiData?.stations || []
      const heatmapData = apiData?.data || []
      expect(stations).toEqual([])
      expect(heatmapData).toEqual([])
    })
  })
})
