<template>
  <div class="stations-page">
    <div class="page-header">
      <div>
        <div class="page-title">工位管理</div>
        <div class="page-subtitle">共 {{ filteredStations.length }} 个工位</div>
      </div>
      <div class="flex items-center gap-2">
        <input
          v-model="searchText"
          class="input"
          type="text"
          placeholder="搜索工位名称"
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
          添加工位
        </button>
      </div>
    </div>

    <!-- Stations Table -->
    <div v-if="loading" class="empty-state">加载中...</div>
    <div v-else-if="!filteredStations.length && stations.length > 0" class="empty-state">无匹配工位</div>
    <div v-else-if="!stations.length" class="empty-state">暂无工位数据，请添加工位</div>
    <div v-else class="card" style="overflow: hidden;">
      <table class="table">
        <thead>
          <tr>
            <th>编号</th>
            <th>操作人</th>
            <th>产线</th>
            <th>班次</th>
            <th style="width: 120px;">操作</th>
          </tr>
        </thead>
        <tbody>
          <tr v-for="st in filteredStations" :key="st.id">
            <td class="font-medium">{{ st.name }}</td>
            <td>{{ st.worker }}</td>
            <td>{{ st.line }}</td>
            <td>{{ st.shift }}</td>
            <td>
              <div class="table-actions">
                <button class="btn btn-ghost btn-sm btn-icon" title="编辑" @click="openEditModal(st)">
                  <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
                    <path d="M11 4H4a2 2 0 0 0-2 2v14a2 2 0 0 0 2 2h14a2 2 0 0 0 2-2v-7" />
                    <path d="M18.5 2.5a2.121 2.121 0 0 1 3 3L12 15l-4 1 1-4 9.5-9.5z" />
                  </svg>
                </button>
                <button class="btn btn-ghost btn-sm btn-icon" title="删除" style="color: var(--danger);" @click="handleDeleteStation(st.id)">
                  <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
                    <polyline points="3 6 5 6 21 6" />
                    <path d="M19 6v14a2 2 0 0 1-2 2H7a2 2 0 0 1-2-2V6m3 0V4a2 2 0 0 1 2-2h4a2 2 0 0 1 2 2v2" />
                  </svg>
                </button>
              </div>
            </td>
          </tr>
        </tbody>
      </table>
    </div>

    <!-- Add Station Modal -->
    <div v-if="showAddModal" class="modal-overlay" @click.self="showAddModal = false">
      <div class="modal" style="max-width: 480px">
        <div class="modal-header">
          <div class="modal-title">添加工位</div>
          <button class="btn btn-ghost btn-icon" @click="showAddModal = false">
            <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><line x1="18" y1="6" x2="6" y2="18"/><line x1="6" y1="6" x2="18" y2="18"/></svg>
          </button>
        </div>
        <div class="modal-body">
          <div class="form-group">
            <label class="form-label">编号 <span style="color: var(--danger)">*</span></label>
            <input v-model="stationForm.name" class="input" placeholder="如：WS-01" />
          </div>
          <div class="form-group">
            <label class="form-label">操作人 <span style="color: var(--danger)">*</span></label>
            <input v-model="stationForm.worker" class="input" placeholder="操作人姓名" />
          </div>
          <div class="form-group">
            <label class="form-label">产线 <span style="color: var(--danger)">*</span></label>
            <input v-model="stationForm.line" class="input" placeholder="如：组装产线" />
          </div>
          <div class="form-group">
            <label class="form-label">班次 <span style="color: var(--danger)">*</span></label>
            <input v-model="stationForm.shift" class="input" placeholder="如：早班" />
          </div>
        </div>
        <div class="modal-footer">
          <button class="btn btn-outline" @click="showAddModal = false">取消</button>
          <button class="btn btn-primary" @click="submitAddStation">确认添加</button>
        </div>
      </div>
    </div>

    <!-- Edit Station Modal -->
    <div v-if="showEditModal && editStationData" class="modal-overlay" @click.self="showEditModal = false">
      <div class="modal" style="max-width: 480px">
        <div class="modal-header">
          <div class="modal-title">编辑工位</div>
          <button class="btn btn-ghost btn-icon" @click="showEditModal = false">
            <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><line x1="18" y1="6" x2="6" y2="18"/><line x1="6" y1="6" x2="18" y2="18"/></svg>
          </button>
        </div>
        <div class="modal-body">
          <div class="form-group">
            <label class="form-label">编号</label>
            <input :value="editStationData.name" class="input" disabled placeholder="编号不可更改" />
          </div>
          <div class="form-group">
            <label class="form-label">操作人 <span style="color: var(--danger)">*</span></label>
            <input v-model="editStationData.worker" class="input" placeholder="操作人姓名" />
          </div>
          <div class="form-group">
            <label class="form-label">产线 <span style="color: var(--danger)">*</span></label>
            <input v-model="editStationData.line" class="input" placeholder="如：组装产线" />
          </div>
          <div class="form-group">
            <label class="form-label">班次 <span style="color: var(--danger)">*</span></label>
            <input v-model="editStationData.shift" class="input" placeholder="如：早班" />
          </div>
        </div>
        <div class="modal-footer">
          <button class="btn btn-outline" @click="showEditModal = false">取消</button>
          <button class="btn btn-primary" @click="submitEditStation">保存修改</button>
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
import { ref, computed, onMounted } from 'vue'
import { useToast } from '../composables/useToast.js'
import { useConfirm } from '../composables/useConfirm.js'
import {
  fetchStations,
  createStation,
  updateStation,
  deleteStation
} from '../api/index.js'

const { toasts, showToast } = useToast()
const { openConfirm } = useConfirm()

const loading = ref(false)
const stations = ref([])
const showAddModal = ref(false)
const showEditModal = ref(false)
const editStationData = ref(null)
const searchText = ref('')

const stationForm = ref({
  name: '',
  worker: '',
  line: '',
  shift: ''
})

async function loadStations() {
  loading.value = true
  try {
    stations.value = await fetchStations()
  } catch {
    stations.value = []
  } finally {
    loading.value = false
  }
}

const filteredStations = computed(() => {
  if (!searchText.value) return stations.value
  const q = searchText.value.toLowerCase()
  return stations.value.filter(
    st => st.name.toLowerCase().includes(q) ||
      st.worker.toLowerCase().includes(q) ||
      st.line.toLowerCase().includes(q) ||
      st.shift.toLowerCase().includes(q)
  )
})

function openAddModal() {
  stationForm.value = { name: '', worker: '', line: '', shift: '' }
  showAddModal.value = true
}

function openEditModal(st) {
  editStationData.value = {
    id: st.id,
    name: st.name,
    worker: st.worker,
    line: st.line,
    shift: st.shift
  }
  showEditModal.value = true
}

async function submitAddStation() {
  if (!stationForm.value.name || !stationForm.value.worker || !stationForm.value.line || !stationForm.value.shift) {
    showToast('请填写完整信息', 'warning')
    return
  }
  try {
    await createStation(stationForm.value)
    showAddModal.value = false
    showToast('工位添加成功', 'success')
    await loadStations()
  } catch {
    showToast('添加工位失败', 'warning')
  }
}

async function submitEditStation() {
  if (!editStationData.value.worker || !editStationData.value.line || !editStationData.value.shift) {
    showToast('请填写完整信息', 'warning')
    return
  }
  const payload = {
    worker: editStationData.value.worker,
    line: editStationData.value.line,
    shift: editStationData.value.shift
  }
  try {
    await updateStation(editStationData.value.id, payload)
    showEditModal.value = false
    showToast('工位更新成功', 'success')
    await loadStations()
  } catch {
    showToast('更新工位失败', 'warning')
  }
}

async function handleDeleteStation(id) {
  if (!await openConfirm({ title: '删除工位', message: '确定要删除该工位吗？' })) return
  try {
    await deleteStation(id)
    showToast('工位已删除', 'success')
    await loadStations()
  } catch {
    showToast('删除失败，请重试', 'warning')
  }
}

onMounted(() => {
  loadStations()
})
</script>

<style scoped>
.stations-page {
  display: flex;
  flex-direction: column;
  gap: 16px;
}

/* Table styles */
.table {
  width: 100%;
  border-collapse: collapse;
  font-size: var(--font-size-sm);
}
.table thead {
  background: var(--gray-50);
}
.table th {
  padding: 12px 16px;
  text-align: left;
  font-weight: 600;
  font-size: 12px;
  color: var(--gray-500);
  text-transform: uppercase;
  letter-spacing: 0.05em;
  border-bottom: 1px solid var(--gray-100);
}
.table td {
  padding: 12px 16px;
  border-bottom: 1px solid var(--gray-100);
  color: var(--gray-700);
}
.table tbody tr:hover {
  background: var(--gray-50);
}
.table tbody tr:last-child td {
  border-bottom: none;
}
.font-medium {
  font-weight: 600;
  color: var(--gray-900);
}
.table-actions {
  display: flex;
  gap: 4px;
}
.table-actions .btn-icon {
  width: 28px;
  height: 28px;
  padding: 0;
  display: inline-flex;
  align-items: center;
  justify-content: center;
  border-radius: 6px;
}
.table-actions .btn-icon:hover {
  background: var(--gray-100);
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
