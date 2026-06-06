/**
 * useToast composable unit tests
 *
 * Covers:
 *   - showToast adds a toast to the reactive list
 *   - added toast has id, message, and type fields
 *   - dismissToast removes toast by id
 *   - dismissByType removes only matching toasts
 *   - MAX_TOASTS (10) cap: oldest toast evicted
 *   - auto-dismiss: toast removed after duration
 *   - multiple toasts coexist with distinct ids
 *   - empty list after dismissing all
 */

import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest'

// useToast uses module-level shared state (toasts ref).
// We advance fake timers between tests to clear auto-dismiss timers.
vi.useFakeTimers({ shouldAdvanceTime: true })

import { useToast } from './useToast.js'

function advanceToClearTimers() {
  // Advance enough time for all 3s + 5s timers to fire
  vi.advanceTimersByTime(10000)
}

describe('useToast', () => {
  beforeEach(() => {
    // Clear any lingering toasts from previous tests by advancing time
    advanceToClearTimers()
  })

  afterEach(() => {
    advanceToClearTimers()
  })

  it('returns toasts ref and helper functions', () => {
    const { toasts, showToast, dismissToast, dismissByType } = useToast()
    expect(toasts).toBeDefined()
    expect(Array.isArray(toasts.value)).toBe(true)
    expect(typeof showToast).toBe('function')
    expect(typeof dismissToast).toBe('function')
    expect(typeof dismissByType).toBe('function')
  })

  it('starts with an empty list', () => {
    // After clearing timers in beforeEach, should be empty
    const { toasts } = useToast()
    expect(toasts.value.length).toBe(0)
  })

  it('showToast adds a toast to the list', () => {
    const { toasts, showToast } = useToast()
    showToast('操作成功', 'success')
    expect(toasts.value.length).toBe(1)
    expect(toasts.value[0].message).toBe('操作成功')
    expect(toasts.value[0].type).toBe('success')
    expect(typeof toasts.value[0].id).toBe('number')
  })

  it('accepts different toast types', () => {
    const { toasts, showToast } = useToast()
    showToast('警告信息', 'warning')
    showToast('发生错误', 'error')
    showToast('仅供参考', 'info')
    expect(toasts.value.length).toBe(3)
    expect(toasts.value[0].type).toBe('warning')
    expect(toasts.value[1].type).toBe('error')
    expect(toasts.value[2].type).toBe('info')
  })

  it('dismissToast removes the correct toast by id', () => {
    const { toasts, showToast, dismissToast } = useToast()
    showToast('第一条', 'info')
    showToast('第二条', 'info')
    const last = toasts.value[toasts.value.length - 1]
    dismissToast(last.id)
    expect(toasts.value.length).toBe(1)
    expect(toasts.value[0].message).toBe('第一条')
  })

  it('dismissByType removes only matching toasts', () => {
    const { toasts, showToast, dismissByType } = useToast()
    showToast('成功消息', 'success')
    showToast('警告消息', 'warning')
    showToast('错误消息', 'error')
    showToast('又一条成功', 'success')

    dismissByType('success')
    expect(toasts.value.length).toBe(2)
    expect(toasts.value.every(t => t.type !== 'success')).toBe(true)
    expect(toasts.value[0].type).toBe('warning')
    expect(toasts.value[1].type).toBe('error')
  })

  it('does not error when dismissing non-existent id', () => {
    const { toasts, showToast, dismissToast } = useToast()
    showToast('一条信息', 'info')
    expect(() => dismissToast(999999)).not.toThrow()
    expect(toasts.value.length).toBe(1)
  })

  it('does not error when dismissing by type that has no matches', () => {
    const { toasts, showToast, dismissByType } = useToast()
    showToast('只有 info', 'info')
    expect(() => dismissByType('error')).not.toThrow()
    expect(toasts.value.length).toBe(1)
  })

  it('enforces MAX_TOASTS (10) cap by evicting oldest', () => {
    const { toasts, showToast } = useToast()
    // Add 11 toasts (MAX_TOASTS + 1)
    for (let i = 1; i <= 11; i++) {
      showToast(`消息 ${i}`, 'info')
    }
    expect(toasts.value.length).toBe(10)
    // Oldest (消息 1) should be evicted, newest (消息 11) present
    expect(toasts.value[0].message).toBe('消息 2')
    expect(toasts.value[9].message).toBe('消息 11')
  })

  it('auto-dismisses toast after default 3000ms', () => {
    const { toasts, showToast } = useToast()
    showToast('短暂的消息', 'success')
    expect(toasts.value.length).toBe(1)

    // Advance time to just before dismissal
    vi.advanceTimersByTime(2999)
    expect(toasts.value.length).toBe(1)

    // Advance past 3000ms threshold
    vi.advanceTimersByTime(10)
    expect(toasts.value.length).toBe(0)
  })

  it('auto-dismisses toast after custom duration', () => {
    const { toasts, showToast } = useToast()
    showToast('5秒消息', 'info', 5000)
    expect(toasts.value.length).toBe(1)

    // Should still be there at 4s
    vi.advanceTimersByTime(4000)
    expect(toasts.value.length).toBe(1)

    // Should be gone after 5s
    vi.advanceTimersByTime(1100)
    expect(toasts.value.length).toBe(0)
  })

  it('dismissToast clears pending auto-dismiss timer', () => {
    const { toasts, showToast, dismissToast } = useToast()
    showToast('手动关闭', 'warning', 5000)
    expect(toasts.value.length).toBe(1)

    // Dismiss manually before timer fires
    dismissToast(toasts.value[0].id)
    expect(toasts.value.length).toBe(0)

    // Advance past the original timer — no crash
    vi.advanceTimersByTime(6000)
    // Still empty (no stale toast reappears)
    expect(toasts.value.length).toBe(0)
  })

  it('dismissByType clears pending auto-dismiss timers', () => {
    const { toasts, showToast, dismissByType } = useToast()
    showToast('错误消息', 'error', 5000)

    dismissByType('error')
    expect(toasts.value.length).toBe(0)

    // Advance past original timer — no crash
    vi.advanceTimersByTime(6000)
    expect(toasts.value.length).toBe(0)
  })

  it('generates unique ids for each toast', () => {
    const { toasts, showToast } = useToast()
    const ids = new Set()
    for (let i = 0; i < 20; i++) {
      showToast(`toast ${i}`, 'info', 100)
      if (toasts.value.length > 0) {
        ids.add(toasts.value[toasts.value.length - 1].id)
      }
      // Advance time so auto-dismiss fires and makes room
      vi.advanceTimersByTime(150)
    }
    // Should have seen unique ids
    // max 10 at once, but across time we should have no duplicates
    expect(ids.size).toBeGreaterThanOrEqual(10)
  })
})
