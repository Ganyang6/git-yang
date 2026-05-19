/**
 * LineBalance view tests — P1-6: showToast 未定义
 *
 * Verifies that showToast is properly imported via useToast
 * in LineBalance.vue, preventing ReferenceError at runtime.
 */

import { describe, it, expect } from 'vitest'
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
