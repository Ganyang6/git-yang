<template>
  <div class="video-analysis">
    <!-- Page Header -->
    <div class="page-header">
      <h1 class="page-title">视频分析</h1>
      <p class="page-subtitle">
        上传视频文件，自动分析工人操作并生成工时报告
      </p>
    </div>

    <div class="video-layout">
      <!-- Left: Upload + Current Task -->
      <div class="video-main">
        <!-- Upload Zone -->
        <div
          v-if="!currentTask"
          class="upload-drop-zone"
          :class="{ 'drop-active': isDragOver }"
          @dragover.prevent="isDragOver = true"
          @dragleave.prevent="isDragOver = false"
          @drop.prevent="handleDrop"
          @click="triggerFileInput"
        >
          <div class="upload-icon">
            <svg width="48" height="48" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5">
              <path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4" />
              <polyline points="17 8 12 3 7 8" />
              <line x1="12" y1="3" x2="12" y2="15" />
            </svg>
          </div>
          <p class="upload-text">拖拽视频文件到此处</p>
          <p class="upload-hint">或点击选择文件</p>
          <p class="upload-formats">支持格式：MP4, AVI, MOV, MKV（最大 500MB）</p>
          <input
            ref="fileInput"
            type="file"
            accept=".mp4,.avi,.mov,.mkv,video/mp4,video/avi,video/quicktime,video/x-matroska"
            style="display: none"
            @change="handleFileSelect"
          />
        </div>

        <!-- Station & Shift Selectors (outside clickable upload zone to avoid event conflicts) -->
        <div v-if="!currentTask" class="upload-config-area">
          <div class="station-selector">
            <label class="station-label">目标工位:</label>
            <select v-model="selectedStation" class="station-select" @click.stop>
              <option value="" disabled>请选择工位</option>
              <option v-for="s in stationOptions" :key="s.value" :value="s.value">
                {{ s.label }} ({{ s.value }})
              </option>
            </select>
          </div>
          <div class="shift-selector">
            <label class="station-label">班次:</label>
            <select v-model="selectedShift" class="station-select" @click.stop>
              <option value="" disabled>请选择班次</option>
              <option v-for="s in shiftOptions" :key="s.value" :value="s.value">
                {{ s.label }}
              </option>
            </select>
          </div>
          <div class="shift-selector">
            <label class="station-label">产线:</label>
            <select v-model="selectedLine" class="station-select" @click.stop>
              <option value="">全部产线</option>
              <option value="line1">产线 A</option>
              <option value="line2">产线 B</option>
            </select>
          </div>
        </div>

        <!-- Upload Error -->
        <div v-if="uploadError" class="upload-error">
          <span class="error-icon">!</span>
          <span>{{ uploadError }}</span>
        </div>

        <!-- Upload Progress (Uploading) -->
        <div v-if="currentTask && currentTask.status === 'uploaded'" class="task-status-card">
          <h3>正在上传...</h3>
          <p>任务 ID: {{ currentTask.task_id }}</p>
          <p>文件: {{ currentTask.filename }}</p>
          <div class="upload-spinner"></div>
        </div>

        <!-- Processing Progress -->
        <div
          v-if="currentTask && currentTask.status === 'processing'"
          class="task-status-card"
        >
          <h3>正在处理视频...</h3>
          <div class="progress-info">
            <span class="progress-percent">{{ progressPercent }}%</span>
            <span class="progress-frames">
              {{ currentTask.processed_frames || 0 }} / {{ currentTask.total_frames || '?' }} 帧
            </span>
          </div>
          <div class="progress-bar">
            <div
              class="progress-fill processing"
              :style="{ width: progressPercent + '%' }"
            ></div>
          </div>
          <p v-if="estimatedTimeRemaining" class="progress-eta">
            预计剩余时间: {{ estimatedTimeRemaining }}
          </p>
          <button class="btn btn-ghost" @click="handleCancel">取消</button>
        </div>

        <!-- Completed -->
        <div v-if="currentTask && currentTask.status === 'completed'" class="task-status-card task-completed">
          <div class="completion-icon">
            <svg width="48" height="48" viewBox="0 0 24 24" fill="none" stroke="#10b981" stroke-width="2">
              <circle cx="12" cy="12" r="10" />
              <polyline points="8 12 11 15 16 9" />
            </svg>
          </div>
          <h3>分析完成</h3>
          <div class="completion-stats">
            <div class="stat-item">
              <span class="stat-label">总帧数</span>
              <span class="stat-value">{{ currentTask.total_frames || 0 }}</span>
            </div>
            <div class="stat-item">
              <span class="stat-label">处理耗时</span>
              <span class="stat-value">{{ formatDuration(currentTask.duration_s) }}</span>
            </div>
            <div v-if="currentTask.segments_count" class="stat-item">
              <span class="stat-label">动作段数</span>
              <span class="stat-value">{{ currentTask.segments_count }}</span>
            </div>
          </div>
          <router-link to="/worktime" class="btn btn-primary">
            查看工时分析
          </router-link>
          <button class="btn btn-ghost" @click="resetCurrentTask">上传新视频</button>
        </div>

        <!-- Failed -->
        <div v-if="currentTask && currentTask.status === 'failed'" class="task-status-card task-failed">
          <div class="failure-icon">
            <svg width="48" height="48" viewBox="0 0 24 24" fill="none" stroke="#ef4444" stroke-width="2">
              <circle cx="12" cy="12" r="10" />
              <line x1="15" y1="9" x2="9" y2="15" />
              <line x1="9" y1="9" x2="15" y2="15" />
            </svg>
          </div>
          <h3>处理失败</h3>
          <p class="error-detail">{{ currentTask.error || '未知错误' }}</p>
          <button class="btn btn-primary" @click="resetCurrentTask">重试</button>
        </div>

        <!-- Pending state -->
        <div v-if="currentTask && currentTask.status === 'pending'" class="task-status-card">
          <h3>排队等待中...</h3>
          <p>当前有其他任务正在处理，您的任务将自动开始。</p>
        </div>
      </div>

      <!-- Right: Task History -->
      <div class="video-sidebar">
        <h3 class="sidebar-title">任务历史</h3>
        <div v-if="tasksLoading" class="loading-skeleton">
          <div v-for="i in 3" :key="i" class="skeleton-item">
            <div class="skeleton-line" style="width: 60%"></div>
            <div class="skeleton-line" style="width: 40%"></div>
          </div>
        </div>
        <div v-else-if="tasks.length === 0" class="empty-state">
          <p>暂无任务记录</p>
        </div>
        <div v-else class="task-list">
          <div
            v-for="task in tasks"
            :key="task.task_id"
            class="task-item"
            :class="`status-${task.status}`"
          >
            <div class="task-item-header">
              <span class="task-filename">{{ task.filename }}</span>
              <span class="task-status-badge" :class="task.status">
                {{ statusLabel(task.status) }}
              </span>
            </div>
            <div class="task-item-meta">
              <span>{{ formatFileSize(task.size) }}</span>
              <span v-if="task.station_id || task.shift">{{ [task.station_id, task.shift].filter(Boolean).join(' | ') }}</span>
              <span v-if="task.progress != null && task.status === 'processing'">
                {{ Math.round(task.progress * 100) }}%
              </span>
            </div>
          </div>
        </div>
      </div>
    </div>
  </div>
</template>

<script setup>
import { ref, computed, onMounted, onUnmounted } from 'vue'
import {
  uploadVideo,
  fetchVideoTasks,
  cancelVideoTask,
  validateVideoFile,
  streamVideoProgress,
  fetchVideoStations
} from '../api/index.js'

// -- State --
const currentTask = ref(null)
const tasks = ref([])
const tasksLoading = ref(false)
const isDragOver = ref(false)
const uploadError = ref('')
const fileInput = ref(null)
const selectedStation = ref('')
const stationOptions = ref([
  { value: 'WS-01', label: '工位 1' },
  { value: 'WS-02', label: '工位 2' },
  { value: 'WS-03', label: '工位 3' }
])
const selectedShift = ref('morning')
const selectedLine = ref('')
const shiftOptions = [
  { value: 'morning', label: '早班' },
  { value: 'afternoon', label: '中班' },
  { value: 'night', label: '晚班' }
]
let closeSSE = null
let pollTimer = null

// -- Progress computation --
const progressPercent = computed(() => {
  if (!currentTask.value) return 0
  return Math.round((currentTask.value.progress || 0) * 100)
})

const estimatedTimeRemaining = computed(() => {
  const task = currentTask.value
  if (!task || task.status !== 'processing' || !task.processed_frames || task.processed_frames === 0) {
    return ''
  }
  const framesPerSecond = task.processed_frames / Math.max(task.elapsed_s || 1, 0.1)
  const remaining = Math.max(0, (task.total_frames || 0) - task.processed_frames) / framesPerSecond
  if (remaining > 3600) return `${Math.round(remaining / 3600)}h ${Math.round((remaining % 3600) / 60)}m`
  if (remaining > 60) return `${Math.round(remaining / 60)}m ${Math.round(remaining % 60)}s`
  return `${Math.round(remaining)}s`
})

// -- File handling --
function triggerFileInput() {
  if (fileInput.value) fileInput.value.click()
}

function handleFileSelect(event) {
  const file = event.target.files?.[0]
  if (file) processFile(file)
  // Reset input so same file can be re-selected
  if (fileInput.value) fileInput.value.value = ''
}

function handleDrop(event) {
  isDragOver.value = false
  const file = event.dataTransfer?.files?.[0]
  if (file) processFile(file)
}

async function processFile(file) {
  if (!selectedStation.value) {
    uploadError.value = '请先选择工位'
    return
  }
  uploadError.value = ''

  // Validate file size (max 500MB)
  const MAX_SIZE = 500 * 1024 * 1024
  if (file.size > MAX_SIZE) {
    uploadError.value = `文件大小 ${(file.size / (1024 * 1024)).toFixed(1)}MB 超过限制 (500MB)`
    return
  }

  // Validate file format
  const validation = validateVideoFile(file)
  if (!validation.valid) {
    uploadError.value = validation.reason
    return
  }

  try {
    const result = await uploadVideo(file, selectedStation.value, selectedShift.value, selectedLine.value)
    currentTask.value = result
    startProgressStream(result.task_id)
    // Refresh task list
    loadTasks()
  } catch (err) {
    uploadError.value = err.message || 'Upload failed'
  }
}

// -- SSE progress streaming --
function startProgressStream(taskId) {
  // Close previous connection if any
  if (closeSSE) {
    closeSSE()
    closeSSE = null
  }

  let startTime = Date.now()

  const { close } = streamVideoProgress(taskId, (data) => {
    if (!currentTask.value) return
    const elapsed = (Date.now() - startTime) / 1000
    currentTask.value = {
      ...currentTask.value,
      status: data.status,
      progress: data.progress,
      total_frames: data.total_frames,
      processed_frames: data.processed_frames,
      duration_s: data.duration_s,
      error: data.error,
      elapsed_s: elapsed
    }

    // Auto-refresh task list on terminal states
    if (data.status === 'completed' || data.status === 'failed') {
      loadTasks()
    }
  })

  closeSSE = close
}

// -- Cancel --
async function handleCancel() {
  const taskId = currentTask.value?.task_id
  if (closeSSE) {
    closeSSE()
    closeSSE = null
  }
  if (taskId) {
    try {
      await cancelVideoTask(taskId)
    } catch {
      // 即使 API 失败也关闭本地 UI
    }
  }
  resetCurrentTask()
}

// -- Reset --
function resetCurrentTask() {
  if (closeSSE) {
    closeSSE()
    closeSSE = null
  }
  currentTask.value = null
  uploadError.value = ''
}

// -- Task list --
async function loadTasks() {
  tasksLoading.value = true
  try {
    const result = await fetchVideoTasks()
    tasks.value = result?.items || result || []
  } catch {
    tasks.value = []
  } finally {
    tasksLoading.value = false
  }
}

// -- Formatters --
function formatFileSize(bytes) {
  if (!bytes) return '0 B'
  const units = ['B', 'KB', 'MB', 'GB']
  let i = 0
  let size = bytes
  while (size >= 1024 && i < units.length - 1) {
    size /= 1024
    i++
  }
  return `${size.toFixed(1)} ${units[i]}`
}

function formatDuration(seconds) {
  if (!seconds) return '0s'
  if (seconds < 60) return `${Math.round(seconds)}s`
  return `${Math.floor(seconds / 60)}m ${Math.round(seconds % 60)}s`
}

function statusLabel(status) {
  const labels = {
    pending: '排队中',
    uploaded: '已上传',
    processing: '处理中',
    completed: '已完成',
    failed: '已失败',
    cancelled: '已取消'
  }
  return labels[status] || status
}

// -- Lifecycle --
async function fetchStations() {
  try {
    const data = await fetchVideoStations()
    stationOptions.value = (data || []).map(item => ({
      value: item.id,
      label: item.name
    }))
    if (stationOptions.value.length > 0 && !selectedStation.value) {
      selectedStation.value = stationOptions.value[0].value
    }
  } catch {
    // API 失败时保留初始 fallback 值
  }
}

onMounted(() => {
  loadTasks()
  fetchStations()
  // 每 5 秒刷新任务列表
  pollTimer = setInterval(() => loadTasks(), 5000)

  // 页面不可见时暂停轮询和 SSE
  document.addEventListener('visibilitychange', handleVisibilityChange)
})

onUnmounted(() => {
  clearInterval(pollTimer)
  if (closeSSE) {
    closeSSE()
    closeSSE = null
  }
  document.removeEventListener('visibilitychange', handleVisibilityChange)
})

// -- Visibility handling --
function handleVisibilityChange() {
  if (document.hidden) {
    // Pause
    if (pollTimer) {
      clearInterval(pollTimer)
      pollTimer = null
    }
    if (closeSSE) {
      closeSSE()
      closeSSE = null
    }
  } else {
    // Resume
    loadTasks()
    pollTimer = setInterval(() => loadTasks(), 5000)
    if (currentTask.value && (currentTask.value.status === 'uploaded' || currentTask.value.status === 'processing')) {
      startProgressStream(currentTask.value.task_id)
    }
  }
}
</script>

<style scoped>
.video-analysis {
  padding: 24px;
  max-width: 1200px;
  margin: 0 auto;
}

.page-header {
  margin-bottom: 24px;
}

.page-title {
  font-size: 24px;
  font-weight: 700;
  color: var(--gray-900);
  margin: 0 0 4px;
}

.page-subtitle {
  font-size: 14px;
  color: var(--gray-500);
  margin: 0;
}

.video-layout {
  display: grid;
  grid-template-columns: 1fr 320px;
  gap: 24px;
}

/* Upload Zone */
.upload-drop-zone {
  border: 2px dashed var(--gray-300);
  border-radius: 12px;
  padding: 48px 24px;
  text-align: center;
  cursor: pointer;
  transition: all 0.2s;
  background: var(--white);
}

.upload-drop-zone:hover,
.upload-drop-zone.drop-active {
  border-color: var(--blue-500);
  background: var(--blue-50);
}

.upload-icon {
  color: var(--gray-400);
  margin-bottom: 16px;
}

.upload-drop-zone:hover .upload-icon,
.upload-drop-zone.drop-active .upload-icon {
  color: var(--blue-500);
}

.upload-text {
  font-size: 16px;
  font-weight: 600;
  color: var(--gray-700);
  margin: 0 0 4px;
}

.upload-hint {
  font-size: 14px;
  color: var(--gray-400);
  margin: 0 0 8px;
}

.upload-formats {
  font-size: 12px;
  color: var(--gray-400);
  margin: 0;
}

.upload-config-area {
  display: flex;
  align-items: center;
  justify-content: center;
  gap: 24px;
  margin-top: 12px;
  padding: 8px 16px;
  background: var(--white);
  border: 1px solid var(--gray-200);
  border-radius: 8px;
}

.station-selector {
  display: flex;
  align-items: center;
  gap: 8px;
}

.station-label {
  font-size: 14px;
  color: var(--gray-600);
}

.station-select {
  padding: 4px 8px;
  border: 1px solid var(--gray-300);
  border-radius: 6px;
  font-size: 13px;
  color: var(--gray-700);
  background: var(--white);
  cursor: pointer;
}

.station-select:focus {
  outline: none;
  border-color: var(--blue-400);
  box-shadow: 0 0 0 2px var(--blue-100);
}

.upload-spinner {
  width: 32px;
  height: 32px;
  border: 3px solid var(--gray-200);
  border-top-color: var(--blue-500);
  border-radius: 50%;
  animation: spin 0.8s linear infinite;
  margin: 16px auto;
}

@keyframes spin {
  to { transform: rotate(360deg); }
}

.upload-error {
  margin-top: 12px;
  padding: 12px 16px;
  background: var(--red-50);
  border: 1px solid var(--red-200);
  border-radius: 8px;
  color: var(--red-700);
  font-size: 14px;
  display: flex;
  align-items: center;
  gap: 8px;
}

.error-icon {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  width: 20px;
  height: 20px;
  border-radius: 50%;
  background: var(--red-500);
  color: white;
  font-size: 12px;
  font-weight: 700;
  flex-shrink: 0;
}

/* Task Status Cards */
.task-status-card {
  background: var(--white);
  border: 1px solid var(--gray-200);
  border-radius: 12px;
  padding: 24px;
  text-align: center;
}

.task-status-card h3 {
  font-size: 18px;
  font-weight: 600;
  color: var(--gray-800);
  margin: 0 0 16px;
}

.task-completed {
  border-color: var(--green-200);
  background: var(--green-50);
}

.task-failed {
  border-color: var(--red-200);
  background: var(--red-50);
}

.completion-icon,
.failure-icon {
  margin-bottom: 12px;
}

.completion-stats {
  display: flex;
  justify-content: center;
  gap: 32px;
  margin-bottom: 24px;
}

.stat-item {
  display: flex;
  flex-direction: column;
  align-items: center;
}

.stat-label {
  font-size: 12px;
  color: var(--gray-500);
  margin-bottom: 4px;
}

.stat-value {
  font-size: 20px;
  font-weight: 700;
  color: var(--gray-800);
}

.error-detail {
  font-size: 14px;
  color: var(--red-600);
  margin-bottom: 16px;
}

.btn {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  padding: 8px 20px;
  border-radius: 8px;
  font-size: 14px;
  font-weight: 500;
  cursor: pointer;
  border: none;
  transition: all 0.15s;
  margin: 4px;
}

.btn-primary {
  background: var(--blue-500);
  color: white;
}

.btn-primary:hover {
  background: var(--blue-600);
}

.btn-ghost {
  background: transparent;
  color: var(--gray-600);
  border: 1px solid var(--gray-300);
}

.btn-ghost:hover {
  background: var(--gray-100);
}

/* Progress Bar */
.progress-info {
  display: flex;
  justify-content: space-between;
  align-items: center;
  margin-bottom: 8px;
}

.progress-percent {
  font-size: 24px;
  font-weight: 700;
  color: var(--blue-600);
}

.progress-frames {
  font-size: 14px;
  color: var(--gray-500);
}

.progress-bar {
  height: 8px;
  background: var(--gray-200);
  border-radius: 4px;
  overflow: hidden;
  margin-bottom: 8px;
}

.progress-fill {
  height: 100%;
  border-radius: 4px;
  transition: width 0.3s;
}

.progress-fill.processing {
  background: linear-gradient(90deg, var(--blue-400), var(--blue-600));
}

@keyframes pulse {
  0%, 100% { opacity: 1; }
  50% { opacity: 0.5; }
}

.progress-eta {
  font-size: 13px;
  color: var(--gray-500);
  margin-bottom: 12px;
}

/* Sidebar */
.sidebar-title {
  font-size: 16px;
  font-weight: 600;
  color: var(--gray-700);
  margin: 0 0 12px;
}

.task-list {
  display: flex;
  flex-direction: column;
  gap: 8px;
}

.task-item {
  background: var(--white);
  border: 1px solid var(--gray-200);
  border-radius: 8px;
  padding: 12px;
  transition: border-color 0.15s;
}

.task-item:hover {
  border-color: var(--gray-300);
}

.task-item-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  margin-bottom: 4px;
}

.task-filename {
  font-size: 14px;
  font-weight: 500;
  color: var(--gray-800);
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
  max-width: 180px;
}

.task-status-badge {
  font-size: 11px;
  font-weight: 600;
  padding: 2px 8px;
  border-radius: 12px;
  text-transform: uppercase;
  flex-shrink: 0;
}

.task-status-badge.pending {
  background: var(--gray-100);
  color: var(--gray-600);
}

.task-status-badge.uploaded {
  background: var(--blue-100);
  color: var(--blue-700);
}

.task-status-badge.processing {
  background: var(--blue-100);
  color: var(--blue-700);
}

.task-status-badge.completed {
  background: var(--green-100);
  color: var(--green-700);
}

.task-status-badge.failed {
  background: var(--red-100);
  color: var(--red-700);
}

.task-status-badge.cancelled {
  background: var(--gray-100);
  color: var(--gray-500);
}

.task-item-meta {
  display: flex;
  gap: 12px;
  font-size: 12px;
  color: var(--gray-500);
}

/* Loading skeleton */
.loading-skeleton {
  display: flex;
  flex-direction: column;
  gap: 12px;
}

.skeleton-item {
  background: var(--white);
  border: 1px solid var(--gray-200);
  border-radius: 8px;
  padding: 12px;
}

.skeleton-line {
  height: 12px;
  background: var(--gray-200);
  border-radius: 4px;
  margin-bottom: 8px;
  animation: shimmer 1.5s infinite;
}

@keyframes shimmer {
  0% { opacity: 0.5; }
  50% { opacity: 1; }
  100% { opacity: 0.5; }
}

.empty-state {
  text-align: center;
  padding: 24px;
  color: var(--gray-400);
  font-size: 14px;
}

/* Responsive */
@media (max-width: 768px) {
  .video-layout {
    grid-template-columns: 1fr;
  }

  .completion-stats {
    gap: 16px;
  }

  .stat-value {
    font-size: 16px;
  }
}
</style>
