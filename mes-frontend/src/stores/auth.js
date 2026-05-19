/**
 * Auth Store - Pinia 全局认证状态管理
 *
 * 职责：
 *   - 管理 JWT token 持久化（localStorage）
 *   - 管理当前用户信息
 *   - 提供 isLoggedIn / logout 等便捷方法
 */

import { defineStore } from 'pinia'
import { ref, computed } from 'vue'
import { setAuthToken, getAuthToken, fetchCurrentUser } from '../api/index.js'

const TOKEN_KEY = 'mes_auth_token'

export const useAuthStore = defineStore('auth', () => {
  const token = ref(localStorage.getItem(TOKEN_KEY) || sessionStorage.getItem(TOKEN_KEY) || null)
  const user = ref(null)

  const isLoggedIn = computed(() => !!token.value)

  function setToken(t) {
    token.value = t
    setAuthToken(t)
    if (t) {
      localStorage.setItem(TOKEN_KEY, t)
    } else {
      localStorage.removeItem(TOKEN_KEY)
    }
  }

  function setUser(u) {
    user.value = u
  }

  async function restore() {
    const saved = localStorage.getItem(TOKEN_KEY) || sessionStorage.getItem(TOKEN_KEY)
    if (saved) {
      token.value = saved
      setAuthToken(saved)
      try {
        const data = await fetchCurrentUser()
        setUser(data)
      } catch (err) {
        console.warn('[auth] restore failed:', err.message)
        logout()
      }
    }
  }

  function logout() {
    setToken(null)
    setUser(null)
  }

  return {
    token,
    user,
    isLoggedIn,
    setToken,
    setUser,
    restore,
    logout
  }
})
