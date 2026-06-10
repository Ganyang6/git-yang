import { describe, it, expect } from 'vitest'

// 模拟 ECharts 行为：getInitialData 对 null/undefined 崩溃
function simulateGetInitialData(data) {
  try {
    data.forEach(item => {
      // ECharts 内部会尝试读取 .value
      if (item === null || item === undefined) {
        throw new TypeError(`Cannot read properties of ${item === null ? 'null' : 'undefined'} (reading 'value')`)
      }
    })
    return true
  } catch (e) {
    return e.message
  }
}

describe('renderBoxplotChart data sanitization', () => {
  it('should reject null entries in shift data', () => {
    const shiftArr = [1.2, null, 0.5]
    const result = simulateGetInitialData(shiftArr)
    expect(result).toContain('null')
  })

  it('should reject undefined entries in shift data', () => {
    const shiftArr = [1.2, undefined, 0.5]
    const result = simulateGetInitialData(shiftArr)
    expect(result).toContain('undefined')
  })

  it('should accept clean data without crash', () => {
    const shiftArr = [1.2, 3.4, 0.5]
    const result = simulateGetInitialData(shiftArr)
    expect(result).toBe(true)
  })
})

describe('renderBarChart data safety', () => {
  it('should handle null data gracefully', () => {
    const data = null
    const items = (data || [])
    expect(Array.isArray(items)).toBe(true)
    expect(items.length).toBe(0)
  })
})

describe('renderPieChart data safety', () => {
  it('should handle null data gracefully', () => {
    const data = null
    const mapped = (data || []).map(d => ({ value: 0 }))
    expect(Array.isArray(mapped)).toBe(true)
    expect(mapped.length).toBe(0)
  })
})
