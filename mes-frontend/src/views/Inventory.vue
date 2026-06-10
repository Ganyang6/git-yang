<template>
  <div class="inventory-page">
    <div class="page-header">
      <div>
        <div class="page-title">库存管理</div>
        <div class="page-subtitle">共 {{ filteredItems.length }} 种物料</div>
      </div>
      <div class="flex gap-2">
        <button class="btn btn-outline btn-sm" @click="showInbound = true">
          <svg
            width="14"
            height="14"
            viewBox="0 0 24 24"
            fill="none"
            stroke="currentColor"
            stroke-width="2"
          >
            <path d="M12 5v14M5 12l7 7 7-7" />
          </svg>
          入库
        </button>
        <button
          class="btn btn-outline btn-sm"
          style="color: var(--danger); border-color: var(--danger)"
          @click="showOutbound = true"
        >
          <svg
            width="14"
            height="14"
            viewBox="0 0 24 24"
            fill="none"
            stroke="currentColor"
            stroke-width="2"
          >
            <path d="M12 19V5M5 12l7-7 7 7" />
          </svg>
          出库
        </button>
        <button class="btn btn-primary btn-sm" @click="showAddItem = true">
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
          新增物料
        </button>
        <button class="btn btn-outline btn-sm" @click="handleExport">
          <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
            <path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4"/>
            <polyline points="7 10 12 15 17 10"/>
            <line x1="12" y1="15" x2="12" y2="3"/>
          </svg>
          导出
        </button>
      </div>
    </div>

    <!-- Alert -->
    <div v-if="lowStockItems.length > 0" class="alert-bar">
      <svg
        width="16"
        height="16"
        viewBox="0 0 24 24"
        fill="none"
        stroke="currentColor"
        stroke-width="2"
      >
        <path
          d="M10.29 3.86L1.82 18a2 2 0 0 0 1.71 3h16.94a2 2 0 0 0 1.71-3L13.71 3.86a2 2 0 0 0-3.42 0z"
        />
        <line x1="12" y1="9" x2="12" y2="13" />
        <line x1="12" y1="17" x2="12.01" y2="17" />
      </svg>
      <span
        ><strong>{{ lowStockItems.length }} 种物料</strong>库存低于预警线，请及时补货</span
      >
      <button
        class="btn btn-sm"
        style="background: rgba(255, 255, 255, 0.2); color: #fff; border: none; margin-left: auto"
        @click="filterAlert = !filterAlert"
      >
        {{ filterAlert ? '显示全部' : '只看预警' }}
      </button>
    </div>

    <!-- Stats -->
    <div class="inv-stats">
      <div v-for="s in invStats" :key="s.label" class="inv-stat-card card">
        <div class="inv-stat-val" :style="`color:${s.color}`">{{ s.value }}</div>
        <div class="inv-stat-label">{{ s.label }}</div>
      </div>
    </div>

    <!-- Filter -->
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
            placeholder="搜索物料编码、名称..."
            class="search-input-inline"
          />
        </div>
        <select v-model="filterCategory" class="select" style="width: 130px">
          <option value="">全部类别</option>
          <option v-for="c in categories" :key="c" :value="c">{{ c }}</option>
        </select>
        <select v-model="filterWarehouse" class="select" style="width: 130px">
          <option value="">全部仓库</option>
          <option v-for="w in warehouses" :key="w" :value="w">{{ w }}</option>
        </select>
      </div>
    </div>

    <!-- Table -->
    <div class="card" style="overflow: hidden">
      <div class="table-wrapper">
        <table class="table">
          <thead>
            <tr>
              <th>物料编码</th>
              <th>物料名称</th>
              <th>规格型号</th>
              <th>类别</th>
              <th>单位</th>
              <th>当前库存</th>
              <th>安全库存</th>
              <th>库存状态</th>
              <th>仓库位置</th>
              <th>单价(元)</th>
              <th>库存金额(元)</th>
              <th>最近入库</th>
              <th>操作</th>
            </tr>
          </thead>
          <tbody>
            <tr v-if="loading"><td colspan="13" class="text-center">加载中...</td></tr>
            <tr v-for="item in filteredItems" :key="item.code">
              <td>
                <span style="font-family: monospace; font-size: 12px; color: var(--primary)">{{
                  item.code
                }}</span>
              </td>
              <td class="text-sm font-medium">{{ item.name }}</td>
              <td class="text-sm" style="color: var(--gray-400)">{{ item.spec }}</td>
              <td>
                <span class="badge badge-gray">{{ item.category }}</span>
              </td>
              <td class="text-sm">{{ item.unit }}</td>
              <td>
                <span
                  class="font-medium"
                  :style="
                    item.stock <= item.safeStock
                      ? 'color:var(--danger)'
                      : item.stock <= item.safeStock * 1.5
                        ? 'color:var(--warning)'
                        : 'color:var(--gray-800)'
                  "
                >
                  {{ item.stock.toLocaleString() }}
                </span>
              </td>
              <td class="text-sm" style="color: var(--gray-400)">
                {{ item.safeStock.toLocaleString() }}
              </td>
              <td>
                <span class="badge" :class="stockStatusClass(item)">{{ stockStatus(item) }}</span>
              </td>
              <td class="text-sm">{{ item.location }}</td>
              <td class="text-sm">{{ formatPrice(item.price) }}</td>
              <td class="text-sm font-medium">{{ formatPrice(item.stock * item.price, 0) }}</td>
              <td class="text-sm" style="color: var(--gray-400)">{{ item.lastIn }}</td>
              <td>
                <div class="flex gap-1">
                  <button
                    class="btn btn-ghost btn-sm btn-icon"
                    title="入库"
                    @click="openRowInbound(item)"
                  >
                    <svg
                      width="13"
                      height="13"
                      viewBox="0 0 24 24"
                      fill="none"
                      stroke="currentColor"
                      stroke-width="2"
                    >
                      <path d="M12 5v14M5 12l7 7 7-7" />
                    </svg>
                  </button>
                  <button
                    class="btn btn-ghost btn-sm btn-icon"
                    title="出库"
                    @click="openRowOutbound(item)"
                  >
                    <svg
                      width="13"
                      height="13"
                      viewBox="0 0 24 24"
                      fill="none"
                      stroke="currentColor"
                      stroke-width="2"
                    >
                      <path d="M12 19V5M5 12l7-7 7 7" />
                    </svg>
                  </button>
                  <button
                    class="btn btn-ghost btn-sm btn-icon"
                    title="删除"
                    @click="handleDeleteItem(item)"
                  >
                    <svg
                      width="13"
                      height="13"
                      viewBox="0 0 24 24"
                      fill="none"
                      stroke="currentColor"
                      stroke-width="2"
                    >
                      <polyline points="3 6 5 6 21 6" />
                      <path d="M19 6v14a2 2 0 0 1-2 2H7a2 2 0 0 1-2-2V6m3 0V4a2 2 0 0 1 2-2h4a2 2 0 0 1 2 2v2" />
                      <line x1="10" y1="11" x2="10" y2="17" />
                      <line x1="14" y1="11" x2="14" y2="17" />
                    </svg>
                  </button>
                </div>
              </td>
            </tr>
          </tbody>
        </table>
      </div>
      <div class="table-footer">
        <div class="pagination-controls">
          <button
            class="btn btn-xs btn-outline"
            :disabled="currentPage <= 1"
            @click="currentPage--"
          >上一页</button>
          <span class="text-sm" style="color: var(--gray-500); padding: 0 8px">
            第 {{ currentPage }} / {{ totalPages }} 页（共 {{ totalItems }} 种物料）
          </span>
          <button
            class="btn btn-xs btn-outline"
            :disabled="currentPage >= totalPages"
            @click="currentPage++"
          >下一页</button>
        </div>
        <span class="text-sm font-medium"
          >总库存金额：<span style="color: var(--primary)">{{ totalAmount }}</span> 元</span
        >
      </div>
    </div>

    <!-- Inbound Modal (C3) -->
    <div v-if="showInbound" class="modal-overlay" @click.self="showInbound = false">
      <div class="modal" style="max-width: 420px">
        <div class="modal-header">
          <div class="modal-title">入库操作</div>
          <button class="btn btn-ghost btn-icon" @click="showInbound = false">
            <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><line x1="18" y1="6" x2="6" y2="18"/><line x1="6" y1="6" x2="18" y2="18"/></svg>
          </button>
        </div>
        <div class="modal-body">
          <div class="form-group">
            <label class="form-label">物料编码 <span style="color: var(--danger)">*</span></label>
            <select v-model="inboundForm.itemCode" class="select">
              <option value="">请选择物料</option>
              <option v-for="item in inventory" :key="item.code" :value="item.code">{{ item.code }} - {{ item.name }}</option>
            </select>
          </div>
          <div class="form-group">
            <label class="form-label">入库数量 <span style="color: var(--danger)">*</span></label>
            <input v-model.number="inboundForm.qty" class="input" type="number" placeholder="0" min="1" />
          </div>
          <div class="form-group">
            <label class="form-label">备注</label>
            <input v-model="inboundForm.remark" class="input" placeholder="可选" />
          </div>
        </div>
        <div class="modal-footer">
          <button class="btn btn-outline" @click="showInbound = false">取消</button>
          <button class="btn btn-primary" @click="submitInbound">确认入库</button>
        </div>
      </div>
    </div>

    <!-- Outbound Modal (C3) -->
    <div v-if="showOutbound" class="modal-overlay" @click.self="showOutbound = false">
      <div class="modal" style="max-width: 420px">
        <div class="modal-header">
          <div class="modal-title">出库操作</div>
          <button class="btn btn-ghost btn-icon" @click="showOutbound = false">
            <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><line x1="18" y1="6" x2="6" y2="18"/><line x1="6" y1="6" x2="18" y2="18"/></svg>
          </button>
        </div>
        <div class="modal-body">
          <div class="form-group">
            <label class="form-label">物料编码 <span style="color: var(--danger)">*</span></label>
            <select v-model="outboundForm.itemCode" class="select">
              <option value="">请选择物料</option>
              <option v-for="item in inventory" :key="item.code" :value="item.code">{{ item.code }} - {{ item.name }} (库存: {{ item.stock }})</option>
            </select>
          </div>
          <div class="form-group">
            <label class="form-label">出库数量 <span style="color: var(--danger)">*</span></label>
            <input v-model.number="outboundForm.qty" class="input" type="number" placeholder="0" min="1" />
          </div>
          <div class="form-group">
            <label class="form-label">备注</label>
            <input v-model="outboundForm.remark" class="input" placeholder="可选" />
          </div>
        </div>
        <div class="modal-footer">
          <button class="btn btn-outline" @click="showOutbound = false">取消</button>
          <button class="btn btn-primary" @click="submitOutbound">确认出库</button>
        </div>
      </div>
    </div>

    <!-- Add Item Modal (C3) -->
    <div v-if="showAddItem" class="modal-overlay" @click.self="showAddItem = false">
      <div class="modal">
        <div class="modal-header">
          <div class="modal-title">新增物料</div>
          <button class="btn btn-ghost btn-icon" @click="showAddItem = false">
            <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><line x1="18" y1="6" x2="6" y2="18"/><line x1="6" y1="6" x2="18" y2="18"/></svg>
          </button>
        </div>
        <div class="modal-body">
          <div class="form-row">
            <div class="form-group">
              <label class="form-label">物料编码 <span style="color: var(--danger)">*</span></label>
              <input v-model="addItemForm.code" class="input" placeholder="如：MAT-001" />
            </div>
            <div class="form-group">
              <label class="form-label">物料名称 <span style="color: var(--danger)">*</span></label>
              <input v-model="addItemForm.name" class="input" placeholder="请输入物料名称" />
            </div>
          </div>
          <div class="form-row">
            <div class="form-group">
              <label class="form-label">规格型号</label>
              <input v-model="addItemForm.spec" class="input" placeholder="规格描述" />
            </div>
            <div class="form-group">
              <label class="form-label">类别</label>
              <select v-model="addItemForm.category" class="select">
                <option v-for="c in categories" :key="c" :value="c">{{ c }}</option>
              </select>
            </div>
          </div>
          <div class="form-row">
            <div class="form-group">
              <label class="form-label">单位</label>
              <input v-model="addItemForm.unit" class="input" placeholder="个/件/kg" />
            </div>
            <div class="form-group">
              <label class="form-label">安全库存</label>
              <input v-model.number="addItemForm.safeStock" class="input" type="number" placeholder="0" min="0" />
            </div>
          </div>
          <div class="form-row">
            <div class="form-group">
              <label class="form-label">仓库位置</label>
              <select v-model="addItemForm.location" class="select">
                <option v-for="w in warehouses" :key="w" :value="w">{{ w }}</option>
              </select>
            </div>
            <div class="form-group">
              <label class="form-label">单价(元)</label>
              <input v-model.number="addItemForm.price" class="input" type="number" placeholder="0.00" min="0" step="0.01" />
            </div>
          </div>
        </div>
        <div class="modal-footer">
          <button class="btn btn-outline" @click="showAddItem = false">取消</button>
          <button class="btn btn-primary" @click="submitAddItem">确认新增</button>
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
import { watchDebounced } from '@vueuse/core'
import { useToast } from '../composables/useToast.js'
import {
  fetchInventory,
  fetchInventoryStats,
  inboundStock as apiInbound,
  outboundStock as apiOutbound,
  createInventoryItem as apiCreateItem,
  deleteInventoryItem
} from '../api/index.js'
import { useConfirm } from '@/composables/useConfirm'

const { toasts, showToast } = useToast()
const { openConfirm } = useConfirm()

const searchText = ref('')
const filterCategory = ref('')
const filterWarehouse = ref('')
const filterAlert = ref(false)
const showInbound = ref(false)
const showOutbound = ref(false)
const showAddItem = ref(false)
const loading = ref(false)

// Pagination state
const currentPage = ref(1)
const pageSize = ref(20)
const totalItems = ref(0)

const totalPages = computed(() => Math.max(1, Math.ceil(totalItems.value / pageSize.value)))

// Reset to page 1 when any filter changes
watch([filterCategory, filterWarehouse, filterAlert, searchText], () => {
  currentPage.value = 1
})

// Reload when page changes
watch(currentPage, () => {
  loadInventory()
})

const categories = ['原材料', '标准件', '外购件', '半成品', '成品']
const warehouses = ['A仓-原材料区', 'B仓-零部件区', 'C仓-成品区', 'D仓-半成品区']

const inventory = ref([])
const invStatsData = ref({ totalItems: 0, lowStockCount: 0, totalValue: '0', warehouseCount: 4 })

// Inbound/Outbound/AddItem form data
const inboundForm = ref({ itemCode: '', qty: '', remark: '' })
const outboundForm = ref({ itemCode: '', qty: '', remark: '' })
const addItemForm = ref({
  code: '', name: '', spec: '', category: '原材料', unit: '个',
  safeStock: 0, location: 'A仓-原材料区', price: 0, warehouse: ''
})

async function loadInventory() {
  loading.value = true
  try {
    const params = {
      category: filterCategory.value || undefined,
      warehouse: filterWarehouse.value
        ? filterWarehouse.value.split('-')[0]
        : undefined,
      keyword: searchText.value || undefined,
      lowStockOnly: filterAlert.value || undefined,
      page: currentPage.value,
      page_size: pageSize.value
    }
    const resp = await fetchInventory(params)
    if (resp && resp.items) {
      inventory.value = resp.items
      totalItems.value = resp.total || resp.items.length
    } else if (Array.isArray(resp)) {
      inventory.value = resp
      totalItems.value = resp.length
    } else {
      inventory.value = []
      totalItems.value = 0
    }
  } catch {
    inventory.value = []
    totalItems.value = 0
  } finally {
    loading.value = false
  }
}

async function loadStats() {
  try {
    invStatsData.value = await fetchInventoryStats()
  } catch {
    // keep previous
  }
}

const lowStockItems = computed(() => inventory.value.filter(i => i.stock <= i.safeStock))

const invStats = computed(() => [
  {
    label: '物料总数',
    value: invStatsData.value.totalItems || inventory.value.length,
    color: '#1a6ef5'
  },
  {
    label: '库存预警',
    value: invStatsData.value.lowStockCount || lowStockItems.value.length,
    color: '#ef4444'
  },
  {
    label: '总库存金额(万)',
    value:
      invStatsData.value.totalValue ||
      (inventory.value.reduce((s, i) => s + i.stock * i.price, 0) / 10000).toFixed(2),
    color: '#10b981'
  },
  {
    label: '仓库数量',
    value: invStatsData.value.warehouseCount || warehouses.length,
    color: '#f59e0b'
  }
])

watch([filterCategory, filterWarehouse, filterAlert], () => {
  loadInventory()
})

watchDebounced(
  searchText,
  () => {
    loadInventory()
  },
  { debounce: 300, maxWait: 1000 }
)

const filteredItems = computed(() => {
  return inventory.value.filter(i => {
    if (filterAlert.value && i.stock > i.safeStock) return false
    if (filterCategory.value && i.category !== filterCategory.value) return false
    if (filterWarehouse.value && !i.location.startsWith(filterWarehouse.value.split('-')[0]))
      return false
    if (searchText.value) {
      const q = searchText.value.toLowerCase()
      if (!i.code.toLowerCase().includes(q) && !i.name.toLowerCase().includes(q)) return false
    }
    return true
  })
})

const totalAmount = computed(() => {
  return filteredItems.value.reduce((s, i) => s + i.stock * i.price, 0).toFixed(0)
})

function stockStatus(item) {
  if (item.stock === 0) return '缺货'
  if (item.stock <= item.safeStock) return '库存不足'
  if (item.stock <= item.safeStock * 1.5) return '库存偏低'
  return '库存正常'
}

function stockStatusClass(item) {
  if (item.stock === 0) return 'badge-danger'
  if (item.stock <= item.safeStock) return 'badge-danger'
  if (item.stock <= item.safeStock * 1.5) return 'badge-warning'
  return 'badge-success'
}

// H9: null-safe price formatting
function formatPrice(val, decimals = 2) {
  if (val == null || isNaN(val)) return '0'
  return Number(val).toFixed(decimals)
}

// C3+C4: Modal openers for row-level operations
function openRowInbound(item) {
  inboundForm.value = { itemCode: item.code, qty: '', remark: '' }
  showInbound.value = true
}

function openRowOutbound(item) {
  outboundForm.value = { itemCode: item.code, qty: '', remark: '' }
  showOutbound.value = true
}

// Delete item with confirmation
async function handleDeleteItem(item) {
  if (item.stock > 0) {
    showToast('库存不为空，不能删除', 'warning')
    return
  }
  try {
    if (!await openConfirm({ title: '删除确认', message: `确定要删除物料 ${item.code} - ${item.name} 吗？` })) return
    await deleteInventoryItem(item.code)
    showToast('删除成功', 'success')
    await loadInventory()
    await loadStats()
  } catch (err) {
    if (err !== 'cancel') {
      showToast(err.message || '删除失败', 'error')
    }
  }
}

// Inbound submit with validation
async function submitInbound() {
  if (!inboundForm.value.itemCode || !inboundForm.value.qty || inboundForm.value.qty <= 0) {
    showToast('请填写物料和入库数量', 'warning')
    return
  }
  await handleInbound(inboundForm.value)
}

// C3: Outbound submit with validation (H16: prevent negative stock)
async function submitOutbound() {
  if (!outboundForm.value.itemCode || !outboundForm.value.qty || outboundForm.value.qty <= 0) {
    showToast('请填写物料和出库数量', 'warning')
    return
  }
  // P2 #91: 校验出库数量不超过当前库存
  const item = inventory.value.find(i => i.code === outboundForm.value.itemCode)
  if (item && outboundForm.value.qty > item.stock) {
    showToast(`出库数量不能超过当前库存 (${item.stock})`, 'warning')
    return
  }
  await handleOutbound(outboundForm.value)
}

// C3: Add item submit with validation
async function submitAddItem() {
  if (!addItemForm.value.code || !addItemForm.value.name) {
    showToast('请填写物料编码和名称', 'warning')
    return
  }
  // 确保数字字段类型正确（后端期望 price: float, safeStock: int）
  const payload = {
    ...addItemForm.value,
    price: Number(addItemForm.value.price) || 0,
    safeStock: Number(addItemForm.value.safeStock) || 0
  }
  await handleAddItem(payload)
}

async function handleInbound(data) {
  try {
    await apiInbound({ code: data.itemCode, qty: data.qty, remark: data.remark })
    showInbound.value = false
    showToast('入库成功', 'success')
    await loadInventory()
    await loadStats()
  } catch {
    showToast('入库操作失败', 'warning')
  }
}

async function handleOutbound(data) {
  try {
    await apiOutbound({ code: data.itemCode, qty: data.qty, remark: data.remark })
    showOutbound.value = false
    showToast('出库成功', 'success')
    await loadInventory()
    await loadStats()
  } catch {
    showToast('出库操作失败', 'warning')
  }
}

async function handleAddItem(data) {
  try {
    // 从 location 自动推导 warehouse
    const loc = data.location || ''
    data.warehouse = loc.includes('-') ? loc.split('-')[0] : loc
    await apiCreateItem(data)
    showAddItem.value = false
    showToast('物料新增成功', 'success')
    await loadInventory()
    await loadStats()
  } catch {
    showToast('新增物料失败', 'warning')
  }
}

// P2 #92: Export inventory as CSV
function handleExport() {
  if (filteredItems.value.length === 0) {
    showToast('没有可导出的数据', 'warning')
    return
  }
  const headers = ['物料编码', '物料名称', '类别', '仓库位置', '库存数量', '安全库存', '单价', '库存金额']
  const rows = filteredItems.value.map(item => [
    item.code, item.name, item.category || '', item.location || '',
    item.stock, item.safeStock || 0, item.price || 0,
    (item.stock * (item.price || 0)).toFixed(2)
  ])
  // BOM + CRLF for Excel compatibility
  const csv = '\uFEFF' + [headers, ...rows].map(r =>
    r.map(c => {
      const s = String(c)
      return s.includes(',') || s.includes('"') || s.includes('\n')
        ? '"' + s.replace(/"/g, '""') + '"'
        : s
    }).join(',')
  ).join('\r\n')
  const blob = new Blob([csv], { type: 'text/csv;charset=utf-8' })
  const url = URL.createObjectURL(blob)
  const a = document.createElement('a')
  a.href = url
  a.download = `inventory_${new Date().toISOString().slice(0, 10)}.csv`
  a.click()
  URL.revokeObjectURL(url)
  showToast('导出成功', 'success')
}

onMounted(() => {
  loadInventory()
  loadStats()
})

onBeforeUnmount(() => {
  // Toast cleanup handled by useToast composable
})
</script>

<style scoped>
.inventory-page {
  display: flex;
  flex-direction: column;
  gap: 16px;
}

.alert-bar {
  display: flex;
  align-items: center;
  gap: 10px;
  background: linear-gradient(135deg, #ef4444, #dc2626);
  color: #fff;
  padding: 12px 18px;
  border-radius: var(--border-radius-lg);
  font-size: var(--font-size-sm);
}

.inv-stats {
  display: grid;
  grid-template-columns: repeat(4, 1fr);
  gap: 14px;
}
.inv-stat-card {
  padding: 18px 20px;
  text-align: center;
}
.inv-stat-val {
  font-size: var(--font-size-2xl);
  font-weight: 700;
}
.inv-stat-label {
  font-size: var(--font-size-xs);
  color: var(--gray-400);
  margin-top: 4px;
}

.filter-bar {
  padding: 14px 16px;
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

.table-footer {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 12px 16px;
  border-top: 1px solid var(--gray-100);
}

@media (max-width: 1100px) {
  .inv-stats {
    grid-template-columns: repeat(2, 1fr);
  }
}

/* Modal styles (shared with Orders) */
.modal-overlay {
  position: fixed;
  inset: 0;
  background: rgba(0, 0, 0, 0.4);
  display: flex;
  align-items: center;
  justify-content: center;
  z-index: 1000;
}
.modal {
  background: var(--white, #fff);
  border-radius: var(--border-radius-lg, 12px);
  box-shadow: var(--shadow-lg, 0 20px 60px rgba(0, 0, 0, 0.15));
  width: 90%;
  max-width: 520px;
  max-height: 90vh;
  overflow-y: auto;
}
.modal-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 18px 20px;
  border-bottom: 1px solid var(--gray-100);
}
.modal-title {
  font-size: 16px;
  font-weight: 600;
  color: var(--gray-800);
}
.modal-body {
  padding: 20px;
}
.modal-footer {
  display: flex;
  justify-content: flex-end;
  gap: 10px;
  padding: 14px 20px;
  border-top: 1px solid var(--gray-100);
}
.form-group {
  margin-bottom: 14px;
}
.form-label {
  display: block;
  font-size: 13px;
  font-weight: 500;
  color: var(--gray-700);
  margin-bottom: 5px;
}
.form-row {
  display: flex;
  gap: 14px;
}
.form-row .form-group {
  flex: 1;
}
/* Toast (C9) */
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
  border-radius: var(--border-radius, 8px);
  box-shadow: var(--shadow-lg);
  font-size: var(--font-size-sm);
  min-width: 240px;
  animation: slideIn 0.3s ease;
}
.pagination-controls {
  display: flex;
  align-items: center;
  gap: 4px;
}
.btn-xs {
  padding: 4px 10px;
  font-size: 12px;
  line-height: 1.4;
  border-radius: 6px;
}
.toast { background: var(--gray-800); color: #fff; }
.toast-success { background: var(--success); color: #fff; }
.toast-warning { background: var(--warning); color: #fff; }
.toast-info { background: var(--info); color: #fff; }
@keyframes slideIn {
  from { transform: translateX(100%); opacity: 0; }
  to { transform: translateX(0); opacity: 1; }
}
</style>
