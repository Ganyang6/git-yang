/**
 * useConfirm composable tests
 *
 * Tests: Promise leak prevention (P1-3) — concurrent calls must not
 * overwrite a pending _resolve, and must reject/error the first one.
 */

import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest'

// Helper: returns a promise that rejects after ms milliseconds
function timeoutPromise(ms) {
  return new Promise((_, reject) => setTimeout(() => reject(new Error('TIMEOUT')), ms))
}

describe('useConfirm', () => {
  beforeEach(() => {
    vi.resetModules()
  })

  it('should resolve true via handleConfirm', async () => {
    const { useConfirm } = await import('../../src/composables/useConfirm.js')
    const { openConfirm, handleConfirm } = useConfirm()

    const promise = openConfirm({ title: 'Test', message: 'Proceed?' })
    handleConfirm()

    const result = await promise
    expect(result).toBe(true)
  })

  it('should resolve false via handleCancel', async () => {
    const { useConfirm } = await import('../../src/composables/useConfirm.js')
    const { openConfirm, handleCancel } = useConfirm()

    const promise = openConfirm({ title: 'Test', message: 'Cancel?' })
    handleCancel()

    const result = await promise
    expect(result).toBe(false)
  })

  it('should reject/stage_error when a second concurrent openConfirm is called (P1-3 fix)', async () => {
    const { useConfirm } = await import('../../src/composables/useConfirm.js')
    const { openConfirm, handleConfirm } = useConfirm()

    const firstPromise = openConfirm({ title: 'First', message: 'First call' })

    // In the FIXED version, second openConfirm() should reject or throw
    // We catch the error if it throws, or wait for rejection with timeout
    let secondError = null
    try {
      await Promise.race([
        openConfirm({ title: 'Second', message: 'Second call' }),
        timeoutPromise(500)
      ])
    } catch (err) {
      secondError = err
    }

    // The second call should cause an error (either thrown or rejected first promise)
    // If no error, the first promise is leaking — fail
    if (!secondError) {
      // Maybe the fix returns the same promise — verify first promise still works
      handleConfirm()
      const result = await firstPromise
      expect(result).toBe(true)
    } else {
      // Error was produced — either thrown sync or promise rejected
      expect(secondError).toBeTruthy()
      // First promise should also be settled (either rejected or resolved)
      // Use race with timeout — the fix should have settled it
      const firstError = await Promise.race([
        firstPromise.then(() => null, err => err),
        timeoutPromise(500)
      ])
      expect(firstError).not.toBe('TIMEOUT')
    }
  })

  it('should not cause the first promise to leak permanently when second openConfirm is called', async () => {
    const { useConfirm } = await import('../../src/composables/useConfirm.js')
    const { openConfirm, handleConfirm } = useConfirm()

    const firstPromise = openConfirm({ title: 'First', message: 'First call' })

    // Call openConfirm a second time — in fixed version this should reject
    // the first promise or throw
    let threw = false
    try {
      const secondPromise = openConfirm({ title: 'Second', message: 'Second call' })
      // Resolve the second one
      handleConfirm()
      await secondPromise
    } catch {
      threw = true
    }

    // After the second call is resolved, the first promise must also be settled
    const firstSettled = await Promise.race([
      firstPromise.then(
        () => 'resolved',
        () => 'rejected'
      ),
      timeoutPromise(500)
    ])

    // If this is 'TIMEOUT', the first promise leaked
    expect(firstSettled).not.toBe('TIMEOUT')
  })
})
