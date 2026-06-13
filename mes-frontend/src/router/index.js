import { createRouter, createWebHashHistory } from 'vue-router'
import MainLayout from '@/layouts/MainLayout.vue'

const routes = [
  {
    path: '/',
    component: MainLayout,
    redirect: '/dashboard',
    meta: { requiresAuth: true },
    children: [
      {
        path: 'dashboard',
        name: 'Dashboard',
        component: () => import('@/views/Dashboard.vue'),
        meta: { title: '生产看板' }
      },
      {
        path: 'worktime',
        name: 'WorktimeAnalysis',
        component: () => import('@/views/WorktimeAnalysis.vue'),
        meta: { title: '工时分析' }
      },
      {
        path: 'line-balance',
        name: 'LineBalance',
        component: () => import('@/views/LineBalance.vue'),
        meta: { title: '线平衡' }
      },
      {
        path: 'ai-analysis',
        name: 'AiAnalysis',
        component: () => import('@/views/AiAnalysis.vue'),
        meta: { title: 'AI分析' }
      },
      {
        path: 'orders',
        name: 'Orders',
        component: () => import('@/views/Orders.vue'),
        meta: { title: '生产订单' }
      },
      {
        path: 'customers',
        name: 'Customers',
        component: () => import('@/views/Customers.vue'),
        meta: { title: '客户管理' }
      },
      {
        path: 'inventory',
        name: 'Inventory',
        component: () => import('@/views/Inventory.vue'),
        meta: { title: '库存管理' }
      },
      {
        path: 'stations',
        name: 'Stations',
        component: () => import('@/views/Stations.vue'),
        meta: { title: '工位管理' }
      },
      {
        path: 'equipment',
        name: 'Equipment',
        component: () => import('@/views/Equipment.vue'),
        meta: { title: '设备管理' }
      },
      {
        path: 'video-analysis',
        name: 'VideoAnalysis',
        component: () => import('@/views/VideoAnalysis.vue'),
        meta: { title: '视频分析' }
      },
      {
        path: 'reports',
        name: 'Reports',
        component: () => import('@/views/Reports.vue'),
        meta: { title: '报表分析' }
      }
    ]
  },
  {
    path: '/login',
    name: 'Login',
    component: () => import('@/views/Login.vue'),
    meta: { title: '登录' }
  },
  {
    path: '/:pathMatch(.*)*',
    redirect: '/dashboard'
  }
]

const router = createRouter({
  history: createWebHashHistory(),
  routes
})

// Global navigation guard for authentication
// Check both localStorage (remember me) and sessionStorage (not remember me)
router.beforeEach((to) => {
  const token = localStorage.getItem('mes_auth_token') || sessionStorage.getItem('mes_auth_token')
  // P1 #56: 已登录用户访问 /login 时重定向到 Dashboard
  if (to.name === 'Login' && token) {
    return { name: 'Dashboard' }
  }
  if (to.meta.requiresAuth && !token) {
    return { name: 'Login' }
  }
})

// P1 #57: 路由切换时更新页面标题
router.afterEach((to) => {
  document.title = to.meta.title ? `${to.meta.title} - MES` : 'MES'
})

export default router
