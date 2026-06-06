/**
 * Auth store unit tests
 *
 * Covers:
 *   - initial state from localStorage
 *   - setToken: updates ref, API layer, and localStorage
 *   - setUser: updates user ref
 *   - isLoggedIn computed
 *   - logout: clears token and user
 *   - restore: fetches user from API, or logs out on failure
 */

import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest'
import { setActivePinia, createPinia } from 'pinia'
import { useAuthStore } from './auth.js'

// Mock the API module that auth store depends on
vi.mock('../api/index.js', () => ({
  setAuthToken: vi.fn(),
  getAuthToken: vi.fn(() => null),
  fetchCurrentUser: vi.fn(() =>
    Promise.resolve({ id: 1, name: 'Admin', role: 'admin' })
  )
}))

// Import the mocked functions so we can assert on them
import { setAuthToken, getAuthToken, fetchCurrentUser } from '../api/index.js'

describe('auth store', () => {
  beforeEach(() => {
    const mockStorage = {}
    const mockSessionStorage = {}
    Object.defineProperty(window, 'localStorage', {
      value: {
        getItem: vi.fn(k => mockStorage[k] ?? null),
        setItem: vi.fn((k, v) => { mockStorage[k] = v }),
        removeItem: vi.fn(k => { delete mockStorage[k] }),
        clear: vi.fn(() => { Object.keys(mockStorage).forEach(k => delete mockStorage[k]) }),
      },
      writable: true,
    })
    Object.defineProperty(window, 'sessionStorage', {
      value: {
        getItem: vi.fn(k => mockSessionStorage[k] ?? null),
        setItem: vi.fn((k, v) => { mockSessionStorage[k] = v }),
        removeItem: vi.fn(k => { delete mockSessionStorage[k] }),
        clear: vi.fn(() => { Object.keys(mockSessionStorage).forEach(k => delete mockSessionStorage[k]) }),
      },
      writable: true,
    })
    setActivePinia(createPinia())
    localStorage.clear()
    sessionStorage.clear()
    vi.clearAllMocks()
  })

  afterEach(() => {
    vi.restoreAllMocks()
  })

  it('initializes token from localStorage', () => {
    localStorage.setItem('mes_auth_token', 'stored-jwt')
    const store = useAuthStore()
    expect(store.token).toBe('stored-jwt')
    expect(store.isLoggedIn).toBe(true)
  })

  it('initializes with null when localStorage is empty', () => {
    const store = useAuthStore()
    expect(store.token).toBeNull()
    expect(store.isLoggedIn).toBe(false)
    expect(store.user).toBeNull()
  })

  describe('setToken', () => {
    it('updates token ref and calls setAuthToken API helper', () => {
      const store = useAuthStore()
      store.setToken('new-jwt')
      expect(store.token).toBe('new-jwt')
      expect(setAuthToken).toHaveBeenCalledWith('new-jwt')
      expect(localStorage.getItem('mes_auth_token')).toBe('new-jwt')
    })

    it('clears token and localStorage when null is passed', () => {
      const store = useAuthStore()
      store.setToken('temp')
      store.setToken(null)
      expect(store.token).toBeNull()
      expect(setAuthToken).toHaveBeenCalledWith(null)
      expect(localStorage.getItem('mes_auth_token')).toBeNull()
    })
  })

  describe('setUser', () => {
    it('updates user ref', () => {
      const store = useAuthStore()
      const user = { id: 5, name: 'Zhang', role: 'operator' }
      store.setUser(user)
      expect(store.user).toEqual(user)
    })
  })

  describe('isLoggedIn', () => {
    it('returns true when token is set', () => {
      const store = useAuthStore()
      store.setToken('jwt')
      expect(store.isLoggedIn).toBe(true)
    })

    it('returns false when token is null', () => {
      const store = useAuthStore()
      expect(store.isLoggedIn).toBe(false)
    })
  })

  describe('logout', () => {
    it('clears both token and user', () => {
      const store = useAuthStore()
      store.setToken('jwt')
      store.setUser({ id: 1 })
      store.logout()
      expect(store.token).toBeNull()
      expect(store.user).toBeNull()
      expect(store.isLoggedIn).toBe(false)
      expect(localStorage.getItem('mes_auth_token')).toBeNull()
    })

    it('clears sessionStorage on logout', () => {
      // Simulate token stored in sessionStorage (e.g. 'do not remember me')
      sessionStorage.setItem('mes_auth_token', 'session-jwt')

      const store = useAuthStore()
      expect(store.token).toBe('session-jwt')

      store.logout()

      expect(store.token).toBeNull()
      expect(store.isLoggedIn).toBe(false)
      // sessionStorage must also be cleared
      expect(sessionStorage.getItem('mes_auth_token')).toBeNull()
    })
  })

  describe('restore', () => {
    it('does nothing when no token is saved', async () => {
      const store = useAuthStore()
      await store.restore()
      expect(fetchCurrentUser).not.toHaveBeenCalled()
      expect(store.user).toBeNull()
    })

    it('fetches user info when token exists', async () => {
      localStorage.setItem('mes_auth_token', 'saved-jwt')
      const store = useAuthStore()
      await store.restore()
      expect(fetchCurrentUser).toHaveBeenCalled()
      expect(store.user).toEqual({ id: 1, name: 'Admin', role: 'admin' })
    })

    it('reads token from sessionStorage when localStorage is empty', async () => {
      // localStorage is empty from beforeEach — no token anywhere
      const store = useAuthStore()
      await store.restore()
      expect(fetchCurrentUser).not.toHaveBeenCalled()
      expect(store.user).toBeNull()
      // Now set token only in sessionStorage — simulate 'don\'t remember me'
      sessionStorage.setItem('mes_auth_token', 'session-jwt')
      const store2 = useAuthStore()
      await store2.restore()
      // Restore should find the token in sessionStorage
      expect(fetchCurrentUser).toHaveBeenCalled()
      expect(store2.user).toEqual({ id: 1, name: 'Admin', role: 'admin' })
    })

    it('logs out when fetchCurrentUser fails', async () => {
      getAuthToken.mockReturnValueOnce('saved-jwt')
      fetchCurrentUser.mockRejectedValueOnce(new Error('401'))
      const store = useAuthStore()
      store.setToken('saved-jwt')
      await store.restore()
      expect(store.token).toBeNull()
      expect(store.user).toBeNull()
      expect(store.isLoggedIn).toBe(false)
    })
  })
})
