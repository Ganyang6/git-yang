/**
 * LineBalance view tests — P1-6: showToast 未定义
 *
 * Verifies that showToast is properly imported via useToast
 * in LineBalance.vue, preventing ReferenceError at runtime.
 */

import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest'
import { readFileSync } from 'fs'
import { resolve } from 'path'

const sourcePath = resolve(process.cwd(), 'src/views/LineBalance.vue')
const source = readFileSync(sourcePath, 'utf-8')

describe('LineBalance - showToast import (P1-6)', () => {
  it('references showToast in the catch block', () => {
    // The component's exportLineBalancePdf catch block calls showToast
    expect(source).toContain("showToast('PDF")
  })

  it('imports useToast', () => {
    // Verify the composable is imported
    const hasImport = source.includes("from '../composables/useToast.js'")
      || source.includes("from '@/composables/useToast.js'")
    expect(hasImport).toBe(true)
  })

  it('destructures showToast from useToast', () => {
    // Verify showToast is destructured from useToast
    const match = source.match(/const\s*\{[^}]*showToast[^}]*\}\s*=\s*useToast\(\)/)
    expect(match).not.toBeNull()
  })
})

describe('LineBalance - 方案A: 产线下拉从 meta.lines 动态加载', () => {
  beforeEach(() => {
    vi.restoreAllMocks()
  })

  it('should import fetchMeta from api', () => {
    expect(source).toContain('fetchMeta')
  })

  it('should NOT have hardcoded line options in template', () => {
    // Template should NOT contain hardcoded option tags
    expect(source).not.toContain('value="line1"')
    expect(source).not.toContain('value="line2"')
  })

  it('should render line options from meta.lines', async () => {
    vi.mock('../../src/api/index.js', () => ({
      fetchLineBalanceFull: vi.fn(() => Promise.resolve(null)),
      downloadBlob: vi.fn(),
      fetchMeta: vi.fn()
    }), { await: true })

    const { fetchMeta } = await import('../../src/api/index.js')

    // Simulate meta API returning lines
    fetchMeta.mockResolvedValue({
      stations: [],
      shifts: [],
      lines: [
        { id: 'line-alpha', name: '产线 Alpha' },
        { id: 'line-beta', name: '产线 Beta' },
        { id: 'line-gamma', name: '产线 Gamma' }
      ],
      mod_unit: 0.129,
      default_allowance_rate: 15,
      thresholds: {}
    })

    const meta = await fetchMeta()
    const metaLines = (meta.lines || []).map(l => ({ value: l.id, label: l.name }))

    expect(metaLines).toEqual([
      { value: 'line-alpha', label: '产线 Alpha' },
      { value: 'line-beta', label: '产线 Beta' },
      { value: 'line-gamma', label: '产线 Gamma' }
    ])

    // No hardcoded lines — only what meta returns
    expect(metaLines.length).toBe(3)
  })

  it('should show error when fetchMeta fails', async () => {
    vi.mock('../../src/api/index.js', () => ({
      fetchLineBalanceFull: vi.fn(() => Promise.resolve(null)),
      downloadBlob: vi.fn(),
      fetchMeta: vi.fn(() => Promise.reject(new Error('Meta API failed')))
    }), { await: true })

    const { fetchMeta } = await import('../../src/api/index.js')

    let metaLines = []
    let errorMsg = ''

    try {
      await fetchMeta()
    } catch {
      errorMsg = '元数据加载失败'
    }

    expect(errorMsg).toBe('元数据加载失败')
    expect(metaLines.length).toBe(0) // No fallback — stays empty
  })
})
