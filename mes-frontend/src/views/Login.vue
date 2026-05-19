<template>
  <div class="login-page">
    <div class="login-bg">
      <div class="bg-circle bg-circle-1"></div>
      <div class="bg-circle bg-circle-2"></div>
    </div>
    <div class="login-left">
      <div class="login-brand">
        <div class="brand-icon">
          <svg width="32" height="32" viewBox="0 0 24 24" fill="none">
            <rect x="2" y="3" width="8" height="8" rx="1.5" fill="#fff" opacity="0.9" />
            <rect x="14" y="3" width="8" height="8" rx="1.5" fill="#fff" opacity="0.7" />
            <rect x="2" y="14" width="8" height="8" rx="1.5" fill="#fff" opacity="0.7" />
            <rect x="14" y="14" width="8" height="8" rx="1.5" fill="#fff" opacity="0.5" />
          </svg>
        </div>
        <span class="brand-name">MES 制造执行系统</span>
      </div>
      <div class="login-intro">
        <h1 class="intro-title">智慧制造，精益管理</h1>
        <p class="intro-desc">
          专为中小型离散制造企业打造的一体化管理平台，覆盖生产、库存、设备、质量全流程。
        </p>
        <div class="intro-features">
          <div v-for="f in features" :key="f" class="intro-feature">
            <svg
              width="16"
              height="16"
              viewBox="0 0 24 24"
              fill="none"
              stroke="currentColor"
              stroke-width="2.5"
            >
              <polyline points="20 6 9 17 4 12" />
            </svg>
            {{ f }}
          </div>
        </div>
      </div>
    </div>
    <div class="login-right">
      <div class="login-card">
        <div class="login-header">
          <div class="login-title">欢迎回来</div>
          <div class="login-subtitle">请登录您的账号</div>
        </div>
        <form @submit.prevent="handleLogin">
          <div class="form-group">
            <label class="form-label">账号</label>
            <div class="input-with-icon">
              <svg
                width="16"
                height="16"
                viewBox="0 0 24 24"
                fill="none"
                stroke="currentColor"
                stroke-width="2"
              >
                <path d="M20 21v-2a4 4 0 0 0-4-4H8a4 4 0 0 0-4 4v2" />
                <circle cx="12" cy="7" r="4" />
              </svg>
              <input
                v-model="username"
                type="text"
                class="input input-icon"
                placeholder="请输入账号"
              />
            </div>
          </div>
          <div class="form-group">
            <label class="form-label">
              密码
            </label>
            <div class="input-with-icon">
              <svg
                width="16"
                height="16"
                viewBox="0 0 24 24"
                fill="none"
                stroke="currentColor"
                stroke-width="2"
              >
                <rect x="3" y="11" width="18" height="11" rx="2" ry="2" />
                <path d="M7 11V7a5 5 0 0 1 10 0v4" />
              </svg>
              <input
                v-model="password"
                :type="showPwd ? 'text' : 'password'"
                class="input input-icon input-icon-right"
                placeholder="请输入密码"
              />
              <button type="button" class="pwd-toggle" @click="showPwd = !showPwd">
                <svg
                  v-if="showPwd"
                  width="16"
                  height="16"
                  viewBox="0 0 24 24"
                  fill="none"
                  stroke="currentColor"
                  stroke-width="2"
                >
                  <path
                    d="M17.94 17.94A10.07 10.07 0 0 1 12 20c-7 0-11-8-11-8a18.45 18.45 0 0 1 5.06-5.94M9.9 4.24A9.12 9.12 0 0 1 12 4c7 0 11 8 11 8a18.5 18.5 0 0 1-2.16 3.19m-6.72-1.07a3 3 0 1 1-4.24-4.24"
                  />
                  <line x1="1" y1="1" x2="23" y2="23" />
                </svg>
                <svg
                  v-else
                  width="16"
                  height="16"
                  viewBox="0 0 24 24"
                  fill="none"
                  stroke="currentColor"
                  stroke-width="2"
                >
                  <path d="M1 12s4-8 11-8 11 8 11 8-4 8-11 8-11-8-11-8z" />
                  <circle cx="12" cy="12" r="3" />
                </svg>
              </button>
            </div>
          </div>
          <div class="form-options">
            <label class="checkbox-label">
              <input v-model="remember" type="checkbox" /> 记住我
            </label>
          </div>
          <button type="submit" class="btn btn-primary w-full login-btn" :disabled="loading">
            <span v-if="loading" class="loading-spinner"></span>
            <span v-else>登录</span>
          </button>
          <div v-if="errorMsg" style="color: var(--danger); font-size: 13px; margin-top: 8px; text-align: center">
            {{ errorMsg }}
          </div>
        </form>
        <div class="login-hint">
          <span style="color: var(--gray-400)"></span>
          <span></span>
        </div>
      </div>
    </div>
  </div>
</template>

<script setup>
import { ref } from 'vue'
import { useRouter } from 'vue-router'
import { login as apiLogin } from '../api/index.js'
import { useAuthStore } from '../stores/auth.js'

const router = useRouter()
const authStore = useAuthStore()
const username = ref('')
const password = ref('')
const showPwd = ref(false)
const remember = ref(true)
const loading = ref(false)
const errorMsg = ref('')

const features = ['实时生产看板', '生产订单全程追踪', '库存预警管理', '设备OEE监控', '多维报表分析']

async function handleLogin() {
  if (!username.value || !password.value) {
    errorMsg.value = '请输入账号和密码'
    return
  }
  loading.value = true
  errorMsg.value = ''
  try {
    const data = await apiLogin(username.value, password.value)
    const token = data.token || data.access_token
    if (token) {
      // Persist token via Pinia store (localStorage + in-memory)
      authStore.setToken(token)
      if (!remember.value) {
        // P2-2: session-only storage for "don't remember me"
        sessionStorage.setItem('mes_auth_token', token)
      }
      if (data.user) {
        authStore.setUser(data.user)
      }
      router.push('/')
    } else {
      errorMsg.value = '登录失败：未获取到令牌'
    }
  } catch (err) {
    errorMsg.value = err.message || '账号或密码错误'
  } finally {
    loading.value = false
  }
}
</script>

<style scoped>
.login-page {
  min-height: 100vh;
  display: flex;
  position: relative;
  overflow: hidden;
}

.login-bg {
  position: fixed;
  inset: 0;
  background: linear-gradient(135deg, #0f1a35 0%, #1a2848 60%, #1a3060 100%);
  z-index: 0;
}

.bg-circle {
  position: absolute;
  border-radius: 50%;
  opacity: 0.12;
}
.bg-circle-1 {
  width: 600px;
  height: 600px;
  background: radial-gradient(circle, #1a6ef5, transparent);
  top: -200px;
  left: -100px;
}
.bg-circle-2 {
  width: 400px;
  height: 400px;
  background: radial-gradient(circle, #6366f1, transparent);
  bottom: -100px;
  right: 200px;
}

.login-left {
  flex: 1;
  display: flex;
  flex-direction: column;
  justify-content: center;
  padding: 60px 80px;
  position: relative;
  z-index: 1;
}

.login-brand {
  display: flex;
  align-items: center;
  gap: 12px;
  margin-bottom: 60px;
}
.brand-icon {
  width: 48px;
  height: 48px;
  background: var(--primary);
  border-radius: 12px;
  display: flex;
  align-items: center;
  justify-content: center;
}
.brand-name {
  font-size: 18px;
  font-weight: 700;
  color: #fff;
}

.intro-title {
  font-size: 40px;
  font-weight: 800;
  color: #fff;
  line-height: 1.2;
  margin-bottom: 16px;
}
.intro-desc {
  font-size: 16px;
  color: rgba(255, 255, 255, 0.65);
  line-height: 1.6;
  max-width: 440px;
  margin-bottom: 32px;
}
.intro-features {
  display: flex;
  flex-direction: column;
  gap: 12px;
}
.intro-feature {
  display: flex;
  align-items: center;
  gap: 10px;
  color: rgba(255, 255, 255, 0.8);
  font-size: 15px;
}
.intro-feature svg {
  color: #10b981;
  flex-shrink: 0;
}

.login-right {
  width: 480px;
  display: flex;
  align-items: center;
  justify-content: center;
  padding: 40px;
  position: relative;
  z-index: 1;
}

.login-card {
  width: 100%;
  background: #fff;
  border-radius: 20px;
  padding: 40px;
  box-shadow: 0 20px 60px rgba(0, 0, 0, 0.3);
}

.login-header {
  margin-bottom: 28px;
}
.login-title {
  font-size: 26px;
  font-weight: 700;
  color: var(--gray-900);
  margin-bottom: 6px;
}
.login-subtitle {
  font-size: var(--font-size-sm);
  color: var(--gray-400);
}

.form-label {
  display: flex;
  align-items: center;
  justify-content: space-between;
}
.forgot-link {
  font-size: var(--font-size-xs);
  color: var(--primary);
  text-decoration: none;
}

.input-with-icon {
  position: relative;
}
.input-with-icon > svg:first-child {
  position: absolute;
  left: 12px;
  top: 50%;
  transform: translateY(-50%);
  color: var(--gray-400);
  pointer-events: none;
}
.input-icon {
  padding-left: 38px;
}
.input-icon-right {
  padding-right: 38px;
}
.pwd-toggle {
  position: absolute;
  right: 10px;
  top: 50%;
  transform: translateY(-50%);
  background: none;
  border: none;
  cursor: pointer;
  color: var(--gray-400);
  padding: 4px;
  display: flex;
  align-items: center;
}
.pwd-toggle:hover {
  color: var(--gray-600);
}

.form-options {
  margin: 12px 0 20px;
}
.checkbox-label {
  display: flex;
  align-items: center;
  gap: 6px;
  font-size: var(--font-size-sm);
  color: var(--gray-500);
  cursor: pointer;
}

.login-btn {
  height: 44px;
  font-size: 15px;
  justify-content: center;
}

.login-hint {
  text-align: center;
  font-size: var(--font-size-xs);
  color: var(--gray-400);
  margin-top: 20px;
}
.login-hint span {
  color: var(--primary);
  font-weight: 600;
}

@media (max-width: 900px) {
  .login-left {
    display: none;
  }
  .login-right {
    width: 100%;
    padding: 20px;
  }
  .login-card {
    max-width: 420px;
  }
}
</style>
