<template>
  <div class="orders-page">
    <div class="page-header">
      <div>
        <div class="page-title">生产订单</div>
        <div class="page-subtitle">共 {{ totalCount }} 条记录</div>
      </div>
      <div class="flex gap-2">
        <button class="btn btn-outline btn-sm" disabled title="导出功能开发中">
          <svg
            width="14"
            height="14"
            viewBox="0 0 24 24"
            fill="none"
            stroke="currentColor"
            stroke-width="2"
          >
            <path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4" />
            <polyline points="7 10 12 15 17 10" />
            <line x1="12" y1="15" x2="12" y2="3" />
          </svg>
          导出
        </button>
        <button class="btn btn-primary btn-sm" @click="openCreateModal">
          <svg
            width="14"
            height="14"
            viewBox="0 0 24 24"
            fill="none"
            stroke="currentColor"
            stroke-width="2"
          >
            <line x1="12" y1="5" x2="12" y2="19" />
            <line x1="5" y1="12" x2="19" y2="12" />
          </svg>
          新建订单
        </button>
      </div>
    </div>

    <!-- Filters -->
    <div class="card filter-bar">
      <div class="filter-group">
        <div class="search-box">
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
          <input
            v-model="searchText"
            type="text"
            placeholder="搜索订单号、产品名称..."
            class="search-input-inline"
          />
        </div>
        <select v-model="filterPriority" class="select filter-select">
          <option value="">全部优先级</option>
          <option v-for="p in priorityOptions" :key="p.value" :value="p.value">{{ p.label }}</option>
        </select>
        <input v-model="filterDateFrom" type="date" class="input filter-date" />
        <span style="color: var(--gray-400); font-size: 13px">至</span>
        <input v-model="filterDateTo" type="date" class="input filter-date" />
      </div>
      <div class="filter-actions">
        <button class="btn btn-ghost btn-sm" @click="resetFilters">重置</button>
        <span class="text-sm" style="color: var(--gray-500)"
          >{{ totalCount }} 条结果</span
        >
      </div>
    </div>

    <!-- Status Tabs -->
    <div class="status-tabs">
      <button
        v-for="tab in statusTabs"
        :key="tab.value"
        class="status-tab"
        :class="{ active: activeTab === tab.value }"
        @click="activeTab = tab.value"
      >
        {{ tab.label }}
        <span class="tab-count">{{ tab.count }}</span>
      </button>
    </div>

    <!-- Table -->
    <div class="card table-card">
      <div class="table-wrapper">
        <table class="table">
          <thead>
            <tr>
              <th style="width: 40px">
                <input v-model="selectAll" type="checkbox" @change="toggleSelectAll" />
              </th>
              <th>订单号</th>
              <th>产品名称</th>
              <th>规格型号</th>
              <th>客户名称</th>
              <th>订单数量</th>
              <th>完成数量</th>
              <th>计划完工</th>
              <th>优先级</th>
              <th>进度</th>
              <th>状态</th>
              <th>操作</th>
            </tr>
          </thead>
          <tbody>
            <tr v-if="loading"><td colspan="12" class="text-center">加载中...</td></tr>
            <tr v-if="orders.length === 0">
              <td colspan="12">
                <div class="empty-state">
                  <div class="empty-state-icon">
                    <svg
                      width="48"
                      height="48"
                      viewBox="0 0 24 24"
                      fill="none"
                      stroke="currentColor"
                      stroke-width="1.2"
                      style="color: var(--gray-300)"
                    >
                      <path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z" />
                      <polyline points="14 2 14 8 20 8" />
                    </svg>
                  </div>
                  <div class="empty-state-text">暂无匹配订单</div>
                </div>
              </td>
            </tr>
            <tr v-for="order in orders" :key="order.id">
              <td><input v-model="selectedIds" type="checkbox" :value="order.id" /></td>
              <td>
                <span class="order-num">{{ order.id }}</span>
              </td>
              <td>
                <div class="product-cell">
                  <div class="product-name">{{ order.product }}</div>
                  <div class="product-code text-xs" style="color: var(--gray-400)">
                    {{ order.code }}
                  </div>
                </div>
              </td>
              <td class="text-sm">{{ order.spec }}</td>
              <td>
                <div class="flex items-center gap-2">
                  <div class="avatar avatar-sm" :style="`background: ${strColor(order.customer)}`">
                    {{ order.customer[0] }}
                  </div>
                  <span class="text-sm">{{ order.customer }}</span>
                </div>
              </td>
              <td class="text-sm font-medium">{{ order.qty.toLocaleString() }}</td>
              <td class="text-sm">
                <span :style="(order.completedQty || 0) >= order.qty ? 'color:var(--success)' : ''">{{
                  (order.completedQty || 0).toLocaleString()
                }}</span>
              </td>
              <td class="text-sm">
                <span
                  :class="
                    isOverdue(order.dueDate) && order.status !== 'completed' ? 'overdue-date' : ''
                  "
                >
                  {{ order.dueDate }}
                </span>
              </td>
              <td>
                <span class="priority-badge" :class="`priority-${order.priority}`">{{
                  PRIORITY_LABELS[order.priority] || order.priority
                }}</span>
              </td>
              <td>
                <div class="progress-cell">
                  <div class="progress" :class="progressClass(order)">
                    <div class="progress-bar" :style="`width:${calcProgress(order)}%`"></div>
                  </div>
                  <span class="text-xs" style="color: var(--gray-500)"
                    >{{ calcProgress(order) }}%</span
                  >
                </div>
              </td>
              <td>
                <span class="badge" :class="statusBadge(order.status)">{{ STATUS_LABELS[order.status] || order.status }}</span>
              </td>
              <td>
                <div class="action-buttons">
                  <button
                    class="btn btn-ghost btn-sm btn-icon"
                    title="查看详情"
                    @click="viewOrder(order)"
                  >
                    <svg
                      width="14"
                      height="14"
                      viewBox="0 0 24 24"
                      fill="none"
                      stroke="currentColor"
                      stroke-width="2"
                    >
                      <path d="M1 12s4-8 11-8 11 8 11 8-4 8-11 8-11-8-11-8z" />
                      <circle cx="12" cy="12" r="3" />
                    </svg>
                  </button>
                  <button
                    class="btn btn-ghost btn-sm btn-icon"
                    title="编辑"
                    @click="editOrder(order)"
                  >
                    <svg
                      width="14"
                      height="14"
                      viewBox="0 0 24 24"
                      fill="none"
                      stroke="currentColor"
                      stroke-width="2"
                    >
                      <path d="M11 4H4a2 2 0 0 0-2 2v14a2 2 0 0 0 2 2h14a2 2 0 0 0 2-2v-7" />
                      <path d="M18.5 2.5a2.121 2.121 0 0 1 3 3L12 15l-4 1 1-4 9.5-9.5z" />
                    </svg>
                  </button>
                  <button
                    class="btn btn-ghost btn-sm btn-icon"
                    title="删除"
                    @click="handleDelete(order.id)"
                  >
                    <svg
                      width="14"
                      height="14"
                      viewBox="0 0 24 24"
                      fill="none"
                      stroke="currentColor"
                      stroke-width="2"
                    >
                      <polyline points="3 6 5 6 21 6" />
                      <path
                        d="M19 6v14a2 2 0 0 1-2 2H7a2 2 0 0 1-2-2V6m3 0V4a2 2 0 0 1 2-2h4a2 2 0 0 1 2 2v2"
                      />
                    </svg>
                  </button>
                  <button
                    class="btn btn-ghost btn-sm btn-icon"
                    title="更多"
                    @click="toggleDropdown(order.id)"
                  >
                    <svg
                      width="14"
                      height="14"
                      viewBox="0 0 24 24"
                      fill="none"
                      stroke="currentColor"
                      stroke-width="2"
                    >
                      <circle cx="12" cy="5" r="1" />
                      <circle cx="12" cy="12" r="1" />
                      <circle cx="12" cy="19" r="1" />
                    </svg>
                  </button>
                </div>
              </td>
            </tr>
          </tbody>
        </table>
      </div>

      <!-- Pagination -->
      <div class="pagination">
        <div class="page-info text-sm" style="color: var(--gray-500)">
          显示 {{ (currentPage - 1) * pageSize + 1 }}-{{
            Math.min(currentPage * pageSize, totalCount)
          }}，共 {{ totalCount }} 条
        </div>
        <div class="flex items-center gap-2">
          <select
            v-model="pageSize"
            class="select"
            style="width: 80px; height: 32px; font-size: 13px"
          >
            <option :value="10">10条</option>
            <option :value="20">20条</option>
            <option :value="50">50条</option>
          </select>
          <button
            class="btn btn-outline btn-sm btn-icon"
            :disabled="currentPage === 1"
            @click="currentPage--"
          >
            <svg
              width="14"
              height="14"
              viewBox="0 0 24 24"
              fill="none"
              stroke="currentColor"
              stroke-width="2"
            >
              <polyline points="15 18 9 12 15 6" />
            </svg>
          </button>
          <button
            v-for="p in pageButtons"
            :key="p"
            class="btn btn-sm page-btn"
            :class="p === currentPage ? 'btn-primary' : 'btn-outline'"
            @click="currentPage = p"
          >
            {{ p }}
          </button>
          <button
            class="btn btn-outline btn-sm btn-icon"
            :disabled="currentPage === totalPages"
            @click="currentPage++"
          >
            <svg
              width="14"
              height="14"
              viewBox="0 0 24 24"
              fill="none"
              stroke="currentColor"
              stroke-width="2"
            >
              <polyline points="9 18 15 12 9 6" />
            </svg>
          </button>
        </div>
      </div>
    </div>

    <!-- Create/Edit Modal -->
    <div v-if="showModal" class="modal-overlay" @click.self="closeModal">
      <div class="modal">
        <div class="modal-header">
          <div class="modal-title">
            {{ modalMode === 'create' ? '新建生产订单' : '编辑生产订单' }}
          </div>
          <button class="btn btn-ghost btn-icon" @click="closeModal">
            <svg
              width="18"
              height="18"
              viewBox="0 0 24 24"
              fill="none"
              stroke="currentColor"
              stroke-width="2"
            >
              <line x1="18" y1="6" x2="6" y2="18" />
              <line x1="6" y1="6" x2="18" y2="18" />
            </svg>
          </button>
        </div>
        <div class="modal-body">
          <div class="form-row">
            <div class="form-group">
              <label class="form-label">产品名称 <span style="color: var(--danger)">*</span></label>
              <input v-model="form.product" class="input" placeholder="请输入产品名称" />
            </div>
            <div class="form-group">
              <label class="form-label">产品编码</label>
              <input v-model="form.code" class="input" placeholder="如：PRD-2026-001" />
            </div>
          </div>
          <div class="form-row">
            <div class="form-group">
              <label class="form-label">规格型号</label>
              <input v-model="form.spec" class="input" placeholder="规格描述" />
            </div>
            <div class="form-group">
              <label class="form-label">客户名称 <span style="color: var(--danger)">*</span></label>
              <input v-model="form.customer" class="input" placeholder="客户名称" />
            </div>
          </div>
          <div class="form-row">
            <div class="form-group">
              <label class="form-label">订单数量 <span style="color: var(--danger)">*</span></label>
              <input
                v-model.number="form.qty"
                class="input"
                type="number"
                placeholder="0"
                min="1"
              />
            </div>
            <div class="form-group">
              <label class="form-label"
                >计划完工日期 <span style="color: var(--danger)">*</span></label
              >
              <input v-model="form.dueDate" class="input" type="date" />
            </div>
          </div>
          <div class="form-row">
            <div class="form-group">
              <label class="form-label">优先级</label>
              <select v-model="form.priority" class="select">
                <option v-for="p in priorityOptions" :key="p.value" :value="p.value">{{ p.label }}</option>
              </select>
            </div>
            <div class="form-group">
              <label class="form-label">状态</label>
              <select v-model="form.status" class="select">
                <option v-for="s in orderStatuses" :key="s" :value="s">{{ STATUS_LABELS[s] || s }}</option>
              </select>
            </div>
          </div>
          <div class="form-group">
            <label class="form-label">备注</label>
            <textarea
              v-model="form.remark"
              class="input"
              style="height: 72px; resize: vertical; padding-top: 8px"
              placeholder="订单备注..."
            ></textarea>
          </div>
        </div>
        <div class="modal-footer">
          <button class="btn btn-outline" @click="closeModal">取消</button>
          <button class="btn btn-primary" @click="saveOrder">
            {{ modalMode === 'create' ? '创建订单' : '保存修改' }}
          </button>
        </div>
      </div>
    </div>

    <!-- Toast -->
    <div class="toast-container">
      <div v-for="toast in toasts" :key="toast.id" class="toast" :class="`toast-${toast.type}`">
        {{ toast.message }}
      </div>
    </div>
  </div>
</template>

<script setup>
import { ref, computed, watch, onMounted, onBeforeUnmount } from 'vue'
import { watchDebounced } from '@vueuse/core'
import { strColor } from '../composables/useStrColor.js'
import { useToast } from '../composables/useToast.js'
import { useConfirm } from '../composables/useConfirm.js'
import {
  fetchOrders,
  fetchOrderStatuses,
  fetchOrderPriorities,
  createOrder as apiCreateOrder,
  updateOrder as apiUpdateOrder,
  deleteOrder as apiDeleteOrder
} from '../api/index.js'

const searchText = ref('')
const filterPriority = ref('')
const filterDateFrom = ref('')
const filterDateTo = ref('')
const activeTab = ref('')
const currentPage = ref(1)
const pageSize = ref(10)
const selectAll = ref(false)
const selectedIds = ref([])
const showModal = ref(false)
const modalMode = ref('create')
const { toasts, showToast } = useToast()
const { openConfirm } = useConfirm()

const loading = ref(false)
const orders = ref([])
const totalCount = ref(0)

// Status enum loaded from API
const orderStatuses = ref([])

const STATUS_LABELS = {
  pending: '待生产',
  in_progress: '生产中',
  processing: '暂停',
  completed: '已完成',
  cancelled: '已取消'
}

// Priority options loaded from API, mapped to {value, label} format
const priorityOptions = ref([])

const PRIORITY_LABELS = {
  normal: '普通',
  high: '高',
  urgent: '紧急',
  low: '低'
}

const form = ref({
  product: '',
  code: '',
  spec: '',
  customer: '',
  qty: '',
  dueDate: '',
  priority: '',
  status: '',
  remark: ''
})

const statusCounts = ref({})

async function loadOrders() {
  loading.value = true
  try {
    const params = {
      status: activeTab.value || undefined,
      priority: filterPriority.value || undefined,
      keyword: searchText.value || undefined,
      dateFrom: filterDateFrom.value || undefined,
      dateTo: filterDateTo.value || undefined,
      page: currentPage.value,
      pageSize: pageSize.value
    }
    const data = await fetchOrders(params)
    orders.value = data.items || []
    totalCount.value = data.total || 0
    // Cache status counts from server if returned
    if (data.statusCounts) {
      statusCounts.value = data.statusCounts
    }
  } catch {
    orders.value = []
    totalCount.value = 0
  } finally {
    loading.value = false
  }
}

async function loadStatusCounts() {
  try {
    const data = await fetchOrders({ page: 1, pageSize: 1 })
    totalCount.value = data.total || 0
    if (data.statusCounts) {
      statusCounts.value = data.statusCounts
    }
    // P2 #87: No fallback derivation from single-item response (counts would be wrong)
    // Tab counts show 0 when server doesn't return statusCounts
  } catch {
    // silently fail - tab counts will show 0
  }
}

const statusTabs = computed(() => [
  { label: '全部', value: '', count: totalCount.value },
  { label: '待生产', value: 'pending', count: statusCounts.value['pending'] || 0 },
  { label: '生产中', value: 'in_progress', count: statusCounts.value['in_progress'] || 0 },
  { label: '暂停', value: 'processing', count: statusCounts.value['processing'] || 0 },
  { label: '已完成', value: 'completed', count: statusCounts.value['completed'] || 0 },
  { label: '已取消', value: 'cancelled', count: statusCounts.value['cancelled'] || 0 }
])

// P2 #88: Reset page to 1 when filters change (activeTab, filterPriority, date filters)
// but NOT when currentPage/pageSize change (handled by their own watchers)
watch([filterPriority, activeTab], () => {
  currentPage.value = 1
  loadOrders()
})

watch([currentPage, pageSize], () => {
  loadOrders()
})

watchDebounced(
  searchText,
  () => {
    loadOrders()
  },
  { debounce: 300, maxWait: 1000 }
)

const totalPages = computed(() => Math.ceil(totalCount.value / pageSize.value) || 1)

const pageButtons = computed(() => {
  const total = totalPages.value
  const cur = currentPage.value
  const pages = []
  for (let i = Math.max(1, cur - 2); i <= Math.min(total, cur + 2); i++) {
    pages.push(i)
  }
  return pages
})

function calcProgress(order) {
  if (order.qty === 0) return 0
  return Math.round(((order.completedQty || 0) / order.qty) * 100)
}

function isOverdue(date) {
  return new Date(date) < new Date()
}

function progressClass(order) {
  if (order.status === 'cancelled') return 'progress-danger'
  if (calcProgress(order) === 100) return 'progress-success'
  return 'progress-primary'
}

function statusBadge(status) {
  const map = {
    in_progress: 'badge-primary',
    pending: 'badge-gray',
    processing: 'badge-warning',
    completed: 'badge-success',
    cancelled: 'badge-danger'
  }
  return map[status] || 'badge-gray'
}



function toggleSelectAll() {
  if (selectAll.value) {
    selectedIds.value = orders.value.map(o => o.id)
  } else {
    selectedIds.value = []
  }
}

function resetFilters() {
  searchText.value = ''
  activeTab.value = ''
  filterPriority.value = ''
  filterDateFrom.value = ''
  filterDateTo.value = ''
}

function openCreateModal() {
  modalMode.value = 'create'
  form.value = {
    product: '',
    code: '',
    spec: '',
    customer: '',
    qty: '',
    dueDate: '',
    priority: '',
    status: '',
    remark: ''
  }
  showModal.value = true
}

function editOrder(order) {
  modalMode.value = 'edit'
  form.value = { ...order }
  showModal.value = true
}

function viewOrder(order) {
  showToast(`查看订单：${order.id}`, 'info')
}

function closeModal() {
  showModal.value = false
}

async function saveOrder() {
  // 自动生成订单编号（如果未填写）
  if (!form.value.code) {
    const now = new Date()
    const dateStr = now.getFullYear().toString() +
      String(now.getMonth() + 1).padStart(2, '0') +
      String(now.getDate()).padStart(2, '0')
    const rand = Math.random().toString(36).substring(2, 6).toUpperCase()
    form.value.code = `ORD-${dateStr}-${rand}`
  }
  if (!form.value.product || !form.value.customer || !form.value.qty || !form.value.dueDate) {
    showToast('请填写必填字段', 'warning')
    return
  }
  try {
    // 格式化提交数据，确保字段类型正确
    const submitData = {
      ...form.value,
      qty: Number(form.value.qty) || 1,
      priority: form.value.priority || 'normal',
      status: form.value.status || 'pending',
    }
    if (modalMode.value === 'create') {
      await apiCreateOrder(submitData)
      showToast('订单创建成功', 'success')
    } else {
      await apiUpdateOrder(form.value.id, submitData)
      showToast('订单更新成功', 'success')
    }
    closeModal()
    await loadOrders()
  } catch (err) {
    showToast(err.message || '操作失败', 'warning')
  }
}

async function handleDelete(id) {
  if (!await openConfirm({ title: '删除订单', message: '确定删除该订单吗？此操作不可撤销。' })) return
  try {
    await apiDeleteOrder(id)
    showToast('订单已删除', 'success')
    await loadOrders()
  } catch (err) {
    showToast(err.message || '删除失败', 'warning')
  }
}

function toggleDropdown(id) {
  showToast(`订单 ${id} 更多操作`, 'info')
}

onMounted(() => {
  loadOrders()
  loadStatusCounts()
  fetchOrderStatuses().then(data => { orderStatuses.value = data || [] }).catch(() => {})
  fetchOrderPriorities().then(data => {
    priorityOptions.value = (data || []).map(v => ({ value: v, label: PRIORITY_LABELS[v] || v }))
  }).catch(() => {})
})

onBeforeUnmount(() => {
  // Toast cleanup handled by useToast composable
})
</script>

<style scoped>
.orders-page {
  display: flex;
  flex-direction: column;
  gap: 16px;
}

.filter-bar {
  padding: 14px 16px;
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
  flex-wrap: wrap;
}
.filter-group {
  display: flex;
  align-items: center;
  gap: 10px;
  flex-wrap: wrap;
  flex: 1;
}

.search-box {
  display: flex;
  align-items: center;
  gap: 8px;
  background: var(--gray-50);
  border: 1px solid var(--gray-200);
  border-radius: 8px;
  padding: 0 12px;
  height: 36px;
  color: var(--gray-400);
  min-width: 220px;
}
.search-input-inline {
  border: none;
  background: transparent;
  outline: none;
  font-size: var(--font-size-sm);
  color: var(--gray-700);
  flex: 1;
}
.search-input-inline::placeholder {
  color: var(--gray-400);
}

.filter-select {
  width: 120px;
}
.filter-date {
  width: 140px;
}
.filter-actions {
  display: flex;
  align-items: center;
  gap: 10px;
}

.status-tabs {
  display: flex;
  gap: 4px;
  border-bottom: 2px solid var(--gray-200);
  padding-bottom: 0;
}
.status-tab {
  padding: 8px 16px 10px;
  border: none;
  background: none;
  font-size: var(--font-size-sm);
  color: var(--gray-500);
  cursor: pointer;
  border-bottom: 2px solid transparent;
  margin-bottom: -2px;
  transition: var(--transition-fast);
  display: flex;
  align-items: center;
  gap: 6px;
}
.status-tab:hover {
  color: var(--gray-800);
}
.status-tab.active {
  color: var(--primary);
  border-bottom-color: var(--primary);
  font-weight: 600;
}

.tab-count {
  background: var(--gray-100);
  color: var(--gray-500);
  font-size: 11px;
  padding: 1px 6px;
  border-radius: 10px;
}
.status-tab.active .tab-count {
  background: var(--primary-bg);
  color: var(--primary);
}

.table-card {
  overflow: hidden;
}
.pagination {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 12px 16px;
  border-top: 1px solid var(--gray-100);
}

.order-num {
  font-family: monospace;
  font-size: 12px;
  color: var(--primary);
  font-weight: 600;
}
.product-name {
  font-size: var(--font-size-sm);
  font-weight: 500;
  color: var(--gray-800);
}
.product-code {
  font-family: monospace;
}

.priority-badge {
  display: inline-flex;
  align-items: center;
  padding: 2px 8px;
  border-radius: 4px;
  font-size: 11px;
  font-weight: 600;
}
.priority-urgent {
  background: #fee2e2;
  color: #ef4444;
}
.priority-high {
  background: #fef3c7;
  color: #f59e0b;
}
.priority-normal {
  background: var(--gray-100);
  color: var(--gray-500);
}

.progress-cell {
  display: flex;
  align-items: center;
  gap: 6px;
  min-width: 100px;
}
.overdue-date {
  color: var(--danger);
  font-weight: 600;
}

.action-buttons {
  display: flex;
  gap: 2px;
}
.page-btn {
  min-width: 32px;
  height: 32px;
  padding: 0;
  display: flex;
  align-items: center;
  justify-content: center;
}

.toast-container {
  position: fixed;
  top: 20px;
  right: 20px;
  z-index: 2000;
  display: flex;
  flex-direction: column;
  gap: 8px;
}
.toast {
  display: flex;
  align-items: center;
  gap: 10px;
  padding: 12px 16px;
  border-radius: var(--border-radius);
  box-shadow: var(--shadow-lg);
  font-size: var(--font-size-sm);
  min-width: 240px;
  animation: slideIn 0.3s ease;
}
.toast {
  background: var(--gray-800);
  color: #fff;
}
.toast-success {
  background: var(--success);
  color: #fff;
}
.toast-warning {
  background: var(--warning);
  color: #fff;
}
.toast-info {
  background: var(--info);
  color: #fff;
}
@keyframes slideIn {
  from {
    transform: translateX(100%);
    opacity: 0;
  }
  to {
    transform: translateX(0);
    opacity: 1;
  }
}

@media (max-width: 768px) {
  .filter-bar {
    flex-direction: column;
    align-items: stretch;
  }
  .filter-group {
    flex-direction: column;
  }
  .filter-select,
  .filter-date,
  .search-box {
    width: 100%;
  }
}
</style>
