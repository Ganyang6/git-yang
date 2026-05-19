<template>
  <div class="layout" :class="{ 'sidebar-collapsed': sidebarCollapsed }">
    <!-- Sidebar -->
    <aside class="sidebar" :class="{ 'sidebar-open': sidebarOpen && isMobile }">
      <div class="sidebar-logo">
        <div class="logo-icon">
          <svg width="24" height="24" viewBox="0 0 24 24" fill="none">
            <rect x="2" y="3" width="8" height="8" rx="1.5" fill="#fff" opacity="0.9" />
            <rect x="14" y="3" width="8" height="8" rx="1.5" fill="#fff" opacity="0.7" />
            <rect x="2" y="14" width="8" height="8" rx="1.5" fill="#fff" opacity="0.7" />
            <rect x="14" y="14" width="8" height="8" rx="1.5" fill="#fff" opacity="0.5" />
          </svg>
        </div>
        <span class="logo-text">MES 制造系统</span>
        <button class="collapse-btn" @click="toggleSidebar">
          <svg
            width="16"
            height="16"
            viewBox="0 0 24 24"
            fill="none"
            stroke="currentColor"
            stroke-width="2"
          >
            <path d="M15 18l-6-6 6-6" />
          </svg>
        </button>
      </div>

      <nav class="sidebar-nav">
        <div class="nav-section">
          <span class="nav-section-label">工时测定</span>
          <router-link
            v-for="item in worktimeNav"
            :key="item.path"
            :to="item.path"
            class="nav-item"
            :title="item.title"
          >
            <NavIcon :elements="item.elements" />
            <span class="nav-label">{{ item.title }}</span>
            <span v-if="item.badge" class="nav-badge" :class="item.badgeClass || ''">{{
              item.badge
            }}</span>
          </router-link>
        </div>

        <div class="nav-section">
          <span class="nav-section-label">生产管理</span>
          <router-link
            v-for="item in mainNav"
            :key="item.path"
            :to="item.path"
            class="nav-item"
            :title="item.title"
          >
            <NavIcon :elements="item.elements" />
            <span class="nav-label">{{ item.title }}</span>
            <span v-if="item.badge" class="nav-badge">{{ item.badge }}</span>
          </router-link>
        </div>

        <div class="nav-section">
          <span class="nav-section-label">数据分析</span>
          <router-link
            v-for="item in reportNav"
            :key="item.path"
            :to="item.path"
            class="nav-item"
            :title="item.title"
          >
            <NavIcon :elements="item.elements" />
            <span class="nav-label">{{ item.title }}</span>
          </router-link>
        </div>
      </nav>

      <div class="sidebar-footer">
        <div class="user-info">
          <div class="avatar avatar-sm" :style="`background: #4a8ef9`">{{
            auth.user?.name ? auth.user.name[0] : '?'
          }}</div>
          <div class="user-details">
            <div class="user-name">{{ auth.user?.name || '未登录' }}</div>
            <div class="user-role">{{ auth.user?.role || '' }}</div>
          </div>
        </div>
      </div>
    </aside>

    <!-- Main Content -->
    <div class="main-wrapper">
      <!-- Header -->
      <header class="header">
        <div class="header-left">
          <button class="btn btn-ghost btn-icon mobile-menu-btn" @click="toggleSidebar">
            <svg
              width="18"
              height="18"
              viewBox="0 0 24 24"
              fill="none"
              stroke="currentColor"
              stroke-width="2"
            >
              <line x1="3" y1="6" x2="21" y2="6" />
              <line x1="3" y1="12" x2="21" y2="12" />
              <line x1="3" y1="18" x2="21" y2="18" />
            </svg>
          </button>
          <div class="breadcrumb">
            <span class="breadcrumb-home">首页</span>
            <span class="breadcrumb-sep">/</span>
            <span class="breadcrumb-current">{{ currentPageTitle }}</span>
          </div>
        </div>
        <div class="header-right">
          <div class="header-search">
            <svg
              width="15"
              height="15"
              viewBox="0 0 24 24"
              fill="none"
              stroke="currentColor"
              stroke-width="2"
            >
              <circle cx="11" cy="11" r="8" />
              <path d="m21 21-4.35-4.35" />
            </svg>
            <input type="text" placeholder="搜索订单、客户..." class="search-input" />
          </div>
          <button class="btn btn-ghost btn-icon header-action" title="消息通知">
            <svg
              width="18"
              height="18"
              viewBox="0 0 24 24"
              fill="none"
              stroke="currentColor"
              stroke-width="2"
            >
              <path d="M18 8A6 6 0 0 0 6 8c0 7-3 9-3 9h18s-3-2-3-9" />
              <path d="M13.73 21a2 2 0 0 1-3.46 0" />
            </svg>
            <span class="notification-dot"></span>
          </button>
          <button class="btn btn-ghost btn-icon header-action" title="全屏">
            <svg
              width="18"
              height="18"
              viewBox="0 0 24 24"
              fill="none"
              stroke="currentColor"
              stroke-width="2"
            >
              <path
                d="M8 3H5a2 2 0 0 0-2 2v3m18 0V5a2 2 0 0 0-2-2h-3m0 18h3a2 2 0 0 0 2-2v-3M3 16v3a2 2 0 0 0 2 2h3"
              />
            </svg>
          </button>
          <div class="header-avatar">
            <div
              class="avatar avatar-sm"
              :style="`background: linear-gradient(135deg, #1a6ef5, #6366f1)`"
            >
              {{ auth.user?.name ? auth.user.name[0] : '?' }}
            </div>
          </div>
        </div>
      </header>

      <!-- Page Content -->
      <main class="page-content">
        <router-view v-slot="{ Component }">
          <transition name="page" mode="out-in">
            <component :is="Component" />
          </transition>
        </router-view>
      </main>
    </div>

    <!-- Mobile Overlay -->
    <div v-if="sidebarOpen && isMobile" class="mobile-overlay" @click="closeSidebar"></div>
  </div>
</template>

<script setup>
import { h, defineComponent, ref, computed, onMounted, onUnmounted } from 'vue'
import { useRoute } from 'vue-router'
import { useAuthStore } from '../stores/auth.js'

// P1 #61: NavIcon -- 纯 VNode SVG 渲染组件，替代 v-html 模式
// icon 元素使用结构化对象，完全避免 innerHTML 解析
const NavIcon = defineComponent({
  name: 'NavIcon',
  props: {
    elements: { type: Array, required: true }
  },
  render() {
    return h('svg', {
      width: '18', height: '18', viewBox: '0 0 24 24',
      fill: 'none', stroke: 'currentColor', 'stroke-width': '2'
    }, this.elements.map((el, i) => h(el.tag, { key: i, ...el.attrs })))
  }
})

const route = useRoute()
const auth = useAuthStore()
const sidebarCollapsed = ref(false)
const sidebarOpen = ref(false)
const isMobile = ref(false)

const currentPageTitle = computed(() => {
  const allNav = [...worktimeNav, ...mainNav, ...reportNav]
  const item = allNav.find(n => route.path.startsWith(n.path))
  return item ? item.title : '概览'
})

function toggleSidebar() {
  if (isMobile.value) {
    sidebarOpen.value = !sidebarOpen.value
  } else {
    sidebarCollapsed.value = !sidebarCollapsed.value
  }
}

function closeSidebar() {
  sidebarOpen.value = false
}

function checkMobile() {
  isMobile.value = window.innerWidth < 768
}

let mql = null
onMounted(() => {
  mql = window.matchMedia('(max-width: 768px)')
  mql.addEventListener('change', (e) => { isMobile.value = e.matches })
  isMobile.value = mql.matches
})

onMounted(() => {
  // already handled by matchMedia above
})

onUnmounted(() => {
  if (mql) mql.removeEventListener('change', () => {})
  closeSidebar()
})

// P1 #61: 结构化 SVG icon 数据，替代 v-html 字符串
const worktimeNav = [
  {
    path: '/dashboard', title: '生产看板',
    elements: [
      { tag: 'rect', attrs: { x: 3, y: 3, width: 7, height: 7, rx: 1 } },
      { tag: 'rect', attrs: { x: 14, y: 3, width: 7, height: 7, rx: 1 } },
      { tag: 'rect', attrs: { x: 3, y: 14, width: 7, height: 7, rx: 1 } },
      { tag: 'rect', attrs: { x: 14, y: 14, width: 7, height: 7, rx: 1 } }
    ]
  },
  {
    path: '/worktime', title: '工时分析',
    elements: [
      { tag: 'circle', attrs: { cx: 12, cy: 12, r: 10 } },
      { tag: 'polyline', attrs: { points: '12 6 12 12 16 14' } }
    ]
  },
  {
    path: '/line-balance', title: '线平衡', badge: '新', badgeClass: 'badge-green',
    elements: [
      { tag: 'line', attrs: { x1: 18, y1: 20, x2: 18, y2: 10 } },
      { tag: 'line', attrs: { x1: 12, y1: 20, x2: 12, y2: 4 } },
      { tag: 'line', attrs: { x1: 6, y1: 20, x2: 6, y2: 14 } }
    ]
  },
  {
    path: '/ai-analysis', title: 'AI深度分析', badge: 'AI', badgeClass: 'badge-ai',
    elements: [
      { tag: 'path', attrs: { d: 'M12 2a10 10 0 1 0 10 10' } },
      { tag: 'path', attrs: { d: 'M12 12l4-4' } },
      { tag: 'circle', attrs: { cx: 18, cy: 6, r: 3 } }
    ]
  },
  {
    path: '/video-analysis', title: 'Video Analysis', badge: 'New', badgeClass: 'badge-green',
    elements: [
      { tag: 'polygon', attrs: { points: '23 7 16 12 23 17 23 7' } },
      { tag: 'rect', attrs: { x: 1, y: 5, width: 15, height: 14, rx: 2, ry: 2 } }
    ]
  }
]

const mainNav = [
  {
    path: '/orders', title: '生产订单',
    elements: [
      { tag: 'path', attrs: { d: 'M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z' } },
      { tag: 'polyline', attrs: { points: '14 2 14 8 20 8' } },
      { tag: 'line', attrs: { x1: 16, y1: 13, x2: 8, y2: 13 } },
      { tag: 'line', attrs: { x1: 16, y1: 17, x2: 8, y2: 17 } },
      { tag: 'polyline', attrs: { points: '10 9 9 9 8 9' } }
    ]
  },
  {
    path: '/customers', title: '客户管理',
    elements: [
      { tag: 'path', attrs: { d: 'M17 21v-2a4 4 0 0 0-4-4H5a4 4 0 0 0-4 4v2' } },
      { tag: 'circle', attrs: { cx: 9, cy: 7, r: 4 } },
      { tag: 'path', attrs: { d: 'M23 21v-2a4 4 0 0 0-3-3.87' } },
      { tag: 'path', attrs: { d: 'M16 3.13a4 4 0 0 1 0 7.75' } }
    ]
  },
  {
    path: '/inventory', title: '库存管理',
    elements: [
      { tag: 'path', attrs: { d: 'M21 16V8a2 2 0 0 0-1-1.73l-7-4a2 2 0 0 0-2 0l-7 4A2 2 0 0 0 3 8v8a2 2 0 0 0 1 1.73l7 4a2 2 0 0 0 2 0l7-4A2 2 0 0 0 21 16z' } },
      { tag: 'polyline', attrs: { points: '3.27 6.96 12 12.01 20.73 6.96' } },
      { tag: 'line', attrs: { x1: 12, y1: 22.08, x2: 12, y2: 12 } }
    ]
  },
  {
    path: '/equipment', title: '设备管理',
    elements: [
      { tag: 'circle', attrs: { cx: 12, cy: 12, r: 3 } },
      { tag: 'path', attrs: { d: 'M19.07 4.93l-1.41 1.41' } },
      { tag: 'path', attrs: { d: 'M5.34 17.66l-1.41 1.41' } },
      { tag: 'line', attrs: { x1: 20.49, y1: 12, x2: 22 } },
      { tag: 'line', attrs: { x1: 2, y1: 12, x2: 1.51 } },
      { tag: 'path', attrs: { d: 'M17.66 18.66l1.41 1.41' } },
      { tag: 'path', attrs: { d: 'M4.93 4.93l1.41 1.41' } },
      { tag: 'line', attrs: { x1: 12, y1: 22, x2: 12, y2: 20.49 } },
      { tag: 'line', attrs: { x1: 12, y1: 3.51, x2: 12, y2: 2 } }
    ]
  }
]

const reportNav = [
  {
    path: '/reports', title: '报表分析',
    elements: [
      { tag: 'line', attrs: { x1: 18, y1: 20, x2: 18, y2: 10 } },
      { tag: 'line', attrs: { x1: 12, y1: 20, x2: 12, y2: 4 } },
      { tag: 'line', attrs: { x1: 6, y1: 20, x2: 6, y2: 14 } }
    ]
  }
]
</script>

<style scoped>
.layout {
  display: flex;
  height: 100vh;
  overflow: hidden;
  background: var(--gray-50);
}

/* ===== Sidebar ===== */
.sidebar {
  width: var(--sidebar-width);
  background: linear-gradient(180deg, #0f1a35 0%, #1a2848 100%);
  display: flex;
  flex-direction: column;
  flex-shrink: 0;
  transition: width 0.3s cubic-bezier(0.4, 0, 0.2, 1);
  overflow: hidden;
  position: relative;
  z-index: 100;
}

.sidebar-logo {
  display: flex;
  align-items: center;
  gap: 10px;
  padding: 18px 16px;
  border-bottom: 1px solid rgba(255, 255, 255, 0.08);
  flex-shrink: 0;
  min-height: var(--header-height);
}

.logo-icon {
  width: 32px;
  height: 32px;
  background: var(--primary);
  border-radius: 8px;
  display: flex;
  align-items: center;
  justify-content: center;
  flex-shrink: 0;
}

.logo-text {
  font-size: 15px;
  font-weight: 700;
  color: #fff;
  white-space: nowrap;
  overflow: hidden;
  transition: var(--transition);
}

.collapse-btn {
  margin-left: auto;
  width: 24px;
  height: 24px;
  background: rgba(255, 255, 255, 0.08);
  border: none;
  border-radius: 6px;
  color: rgba(255, 255, 255, 0.6);
  cursor: pointer;
  display: flex;
  align-items: center;
  justify-content: center;
  flex-shrink: 0;
  transition: var(--transition-fast);
}
.collapse-btn:hover {
  background: rgba(255, 255, 255, 0.15);
  color: #fff;
}

.sidebar-nav {
  flex: 1;
  overflow-y: auto;
  padding: 12px 10px;
}

.nav-section {
  margin-bottom: 8px;
}

.nav-section-label {
  display: block;
  font-size: 10px;
  font-weight: 600;
  color: rgba(255, 255, 255, 0.35);
  text-transform: uppercase;
  letter-spacing: 0.08em;
  padding: 8px 8px 4px;
  white-space: nowrap;
  overflow: hidden;
  transition: var(--transition);
}

.nav-item {
  display: flex;
  align-items: center;
  gap: 10px;
  padding: 9px 10px;
  border-radius: 8px;
  color: rgba(255, 255, 255, 0.65);
  text-decoration: none;
  margin-bottom: 2px;
  transition: var(--transition-fast);
  position: relative;
  white-space: nowrap;
  overflow: hidden;
}
.nav-item:hover {
  background: rgba(255, 255, 255, 0.08);
  color: #fff;
}
.nav-item.router-link-active {
  background: var(--primary);
  color: #fff;
  box-shadow: 0 4px 12px rgba(26, 110, 245, 0.35);
}

.nav-icon {
  width: 18px;
  height: 18px;
  display: flex;
  align-items: center;
  justify-content: center;
  flex-shrink: 0;
}

.nav-label {
  font-size: var(--font-size-sm);
  font-weight: 500;
  overflow: hidden;
  transition: var(--transition);
}

.nav-badge {
  margin-left: auto;
  background: var(--danger);
  color: #fff;
  font-size: 10px;
  font-weight: 700;
  padding: 1px 6px;
  border-radius: 10px;
  flex-shrink: 0;
}
.badge-green {
  background: var(--success);
}
.badge-ai {
  background: linear-gradient(135deg, #6366f1, #8b5cf6);
}

.sidebar-footer {
  padding: 12px 10px;
  border-top: 1px solid rgba(255, 255, 255, 0.08);
}

.user-info {
  display: flex;
  align-items: center;
  gap: 10px;
  padding: 8px;
  border-radius: 8px;
  cursor: pointer;
  transition: var(--transition-fast);
  overflow: hidden;
}
.user-info:hover {
  background: rgba(255, 255, 255, 0.08);
}

.user-details {
  overflow: hidden;
}

.user-name {
  font-size: var(--font-size-sm);
  font-weight: 600;
  color: #fff;
  white-space: nowrap;
}
.user-role {
  font-size: var(--font-size-xs);
  color: rgba(255, 255, 255, 0.45);
  white-space: nowrap;
}

/* ===== Collapsed Sidebar ===== */
.sidebar-collapsed .sidebar {
  width: var(--sidebar-collapsed);
}
.sidebar-collapsed .logo-text,
.sidebar-collapsed .nav-label,
.sidebar-collapsed .nav-section-label,
.sidebar-collapsed .nav-badge,
.sidebar-collapsed .user-details {
  opacity: 0;
  width: 0;
  overflow: hidden;
}
.sidebar-collapsed .collapse-btn {
  transform: rotate(180deg);
}

/* ===== Header ===== */
.main-wrapper {
  flex: 1;
  display: flex;
  flex-direction: column;
  overflow: hidden;
  min-width: 0;
}

.header {
  height: var(--header-height);
  background: #fff;
  border-bottom: 1px solid var(--gray-200);
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 0 20px;
  flex-shrink: 0;
  gap: 16px;
}

.header-left {
  display: flex;
  align-items: center;
  gap: 12px;
}

.mobile-menu-btn {
  display: none;
}

.breadcrumb {
  display: flex;
  align-items: center;
  gap: 6px;
  font-size: var(--font-size-sm);
}
.breadcrumb-home {
  color: var(--gray-400);
}
.breadcrumb-sep {
  color: var(--gray-300);
}
.breadcrumb-current {
  color: var(--gray-700);
  font-weight: 500;
}

.header-right {
  display: flex;
  align-items: center;
  gap: 8px;
}

.header-search {
  display: flex;
  align-items: center;
  gap: 8px;
  background: var(--gray-50);
  border: 1px solid var(--gray-200);
  border-radius: 8px;
  padding: 0 12px;
  height: 34px;
  color: var(--gray-400);
}
.search-input {
  border: none;
  background: transparent;
  outline: none;
  font-size: var(--font-size-sm);
  color: var(--gray-700);
  width: 180px;
}
.search-input::placeholder {
  color: var(--gray-400);
}

.header-action {
  position: relative;
}

.notification-dot {
  position: absolute;
  top: 6px;
  right: 6px;
  width: 7px;
  height: 7px;
  background: var(--danger);
  border-radius: 50%;
  border: 1.5px solid #fff;
}

.header-avatar {
  cursor: pointer;
}

/* ===== Page Content ===== */
.page-content {
  flex: 1;
  overflow-y: auto;
  padding: 24px;
}

/* ===== Mobile Overlay ===== */
.mobile-overlay {
  display: none;
  position: fixed;
  inset: 0;
  background: rgba(0, 0, 0, 0.5);
  z-index: 99;
}

/* ===== Page Transition ===== */
.page-enter-active,
.page-leave-active {
  transition: all 0.2s ease;
}
.page-enter-from {
  opacity: 0;
  transform: translateY(8px);
}
.page-leave-to {
  opacity: 0;
  transform: translateY(-4px);
}

/* ===== Responsive ===== */
@media (max-width: 768px) {
  .sidebar {
    position: fixed;
    top: 0;
    left: 0;
    height: 100%;
    transform: translateX(-100%);
    transition: transform 0.3s cubic-bezier(0.4, 0, 0.2, 1);
    z-index: 200;
    width: var(--sidebar-width) !important;
  }
  .sidebar.sidebar-open {
    transform: translateX(0);
  }
  .layout.sidebar-collapsed .sidebar {
    width: var(--sidebar-width) !important;
  }
  .mobile-menu-btn {
    display: flex;
  }
  .header-search {
    display: none;
  }
  .page-content {
    padding: 16px;
  }
  .mobile-overlay {
    display: block;
  }
}
</style>
