/**
 * Router unit tests
 *
 * Covers:
 *   - route definitions: paths, names, meta titles
 *   - hash history mode
 *   - default redirect from / to /dashboard
 *   - lazy loading for all views
 *   - nested routes under MainLayout
 *   - Login route outside MainLayout
 */

import { describe, it, expect } from 'vitest'
import router from './index.js'

function getRouteRecords(routes, flat = true) {
  const result = []
  for (const route of routes) {
    if (flat) {
      result.push(route)
    }
    if (route.children) {
      result.push(...getRouteRecords(route.children, flat))
    }
  }
  return result
}

describe('router configuration', () => {
  it('uses hash history mode', () => {
    // Hash history uses WebHashHistory
    expect(router.options.history.constructor.name).toBe('WebHashHistory')
  })

  it('redirects / to /dashboard', () => {
    const root = router.options.routes[0]
    expect(root.path).toBe('/')
    expect(root.redirect).toBe('/dashboard')
  })

  it('all main routes are nested under MainLayout', () => {
    const root = router.options.routes[0]
    expect(root.path).toBe('/')
    expect(root.component).toBeDefined()
    const mainPaths = root.children.map((r) => r.path)
    expect(mainPaths).toContain('dashboard')
    expect(mainPaths).toContain('orders')
    expect(mainPaths).toContain('customers')
    expect(mainPaths).toContain('inventory')
    expect(mainPaths).toContain('equipment')
    expect(mainPaths).toContain('reports')
    expect(mainPaths).toContain('worktime')
    expect(mainPaths).toContain('line-balance')
    expect(mainPaths).toContain('ai-analysis')
  })

  it('Login route is a top-level route, not under MainLayout', () => {
    const loginRoute = router.options.routes.find((r) => r.path === '/login')
    expect(loginRoute).toBeDefined()
    expect(loginRoute.children).toBeUndefined()
    expect(loginRoute.name).toBe('Login')
  })
})

describe('route names and meta titles', () => {
  const root = router.options.routes[0]
  const loginRoute = router.options.routes.find((r) => r.path === '/login')
  // Collect all child routes + top-level login route
  const flat = [...(root.children || []), loginRoute].filter(Boolean)

  const expected = [
    { path: 'dashboard', name: 'Dashboard', title: '生产看板' },
    { path: 'worktime', name: 'WorktimeAnalysis', title: '工时分析' },
    { path: 'line-balance', name: 'LineBalance', title: '线平衡' },
    { path: 'ai-analysis', name: 'AiAnalysis', title: 'AI分析' },
    { path: 'orders', name: 'Orders', title: '生产订单' },
    { path: 'customers', name: 'Customers', title: '客户管理' },
    { path: 'inventory', name: 'Inventory', title: '库存管理' },
    { path: 'equipment', name: 'Equipment', title: '设备管理' },
    { path: 'reports', name: 'Reports', title: '报表分析' },
    { path: '/login', name: 'Login', title: '登录' }
  ]

  it.each(expected)('route $name has path "$path" and title "$title"', (r) => {
    const found = flat.find((f) => f.name === r.name)
    expect(found).toBeDefined()
    expect(found.path).toBe(r.path)
    expect(found.meta.title).toBe(r.title)
  })
})

describe('lazy loading', () => {
  const allRoutes = getRouteRecords(router.options.routes, false)
  const flat = []
  for (const route of allRoutes) {
    if (route.children) {
      flat.push(...route.children)
    } else {
      flat.push(route)
    }
  }

  it('all view routes use lazy-loaded components', () => {
    const viewRoutes = flat.filter((r) => r.path !== '/')
    for (const route of viewRoutes) {
      expect(typeof route.component).toBe('function')
    }
  })
})
