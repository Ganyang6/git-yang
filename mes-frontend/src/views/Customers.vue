<template>
  <div class="customers-page">
    <div class="page-header">
      <div>
        <div class="page-title">客户管理</div>
        <div class="page-subtitle">共 {{ filteredCustomers.length }} 家客户</div>
      </div>
      <div class="flex gap-2">
        <button class="btn btn-outline btn-sm" disabled title="导入功能开发中">导入</button>
        <button class="btn btn-primary btn-sm" @click="openModal()">
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
          新增客户
        </button>
      </div>
    </div>

    <!-- Stats Cards -->
    <div class="customer-stats">
      <div v-for="stat in statsData" :key="stat.label" class="stat-card card">
        <div
          class="stat-icon"
          :style="`color:${stat.color}; background:${stat.color}15`"
          v-html="stat.icon"
        ></div>
        <div class="stat-content">
          <div class="stat-value">{{ stat.value }}</div>
          <div class="stat-label">{{ stat.label }}</div>
        </div>
      </div>
    </div>

    <!-- Filter Bar -->
    <div class="card filter-bar">
      <div class="flex gap-3 items-center flex-wrap">
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
            placeholder="搜索公司名称、联系人..."
            class="search-input-inline"
          />
        </div>
        <select v-model="filterType" class="select" style="width: 120px">
          <option value="">全部类型</option>
          <option v-for="t in customerTypes" :key="t" :value="t">{{ t }}</option>
        </select>
        <select v-model="filterLevel" class="select" style="width: 120px">
          <option value="">全部级别</option>
          <option v-for="l in customerLevels" :key="l" :value="l">{{ l }}</option>
        </select>
        <div class="view-toggle">
          <button
            :class="['view-btn', viewMode === 'table' ? 'active' : '']"
            title="列表视图"
            @click="viewMode = 'table'"
          >
            <svg
              width="15"
              height="15"
              viewBox="0 0 24 24"
              fill="none"
              stroke="currentColor"
              stroke-width="2"
            >
              <line x1="8" y1="6" x2="21" y2="6" />
              <line x1="8" y1="12" x2="21" y2="12" />
              <line x1="8" y1="18" x2="21" y2="18" />
              <line x1="3" y1="6" x2="3.01" y2="6" />
              <line x1="3" y1="12" x2="3.01" y2="12" />
              <line x1="3" y1="18" x2="3.01" y2="18" />
            </svg>
          </button>
          <button
            :class="['view-btn', viewMode === 'card' ? 'active' : '']"
            title="卡片视图"
            @click="viewMode = 'card'"
          >
            <svg
              width="15"
              height="15"
              viewBox="0 0 24 24"
              fill="none"
              stroke="currentColor"
              stroke-width="2"
            >
              <rect x="3" y="3" width="7" height="7" rx="1" />
              <rect x="14" y="3" width="7" height="7" rx="1" />
              <rect x="3" y="14" width="7" height="7" rx="1" />
              <rect x="14" y="14" width="7" height="7" rx="1" />
            </svg>
          </button>
        </div>
      </div>
    </div>

    <!-- Card View -->
    <div v-if="viewMode === 'card'" class="customer-cards">
      <div
        v-for="c in filteredCustomers"
        :key="c.id"
        class="customer-card card"
        @click="viewCustomer(c)"
      >
        <div class="cc-header">
          <div class="cc-avatar" :style="`background: ${strColor(c.name)}`">{{ c.name[0] }}</div>
          <div class="cc-level" :class="`level-${c.level}`">{{ c.level }}</div>
        </div>
        <div class="cc-name">{{ c.name }}</div>
        <div class="cc-contact">
          <svg
            width="12"
            height="12"
            viewBox="0 0 24 24"
            fill="none"
            stroke="currentColor"
            stroke-width="2"
          >
            <path d="M20 21v-2a4 4 0 0 0-4-4H8a4 4 0 0 0-4 4v2" />
            <circle cx="12" cy="7" r="4" />
          </svg>
          {{ c.contact }} · {{ c.phone }}
        </div>
        <div class="cc-contact">
          <svg
            width="12"
            height="12"
            viewBox="0 0 24 24"
            fill="none"
            stroke="currentColor"
            stroke-width="2"
          >
            <path d="M21 10c0 7-9 13-9 13s-9-6-9-13a9 9 0 0 1 18 0z" />
            <circle cx="12" cy="10" r="3" />
          </svg>
          {{ c.city }}
        </div>
        <div class="cc-stats">
          <div class="cc-stat">
            <div class="cc-stat-val">{{ c.orders }}</div>
            <div class="cc-stat-label">订单数</div>
          </div>
          <div class="cc-stat-divider"></div>
          <div class="cc-stat">
            <div class="cc-stat-val">{{ c.amount }}</div>
            <div class="cc-stat-label">合同额(万)</div>
          </div>
          <div class="cc-stat-divider"></div>
          <div class="cc-stat">
            <div class="cc-stat-val" :class="c.status === '活跃' ? 'text-success' : 'text-gray'">
              {{ c.status }}
            </div>
            <div class="cc-stat-label">状态</div>
          </div>
        </div>
      </div>
    </div>

    <!-- Table View -->
    <div v-else class="card table-card">
      <div class="table-wrapper">
        <table class="table">
          <thead>
            <tr>
              <th>客户名称</th>
              <th>联系人</th>
              <th>联系电话</th>
              <th>城市</th>
              <th>客户类型</th>
              <th>客户级别</th>
              <th>订单数</th>
              <th>合同额(万)</th>
              <th>最近合作</th>
              <th>状态</th>
              <th>操作</th>
            </tr>
          </thead>
          <tbody>
            <tr v-for="c in filteredCustomers" :key="c.id">
              <td>
                <div class="flex items-center gap-2">
                  <div class="avatar avatar-sm" :style="`background:${strColor(c.name)}`">
                    {{ c.name[0] }}
                  </div>
                  <div>
                    <div class="text-sm font-medium">{{ c.name }}</div>
                    <div class="text-xs" style="color: var(--gray-400)">{{ c.id }}</div>
                  </div>
                </div>
              </td>
              <td class="text-sm">{{ c.contact }}</td>
              <td class="text-sm" style="font-family: monospace">{{ c.phone }}</td>
              <td class="text-sm">{{ c.city }}</td>
              <td>
                <span class="badge badge-gray">{{ c.type }}</span>
              </td>
              <td>
                <span class="customer-level" :class="`level-${c.level}`">{{ c.level }}</span>
              </td>
              <td class="text-sm font-medium">{{ c.orders }}</td>
              <td class="text-sm font-medium">{{ c.amount }}</td>
              <td class="text-sm" style="color: var(--gray-400)">{{ c.lastOrder }}</td>
              <td>
                <span class="badge" :class="c.status === '活跃' ? 'badge-success' : 'badge-gray'">{{
                  c.status
                }}</span>
              </td>
              <td>
                <div class="flex gap-1">
                  <button
                    class="btn btn-ghost btn-sm btn-icon"
                    title="查看"
                    @click="viewCustomer(c)"
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
                  <button class="btn btn-ghost btn-sm btn-icon" title="编辑" @click="openModal(c)">
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
                    style="color: var(--danger)"
                    @click="handleDeleteCustomer(c.id)"
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
                </div>
              </td>
            </tr>
          </tbody>
        </table>
      </div>
    </div>

    <!-- Modal -->
    <div v-if="showModal" class="modal-overlay" @click.self="showModal = false">
      <div class="modal">
        <div class="modal-header">
          <div class="modal-title">{{ isViewOnly ? '客户详情' : (editingId ? '编辑客户' : '新增客户') }}</div>
          <button class="btn btn-ghost btn-icon" @click="showModal = false">
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
              <label class="form-label">公司名称 <span style="color: var(--danger)">*</span></label>
              <input v-model="form.name" class="input" placeholder="请输入公司名称" />
            </div>
            <div class="form-group">
              <label class="form-label">联系人</label>
              <input v-model="form.contact" class="input" placeholder="主要联系人" />
            </div>
          </div>
          <div class="form-row">
            <div class="form-group">
              <label class="form-label">联系电话</label>
              <input v-model="form.phone" class="input" placeholder="手机或固定电话" />
            </div>
            <div class="form-group">
              <label class="form-label">所在城市</label>
              <input v-model="form.city" class="input" placeholder="如：上海" />
            </div>
          </div>
          <div class="form-row">
            <div class="form-group">
              <label class="form-label">客户类型</label>
              <select v-model="form.type" class="select">
                <option v-for="t in customerTypes" :key="t" :value="t">{{ t }}</option>
              </select>
            </div>
            <div class="form-group">
              <label class="form-label">客户级别</label>
              <select v-model="form.level" class="select">
                <option v-for="l in customerLevels" :key="l" :value="l">{{ l }}</option>
              </select>
            </div>
          </div>
          <div class="form-group">
            <label class="form-label">备注</label>
            <textarea
              v-model="form.remark"
              class="input"
              style="height: 72px; resize: vertical; padding-top: 8px"
              placeholder="客户备注信息..."
            ></textarea>
          </div>
        </div>
        <div class="modal-footer">
          <button class="btn btn-outline" @click="showModal = false">{{ isViewOnly ? '关闭' : '取消' }}</button>
          <button v-if="!isViewOnly" class="btn btn-primary" @click="saveCustomer">保存</button>
        </div>
      </div>
    </div>

    <!-- Toast (C9) -->
    <div class="toast-container">
      <div v-for="toast in toasts" :key="toast.id" class="toast" :class="`toast-${toast.type}`">
        {{ toast.message }}
      </div>
    </div>
  </div>
</template>

<script setup>
import { ref, computed, watch, onMounted, onBeforeUnmount } from 'vue'
import DOMPurify from 'dompurify'
import { watchDebounced } from '@vueuse/core'
import { strColor } from '../composables/useStrColor.js'
import { useToast } from '../composables/useToast.js'
import { useConfirm } from '../composables/useConfirm.js'
import {
  fetchCustomers,
  fetchCustomerStats,
  fetchCustomerTypes,
  fetchCustomerLevels,
  createCustomer as apiCreateCustomer,
  updateCustomer as apiUpdateCustomer,
  deleteCustomer as apiDeleteCustomer
} from '../api/index.js'

const searchText = ref('')
const filterType = ref('')
const filterLevel = ref('')
const viewMode = ref('table')
const showModal = ref(false)
const isViewOnly = ref(false) // P2 #89: 只读查看模式
const editingId = ref(null)
const loading = ref(false)
const form = ref({
  name: '',
  contact: '',
  phone: '',
  city: '',
  type: '制造业',
  level: 'A级',
  remark: ''
})

const customerTypes = ref([])
const customerLevels = ref([])

const customers = ref([])
const stats = ref({ total: 0, active: 0, saCount: 0, totalAmount: '0' })
const { toasts, showToast } = useToast()
const { openConfirm } = useConfirm()

async function loadCustomers() {
  loading.value = true
  try {
    const params = {
      type: filterType.value || undefined,
      level: filterLevel.value || undefined,
      keyword: searchText.value || undefined
    }
    customers.value = await fetchCustomers(params)
  } catch {
    customers.value = []
  } finally {
    loading.value = false
  }
}

async function loadStats() {
  try {
    stats.value = await fetchCustomerStats()
  } catch {
    // stats keep previous values
  }
}

const statsData = computed(() => [
  {
    label: '客户总数',
    value: stats.value.total || customers.value.length,
    color: '#1a6ef5',
    icon: DOMPurify.sanitize('<svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M17 21v-2a4 4 0 0 0-4-4H5a4 4 0 0 0-4 4v2"/><circle cx="9" cy="7" r="4"/><path d="M23 21v-2a4 4 0 0 0-3-3.87"/><path d="M16 3.13a4 4 0 0 1 0 7.75"/></svg>')
  },
  {
    label: '活跃客户',
    value: stats.value.active || customers.value.filter(c => c.status === '活跃').length,
    color: '#10b981',
    icon: DOMPurify.sanitize('<svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><polyline points="22 12 18 12 15 21 9 3 6 12 2 12"/></svg>')
  },
  {
    label: 'S/A级客户',
    value:
      stats.value.saCount || customers.value.filter(c => ['S级', 'A级'].includes(c.level)).length,
    color: '#f59e0b',
    icon: DOMPurify.sanitize('<svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><polygon points="12 2 15.09 8.26 22 9.27 17 14.14 18.18 21.02 12 17.77 5.82 21.02 7 14.14 2 9.27 8.91 8.26 12 2"/></svg>')
  },
  {
    label: '总合同额(万)',
    value:
      stats.value.totalAmount ||
      customers.value.reduce((s, c) => s + parseFloat(c.amount || 0), 0).toFixed(1),
    color: '#6366f1',
    icon: DOMPurify.sanitize('<svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><line x1="12" y1="1" x2="12" y2="23"/><path d="M17 5H9.5a3.5 3.5 0 0 0 0 7h5a3.5 3.5 0 0 1 0 7H6"/></svg>')
  }
])

watch([filterType, filterLevel], () => {
  loadCustomers()
})

watchDebounced(
  searchText,
  () => {
    loadCustomers()
  },
  { debounce: 300, maxWait: 1000 }
)

const filteredCustomers = computed(() => {
  return customers.value.filter(c => {
    if (filterType.value && c.type !== filterType.value) return false
    if (filterLevel.value && c.level !== filterLevel.value) return false
    if (searchText.value) {
      const q = searchText.value.toLowerCase()
      if (!c.name.toLowerCase().includes(q) && !c.contact.toLowerCase().includes(q)) return false
    }
    return true
  })
})



function openModal(customer = null) {
  isViewOnly.value = false
  if (customer) {
    editingId.value = customer.id
    // P2-6: whitelist extraction to avoid leaking unwanted fields into the form
    form.value = {
      name: customer.name,
      contact: customer.contact,
      phone: customer.phone,
      city: customer.city,
      type: customer.type,
      level: customer.level,
      remark: customer.remark || ''
    }
  } else {
    editingId.value = null
    form.value = {
      name: '',
      contact: '',
      phone: '',
      city: '',
      type: '',
      level: '',
      remark: ''
    }
  }
  showModal.value = true
}

function viewCustomer(c) {
  // 复用编辑模态框以只读模式展示客户详情
  editingId.value = c.id
  form.value = { name: c.name, contact: c.contact, phone: c.phone, city: c.city, type: c.type, level: c.level, remark: c.remark || '' }
  isViewOnly.value = true
  showModal.value = true
}

async function saveCustomer() {
  if (!form.value.name) {
    showToast('请填写客户名称', 'warning')
    return
  }
  try {
    if (editingId.value) {
      await apiUpdateCustomer(editingId.value, form.value)
      showToast('客户信息已更新', 'success')
    } else {
      await apiCreateCustomer(form.value)
      showToast('客户创建成功', 'success')
    }
    showModal.value = false
    await loadCustomers()
    await loadStats()
  } catch {
    showToast('操作失败，请重试', 'warning')
  }
}

// C6: Delete customer with confirmation
async function handleDeleteCustomer(id) {
  if (!await openConfirm({ title: 'Delete Customer', message: 'Are you sure you want to delete this customer? Associated order data will not be deleted.' })) return
  try {
    await apiDeleteCustomer(id)
    showToast('客户已删除', 'success')
    await loadCustomers()
    await loadStats()
  } catch {
    showToast('删除失败，请重试', 'warning')
  }
}

onMounted(() => {
  loadCustomers()
  loadStats()
  fetchCustomerTypes().then(data => { customerTypes.value = data || [] }).catch(() => {})
  fetchCustomerLevels().then(data => { customerLevels.value = data || [] }).catch(() => {})
})

onBeforeUnmount(() => {
  // Toast cleanup handled by useToast composable
})
</script>

<style scoped>
.customers-page {
  display: flex;
  flex-direction: column;
  gap: 16px;
}

.customer-stats {
  display: grid;
  grid-template-columns: repeat(4, 1fr);
  gap: 14px;
}
.stat-card {
  display: flex;
  align-items: center;
  gap: 14px;
  padding: 18px 20px;
}
.stat-icon {
  width: 44px;
  height: 44px;
  border-radius: 10px;
  display: flex;
  align-items: center;
  justify-content: center;
  flex-shrink: 0;
}
.stat-value {
  font-size: var(--font-size-2xl);
  font-weight: 700;
  color: var(--gray-900);
}
.stat-label {
  font-size: var(--font-size-xs);
  color: var(--gray-400);
  margin-top: 2px;
}

.filter-bar {
  padding: 14px 16px;
  display: flex;
  align-items: center;
  justify-content: space-between;
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
  min-width: 240px;
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

.view-toggle {
  display: flex;
  border: 1px solid var(--gray-200);
  border-radius: 8px;
  overflow: hidden;
}
.view-btn {
  padding: 7px 10px;
  border: none;
  background: none;
  cursor: pointer;
  color: var(--gray-400);
  transition: var(--transition-fast);
}
.view-btn.active {
  background: var(--primary);
  color: #fff;
}
.view-btn:hover:not(.active) {
  background: var(--gray-100);
}

/* Card View */
.customer-cards {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(240px, 1fr));
  gap: 14px;
}
.customer-card {
  padding: 20px;
  cursor: pointer;
  transition: var(--transition-fast);
}
.customer-card:hover {
  box-shadow: var(--shadow);
  transform: translateY(-2px);
}

.cc-header {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  margin-bottom: 12px;
}
.cc-avatar {
  width: 44px;
  height: 44px;
  border-radius: 12px;
  display: flex;
  align-items: center;
  justify-content: center;
  color: #fff;
  font-size: 18px;
  font-weight: 700;
}
.cc-name {
  font-size: var(--font-size-base);
  font-weight: 600;
  color: var(--gray-900);
  margin-bottom: 6px;
}
.cc-contact {
  display: flex;
  align-items: center;
  gap: 5px;
  font-size: var(--font-size-xs);
  color: var(--gray-500);
  margin-bottom: 4px;
}
.cc-stats {
  display: flex;
  align-items: center;
  margin-top: 14px;
  padding-top: 12px;
  border-top: 1px solid var(--gray-100);
}
.cc-stat {
  flex: 1;
  text-align: center;
}
.cc-stat-val {
  font-size: var(--font-size-base);
  font-weight: 700;
  color: var(--gray-800);
}
.cc-stat-label {
  font-size: 10px;
  color: var(--gray-400);
  margin-top: 1px;
}
.cc-stat-divider {
  width: 1px;
  background: var(--gray-100);
  height: 28px;
}
.text-success {
  color: var(--success);
}
.text-gray {
  color: var(--gray-400);
}

.customer-level {
  font-size: 11px;
  font-weight: 700;
  padding: 2px 8px;
  border-radius: 4px;
}
.cc-level {
  font-size: 10px;
  font-weight: 700;
  padding: 2px 7px;
  border-radius: 4px;
}
.level-S级 {
  background: linear-gradient(135deg, #fbbf24, #f59e0b);
  color: #fff;
}
.level-A级 {
  background: var(--primary-bg);
  color: var(--primary);
}
.level-B级 {
  background: var(--gray-100);
  color: var(--gray-600);
}
.level-C级 {
  background: var(--gray-100);
  color: var(--gray-400);
}

.table-card {
  overflow: hidden;
}

@media (max-width: 1100px) {
  .customer-stats {
    grid-template-columns: repeat(2, 1fr);
  }
}
@media (max-width: 768px) {
  .customer-stats {
    grid-template-columns: 1fr 1fr;
  }
}
</style>
