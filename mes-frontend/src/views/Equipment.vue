<template>
  <div class="equipment-page">
    <div class="page-header">
      <div>
        <div class="page-title">设备管理</div>
        <div class="page-subtitle">共 {{ filteredEquipment.length }} 台设备</div>
      </div>
      <div class="flex items-center gap-2">
        <input
          v-model="searchText"
          class="input"
          type="text"
          placeholder="搜索设备名称/型号"
          style="width: 200px; height: 32px; font-size: 13px;"
        />
        <button class="btn btn-primary btn-sm" @click="openAddModal">
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
        添加设备
      </button>
      </div>
    </div>

    <!-- Status Overview -->
    <div class="eq-status-row">
      <div v-for="s in statusOverview" :key="s.label" class="eq-status-card card">
        <div
          class="eq-status-icon"
          :style="`background:${s.color}15; color:${s.color}`"
          v-html="s.icon"
        ></div>
        <div class="eq-status-val">{{ s.count }}</div>
        <div class="eq-status-label">{{ s.label }}</div>
        <div class="eq-status-rate" :style="`color:${s.color}`">{{ s.rate }}</div>
      </div>
    </div>

    <!-- Equipment Cards -->
    <div v-if="!filteredEquipment.length && !loading" class="empty-state">无匹配设备</div>
    <div v-if="filteredEquipment.length" class="equipment-grid">
      <div v-for="eq in filteredEquipment" :key="eq.id" class="eq-card card" :class="`eq-${eq.status}`">
        <div class="eq-card-header">
          <div class="eq-status-badge" :class="`badge-${statusBadgeType(eq.status)}`">
            <span class="status-dot" :class="`dot-${eq.status}`"></span>
            {{ statusLabel(eq.status) }}
          </div>
          <div class="eq-card-actions">
            <div class="eq-oee">OEE {{ eq.oee }}%</div>
            <button class="btn btn-ghost btn-sm btn-icon" title="删除" @click="handleDeleteEquipment(eq.id)">
              <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
                <polyline points="3 6 5 6 21 6" />
                <path d="M19 6v14a2 2 0 0 1-2 2H7a2 2 0 0 1-2-2V6m3 0V4a2 2 0 0 1 2-2h4a2 2 0 0 1 2 2v2" />
              </svg>
            </button>
          </div>
        </div>
        <div class="eq-name">{{ eq.name }}</div>
        <div class="eq-model text-sm" style="color: var(--gray-400)">
          {{ eq.model }} · {{ eq.workshop }}
        </div>

        <div class="eq-metrics">
          <div class="eq-metric">
            <div class="eq-metric-val">{{ eq.utilization }}%</div>
            <div class="eq-metric-label">利用率</div>
          </div>
          <div class="eq-metric">
            <div class="eq-metric-val">{{ eq.faultCount }}</div>
            <div class="eq-metric-label">本月故障</div>
          </div>
          <div class="eq-metric">
            <div class="eq-metric-val">{{ eq.mtbf }}h</div>
            <div class="eq-metric-label">MTBF</div>
          </div>
        </div>

        <div class="eq-progress-section">
          <div class="eq-progress-label">
            <span class="text-xs" style="color: var(--gray-500)">今日利用率</span>
            <span class="text-xs font-medium">{{ eq.todayUtil }}%</span>
          </div>
          <div
            class="progress"
            :class="
              eq.status === 'running'
                ? 'progress-primary'
                : eq.status === 'idle'
                  ? 'progress-warning'
                  : 'progress-danger'
            "
          >
            <div class="progress-bar" :style="`width:${eq.todayUtil}%`"></div>
          </div>
        </div>

        <div class="eq-footer">
          <span class="text-xs" style="color: var(--gray-400)">下次保养：{{ eq.nextMaint }}</span>
          <button
            class="btn btn-ghost btn-sm"
            style="padding: 4px 8px; font-size: 12px"
            @click="openEditModal(eq)"
          >
            详情
          </button>
        </div>
      </div>
    </div>

    <!-- Add Equipment Modal (C7) -->
    <div v-if="showAddModal" class="modal-overlay" @click.self="showAddModal = false">
      <div class="modal" style="max-width: 480px">
        <div class="modal-header">
          <div class="modal-title">新增设备</div>
          <button class="btn btn-ghost btn-icon" @click="showAddModal = false">
            <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><line x1="18" y1="6" x2="6" y2="18"/><line x1="6" y1="6" x2="18" y2="18"/></svg>
          </button>
        </div>
        <div class="modal-body">
          <div class="form-row">
            <div class="form-group">
              <label class="form-label">设备名称 <span style="color: var(--danger)">*</span></label>
              <input v-model="eqForm.name" class="input" placeholder="如：WS-01" />
            </div>
            <div class="form-group">
              <label class="form-label">型号</label>
              <input v-model="eqForm.model" class="input" placeholder="设备型号" />
            </div>
          </div>
          <div class="form-row">
            <div class="form-group">
              <label class="form-label">车间</label>
              <input v-model="eqForm.workshop" class="input" placeholder="所在车间" />
            </div>
            <div class="form-group">
              <label class="form-label">状态</label>
              <select v-model="eqForm.status" class="select">
                <option value="running">运行中</option>
                <option value="idle">待机</option>
                <option value="maintenance">维护</option>
              </select>
            </div>
          </div>
        </div>
        <div class="modal-footer">
          <button class="btn btn-outline" @click="showAddModal = false">取消</button>
          <button class="btn btn-primary" @click="submitAddEquipment">确认添加</button>
        </div>
      </div>
    </div>

    <!-- Edit Equipment Modal -->
    <div v-if="showEditModal && editEquipmentData" class="modal-overlay" @click.self="showEditModal = false">
      <div class="modal" style="max-width: 520px">
        <div class="modal-header">
          <div class="modal-title">设备详情 / 编辑</div>
          <button class="btn btn-ghost btn-icon" @click="showEditModal = false">
            <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><line x1="18" y1="6" x2="6" y2="18"/><line x1="6" y1="6" x2="18" y2="18"/></svg>
          </button>
        </div>
        <div class="modal-body">
          <div class="form-row">
            <div class="form-group">
              <label class="form-label">设备名称 <span style="color: var(--danger)">*</span></label>
              <input v-model="editEquipmentData.name" class="input" placeholder="如：WS-01" />
            </div>
            <div class="form-group">
              <label class="form-label">型号</label>
              <input v-model="editEquipmentData.model" class="input" placeholder="设备型号" />
            </div>
          </div>
          <div class="form-row">
            <div class="form-group">
              <label class="form-label">车间</label>
              <input v-model="editEquipmentData.workshop" class="input" placeholder="所在车间" />
            </div>
            <div class="form-group">
              <label class="form-label">状态</label>
              <select v-model="editEquipmentData.status" class="select">
                <option value="running">运行中</option>
                <option value="idle">待机</option>
                <option value="maintenance">维护</option>
                <option value="offline">离线</option>
              </select>
            </div>
          </div>
          <div class="form-row">
            <div class="form-group">
              <label class="form-label">OEE (%)</label>
              <input v-model.number="editEquipmentData.oee" class="input" type="number" min="0" max="100" step="0.1" />
            </div>
            <div class="form-group">
              <label class="form-label">利用率 (%)</label>
              <input v-model.number="editEquipmentData.utilization" class="input" type="number" min="0" max="100" step="0.1" />
            </div>
          </div>
          <div class="form-row">
            <div class="form-group">
              <label class="form-label">本月故障次数</label>
              <input v-model.number="editEquipmentData.faultCount" class="input" type="number" min="0" step="1" />
            </div>
            <div class="form-group">
              <label class="form-label">MTBF (小时)</label>
              <input v-model.number="editEquipmentData.mtbf" class="input" type="number" min="0" step="0.1" />
            </div>
          </div>
          <div class="form-group">
            <label class="form-label">今日利用率 (%)</label>
            <input v-model.number="editEquipmentData.todayUtil" class="input" type="number" min="0" max="100" step="0.1" />
          </div>
          <div class="form-group">
            <label class="form-label">下次保养</label>
            <input v-model="editEquipmentData.nextMaint" class="input" type="date" />
          </div>
        </div>
        <div class="modal-footer">
          <button class="btn btn-outline" @click="showEditModal = false">取消</button>
          <button class="btn btn-primary" @click="submitEditEquipment">保存修改</button>
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
import { ref, computed, onMounted, onBeforeUnmount } from 'vue'
import DOMPurify from 'dompurify'
import { useToast } from '../composables/useToast.js'
import { useConfirm } from '../composables/useConfirm.js'
import {
  fetchEquipment,
  fetchEquipmentStats,
  createEquipment as apiCreateEquipment,
  deleteEquipment as apiDeleteEquipment,
  updateEquipment as apiUpdateEquipment
} from '../api/index.js'

const { toasts, showToast } = useToast()
const { openConfirm } = useConfirm()

const loading = ref(false)
const equipment = ref([])
const eqStatsData = ref({ running: 0, idle: 0, maintenance: 0, avgOee: 0 })
const showAddModal = ref(false)
const showEditModal = ref(false)
const editEquipmentData = ref(null)
const searchText = ref('')

const eqForm = ref({
  name: '',
  model: '',
  workshop: '',
  status: 'idle'
})

async function loadEquipment() {
  loading.value = true
  try {
    equipment.value = await fetchEquipment()
  } catch {
    equipment.value = []
  } finally {
    loading.value = false
  }
}

async function loadStats() {
  try {
    eqStatsData.value = await fetchEquipmentStats()
  } catch {
    // keep previous
  }
}

const statusOverview = computed(() => {
  const runCount =
    eqStatsData.value.running ||
    equipment.value.filter(e => e.status === 'running').length
  const idleCount =
    eqStatsData.value.idle ||
    equipment.value.filter(e => e.status === 'idle').length
  const maintCount =
    eqStatsData.value.maintenance ||
    equipment.value.filter(e => e.status === 'maintenance').length
  const total = equipment.value.length || 1
  const avgOee =
    eqStatsData.value.avgOee ||
    Math.round(
      equipment.value
        .filter(e => e.status !== 'maintenance')
        .reduce((s, e) => s + e.oee, 0) /
        (equipment.value.filter(e => e.status !== 'maintenance').length || 1)
    )
  return [
    {
      label: '运行中',
      count: runCount,
      rate: `${Math.round((runCount / total) * 100)}%`,
      color: '#10b981',
      icon: DOMPurify.sanitize('<svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><circle cx="12" cy="12" r="10"/><polyline points="12 6 12 12 16 14"/></svg>')
    },
    {
      label: '待机',
      count: idleCount,
      rate: '',
      color: '#f59e0b',
      icon: DOMPurify.sanitize('<svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><rect x="6" y="4" width="4" height="16"/><rect x="14" y="4" width="4" height="16"/></svg>')
    },
    {
      label: '维护中',
      count: maintCount,
      rate: '',
      color: '#ef4444',
      icon: DOMPurify.sanitize('<svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M14.7 6.3a1 1 0 0 0 0 1.4l1.6 1.6a1 1 0 0 0 1.4 0l3.77-3.77a6 6 0 0 1-7.94 7.94l-6.91 6.91a2.12 2.12 0 0 1-3-3l6.91-6.91a6 6 0 0 1 7.94-7.94l-3.76 3.76z"/></svg>')
    },
    {
      label: '综合OEE',
      count: `${avgOee}%`,
      rate: '目标>=85%',
      color: '#1a6ef5',
      icon: DOMPurify.sanitize('<svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><polyline points="22 12 18 12 15 21 9 3 6 12 2 12"/></svg>')
    }
  ]
})

function statusLabel(s) {
  return { running: '运行中', idle: '待机', maintenance: '维护' }[s] || s
}
function statusBadgeType(s) {
  return { running: 'success', idle: 'warning', maintenance: 'danger' }[s] || 'gray'
}

// H19: search/filter for equipment
const filteredEquipment = computed(() => {
  if (!searchText.value) return equipment.value
  const q = searchText.value.toLowerCase()
  return equipment.value.filter(
    e => e.name.toLowerCase().includes(q) || (e.model || '').toLowerCase().includes(q)
  )
})

// C7: Open add modal
function openAddModal() {
  eqForm.value = { name: '', model: '', workshop: '', status: 'idle' }
  showAddModal.value = true
}

// Open edit modal
function openEditModal(eq) {
  editEquipmentData.value = {
    id: eq.id,
    name: eq.name,
    model: eq.model,
    workshop: eq.workshop,
    status: eq.status,
    oee: eq.oee,
    utilization: eq.utilization,
    faultCount: eq.faultCount,
    mtbf: eq.mtbf,
    todayUtil: eq.todayUtil,
    nextMaint: eq.nextMaint
  }
  showEditModal.value = true
}

// Submit edit equipment
async function submitEditEquipment() {
  if (!editEquipmentData.value.name) {
    showToast('请填写设备名称', 'warning')
    return
  }
  // 数值范围校验
  const vals = editEquipmentData.value
  if (vals.oee != null && (vals.oee < 0 || vals.oee > 100)) {
    showToast('OEE 必须在 0 ~ 100 之间', 'warning'); return
  }
  if (vals.utilization != null && (vals.utilization < 0 || vals.utilization > 100)) {
    showToast('利用率必须在 0 ~ 100 之间', 'warning'); return
  }
  if (vals.todayUtil != null && (vals.todayUtil < 0 || vals.todayUtil > 100)) {
    showToast('今日利用率必须在 0 ~ 100 之间', 'warning'); return
  }
  if (vals.faultCount != null && vals.faultCount < 0) {
    showToast('故障次数不能小于 0', 'warning'); return
  }
  if (vals.mtbf != null && vals.mtbf < 0) {
    showToast('MTBF 不能小于 0', 'warning'); return
  }
  try {
    await apiUpdateEquipment(editEquipmentData.value.id, editEquipmentData.value)
    showEditModal.value = false
    showToast('设备更新成功', 'success')
    await loadEquipment()
    await loadStats()
  } catch {
    showToast('更新设备失败', 'warning')
  }
}

// C7: Submit add equipment
async function submitAddEquipment() {
  if (!eqForm.value.name) {
    showToast('请填写设备名称', 'warning')
    return
  }
  try {
    await apiCreateEquipment(eqForm.value)
    showAddModal.value = false
    showToast('设备添加成功', 'success')
    await loadEquipment()
    await loadStats()
  } catch {
    showToast('添加设备失败', 'warning')
  }
}

// C8: Delete equipment
async function handleDeleteEquipment(id) {
  if (!await openConfirm({ title: '删除设备', message: '确定要删除该设备吗？' })) return
  try {
    await apiDeleteEquipment(id)
    showToast('设备已删除', 'success')
    await loadEquipment()
    await loadStats()
  } catch {
    showToast('删除失败，请重试', 'warning')
  }
}

onMounted(() => {
  loadEquipment()
  loadStats()
})

onBeforeUnmount(() => {
  // Toast cleanup handled by useToast composable
})
</script>

<style scoped>
.equipment-page {
  display: flex;
  flex-direction: column;
  gap: 16px;
}
.eq-status-row {
  display: grid;
  grid-template-columns: repeat(4, 1fr);
  gap: 14px;
}
.eq-status-card {
  padding: 18px 20px;
  display: flex;
  flex-direction: column;
  align-items: center;
  text-align: center;
}
.eq-status-icon {
  width: 44px;
  height: 44px;
  border-radius: 10px;
  display: flex;
  align-items: center;
  justify-content: center;
  margin-bottom: 10px;
}
.eq-status-val {
  font-size: var(--font-size-2xl);
  font-weight: 700;
  color: var(--gray-900);
}
.eq-status-label {
  font-size: var(--font-size-xs);
  color: var(--gray-400);
  margin-top: 2px;
}
.eq-status-rate {
  font-size: var(--font-size-xs);
  font-weight: 600;
  margin-top: 4px;
}

.equipment-grid {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(280px, 1fr));
  gap: 14px;
}
.eq-card {
  padding: 18px;
  transition: var(--transition-fast);
}
.eq-card:hover {
  box-shadow: var(--shadow);
  transform: translateY(-2px);
}
.eq-running {
  border-top: 3px solid var(--success);
}
.eq-idle {
  border-top: 3px solid var(--warning);
}
.eq-maintenance {
  border-top: 3px solid var(--danger);
  opacity: 0.8;
}

.eq-card-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  margin-bottom: 10px;
}
.eq-status-badge {
  display: flex;
  align-items: center;
  gap: 5px;
  font-size: 12px;
  font-weight: 600;
  padding: 3px 8px;
  border-radius: 20px;
}
.badge-success {
  background: var(--success-bg);
  color: var(--success);
}
.badge-warning {
  background: var(--warning-bg);
  color: var(--warning);
}
.badge-danger {
  background: var(--danger-bg);
  color: var(--danger);
}

.status-dot {
  width: 6px;
  height: 6px;
  border-radius: 50%;
  flex-shrink: 0;
}
.dot-running {
  background: var(--success);
  animation: pulse 2s infinite;
}
.dot-idle {
  background: var(--warning);
}
.dot-maintenance {
  background: var(--danger);
}
@keyframes pulse {
  0%,
  100% {
    opacity: 1;
  }
  50% {
    opacity: 0.5;
  }
}

.eq-oee {
  font-size: 12px;
  font-weight: 700;
  color: var(--gray-500);
}
.eq-name {
  font-size: var(--font-size-base);
  font-weight: 600;
  color: var(--gray-900);
  margin-bottom: 3px;
}
.eq-model {
  margin-bottom: 14px;
}
.eq-metrics {
  display: flex;
  gap: 12px;
  margin-bottom: 14px;
  padding: 10px 0;
  border-top: 1px solid var(--gray-100);
  border-bottom: 1px solid var(--gray-100);
}
.eq-metric {
  flex: 1;
  text-align: center;
}
.eq-metric-val {
  font-size: var(--font-size-base);
  font-weight: 700;
  color: var(--gray-800);
}
.eq-metric-label {
  font-size: 10px;
  color: var(--gray-400);
  margin-top: 1px;
}
.eq-progress-section {
  margin-bottom: 12px;
}
.eq-progress-label {
  display: flex;
  justify-content: space-between;
  margin-bottom: 6px;
}
.eq-footer {
  display: flex;
  align-items: center;
  justify-content: space-between;
}

@media (max-width: 1100px) {
  .eq-status-row {
    grid-template-columns: repeat(2, 1fr);
  }
}

.eq-card-actions {
  display: flex;
  align-items: center;
  gap: 6px;
}

.empty-state {
  text-align: center;
  padding: 48px 24px;
  color: var(--gray-400);
  font-size: var(--font-size-sm);
}

/* Modal styles */
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
/* Toast */
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
.toast { background: var(--gray-800); color: #fff; }
.toast-success { background: var(--success); color: #fff; }
.toast-warning { background: var(--warning); color: #fff; }
.toast-info { background: var(--info); color: #fff; }
@keyframes slideIn {
  from { transform: translateX(100%); opacity: 0; }
  to { transform: translateX(0); opacity: 1; }
}
</style>
