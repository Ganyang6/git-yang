<template>
  <div class="ai-page">
    <!-- Page Header -->
    <div class="page-header">
      <div>
        <div class="page-title">AI 深度分析</div>
        <div class="page-subtitle">DeepSeek - 瓶颈分析 - 标杆对比 - 改善方案 - 多轮问答</div>
      </div>
      <div class="flex gap-2 items-center">
        <div class="model-badge">
          <span class="model-dot"></span>
          DeepSeek-V3
        </div>
        <button class="btn btn-ghost btn-sm" @click="clearAll">
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
          清空
        </button>
      </div>
    </div>

    <div class="ai-layout">
      <!-- Left: Context Panel -->
      <div class="context-panel card">
        <div class="context-header">
          <div class="context-title">产线数据</div>
          <div class="context-subtitle">自动注入聊天上下文</div>
        </div>

        <div class="context-section">
          <div class="ctx-section-label">
            产线状态
            <button
              class="ctx-refresh-btn"
              :disabled="ctxLoading"
              title="刷新"
              @click="loadContext"
            >
              <svg
                width="11"
                height="11"
                viewBox="0 0 24 24"
                fill="none"
                stroke="currentColor"
                stroke-width="2.5"
                :class="ctxLoading ? 'spin' : ''"
              >
                <path d="M23 4v6h-6" />
                <path d="M1 20v-6h6" />
                <path d="M3.51 9a9 9 0 0 1 14.85-3.36L23 10M1 14l4.64 4.36A9 9 0 0 0 20.49 15" />
              </svg>
            </button>
          </div>
          <template v-if="ctxLoading">
            <div class="ctx-item"><span class="ctx-key">加载中...</span></div>
          </template>
          <template v-else-if="!aiContext">
            <div class="ctx-item no-data">无法获取产线数据，请连接后端并刷新</div>
          </template>
          <template v-else>
            <div class="ctx-item">
              <span class="ctx-key">平衡率</span>
              <span
                class="ctx-val"
                :class="
                  aiContext.balanceRate >= 85
                    ? 'val-success'
                    : aiContext.balanceRate >= 70
                      ? 'val-warning'
                      : 'val-danger'
                "
              >
                {{ aiContext.balanceRate }}%
              </span>
            </div>
            <div class="ctx-item">
              <span class="ctx-key">瓶颈工位</span>
              <span class="ctx-val val-danger">{{ aiContext.bottleneckStation || '--' }}</span>
            </div>
            <div class="ctx-item">
              <span class="ctx-key">节拍时间</span>
              <span class="ctx-val">{{ aiContext.taktTime }}s</span>
            </div>
            <div class="ctx-item">
              <span class="ctx-key">产能损失</span>
              <span class="ctx-val val-danger">{{ aiContext.lostCapacity }}件/天</span>
            </div>
          </template>
        </div>

        <div class="context-section">
          <div class="ctx-section-label">工时指标</div>
          <template v-if="!aiContext">
            <div class="ctx-item no-data">--</div>
          </template>
          <template v-else>
            <div class="ctx-item">
              <span class="ctx-key">利用率</span>
              <span class="ctx-val">{{ aiContext.utilization }}%</span>
            </div>
            <div class="ctx-item">
              <span class="ctx-key">标准工时达成率</span>
              <span class="ctx-val val-success">{{ aiContext.stdtimeAchievement }}%</span>
            </div>
            <div class="ctx-item">
              <span class="ctx-key">非增值比</span>
              <span class="ctx-val val-warning">{{ aiContext.wasteRatio }}%</span>
            </div>
          </template>
        </div>

        <!-- Quick Actions: Async Task Submission -->
        <div class="context-section">
          <div class="ctx-section-label">快速分析</div>
          <div class="preset-btns">
            <button
              v-for="q in presetQuestions"
              :key="q.id"
              class="preset-btn"
              :disabled="!aiContext"
              @click="sendPresetChat(buildPresetText(q))"
            >
              {{ q.label }}
            </button>
          </div>
        </div>

        <!-- Async Task Submission Buttons -->
        <div class="context-section">
          <div class="ctx-section-label">异步分析任务</div>
          <div class="preset-btns">
            <button
              class="preset-btn preset-btn-task"
              :disabled="!aiContext"
              @click="submitAsyncTask('worktime', { station_id: 'all' })"
            >
              工时深度分析
            </button>
            <button
              class="preset-btn preset-btn-task"
              :disabled="!aiContext"
              @click="submitAsyncTask('line_balance', { line_id: 'line1' })"
            >
              产线平衡报告
            </button>
            <button
              class="preset-btn preset-btn-task"
              :disabled="!aiContext"
              @click="submitAsyncTask('anomaly', { station_id: aiContext?.bottleneckStation })"
            >
              异常检测
            </button>
          </div>
        </div>

        <div class="context-section">
          <div class="ctx-section-label">
            AI 服务状态
            <span class="status-dot" :class="aiConfigured ? 'status-ok' : 'status-off'"></span>
          </div>
          <div class="ctx-item">
            <span class="ctx-key">状态</span>
            <span class="ctx-val" :class="aiConfigured ? 'val-success' : 'val-danger'">
              {{ aiConfigured ? '已配置' : '未配置' }}
            </span>
          </div>
          <template v-if="aiHealthData">
            <div class="ctx-item">
              <span class="ctx-key">API</span>
              <span class="ctx-val" :class="aiHealthData.deepseek_ok ? 'val-success' : 'val-danger'">
                {{ aiHealthData.deepseek_ok ? '在线' : '离线' }}
              </span>
            </div>
            <div class="ctx-item">
              <span class="ctx-key">缓存命中</span>
              <span class="ctx-val">{{ aiHealthData.cache_hit_rate ?? 0 }}%</span>
            </div>
          </template>
          <div v-if="!aiConfigured" class="ctx-item no-data">
            请设置 DEEPSEEK_API_KEY 环境变量或在 config.yaml 中配置 app.ai.api_key
          </div>
        </div>
      </div>

      <!-- Right: Chat Window -->
      <div class="chat-panel card">
        <!-- Messages -->
        <div ref="chatContainer" class="chat-messages">
          <!-- Welcome -->
          <div v-if="chatMessages.length === 0 && asyncTasks.length === 0" class="chat-welcome">
            <div class="welcome-icon">
              <svg
                width="32"
                height="32"
                viewBox="0 0 24 24"
                fill="none"
                stroke="currentColor"
                stroke-width="1.5"
              >
                <path d="M12 2a10 10 0 1 0 10 10" />
                <path d="M12 12l4-4" />
                <circle cx="18" cy="6" r="3" />
              </svg>
            </div>
            <div class="welcome-title">AI 工时分析助手</div>
            <div class="welcome-desc">基于实时产线数据，提供瓶颈分析、改善建议和行业标杆对比</div>
            <div class="welcome-tips">
              <div
                v-for="tip in presetQuestions.slice(0, 4)"
                :key="tip.id"
                class="welcome-tip"
                @click="sendPresetChat(buildPresetText(tip))"
              >
                {{ tip.label }}
              </div>
            </div>
          </div>

          <!-- Message List -->
          <template v-else>
            <ChatMessage
              v-for="msg in chatMessages"
              :key="msg.id"
              :role="msg.role"
              :content="msg.content"
              :is-streaming="msg.isStreaming"
              :is-fallback="msg.isFallback"
              :fallback-severity="msg.fallbackSeverity || 'cache'"
              :timestamp="msg.timestamp"
            />

            <!-- Async Tasks Panel (shown below chat messages) -->
            <div v-if="asyncTasks.length > 0" class="async-tasks-panel">
              <div class="async-tasks-header">
                <span>异步分析任务</span>
                <button class="btn-clear-tasks" @click="clearCompletedTasks" v-if="hasCompletedTasks">
                  清除已完成
                </button>
              </div>
              <TaskStatusCard
                v-for="task in asyncTasks"
                :key="task.taskId"
                :task-id="task.taskId"
                :analysis-type="task.analysisType"
                :status="task.status"
                :progress="task.progress"
                :result="task.result"
                :error="task.error"
                :created-at="task.createdAt"
                :params="task.params"
                :cancelling="task.cancelling"
                @cancel="handleCancelTask"
                @view="handleViewResult"
                @retry="handleRetryTask"
              />
            </div>
          </template>
        </div>

        <!-- Input Area -->
        <div class="chat-input-area">
          <div class="chat-input-wrap">
            <textarea
              ref="textarea"
              v-model="inputText"
              class="chat-textarea"
              placeholder="输入问题，例如：WS-03 瓶颈的根本原因是什么？如何用 ECRS 方法改善？"
              rows="1"
              @keydown.enter.exact.prevent="handleSendChat"
              @input="autoResize"
            ></textarea>
            <button
              class="send-btn"
              :disabled="!inputText.trim() || isStreaming"
              @click="handleSendChat"
            >
              <svg
                v-if="!isStreaming"
                width="18"
                height="18"
                viewBox="0 0 24 24"
                fill="none"
                stroke="currentColor"
                stroke-width="2.5"
              >
                <line x1="22" y1="2" x2="11" y2="13" />
                <polygon points="22 2 15 22 11 13 2 9 22 2" />
              </svg>
              <svg
                v-else
                class="spin"
                width="18"
                height="18"
                viewBox="0 0 24 24"
                fill="none"
                stroke="currentColor"
                stroke-width="2"
              >
                <path d="M21 12a9 9 0 1 1-6.219-8.56" />
              </svg>
            </button>
          </div>
          <div class="input-hint">
            回车发送，Shift+回车换行，产线上下文自动注入
            <span v-if="isStreaming" class="stream-hint">
              &middot; 按 <button class="btn-inline" @click="abortChat">ESC</button> 停止生成
            </span>
          </div>
        </div>
      </div>
    </div>
  </div>
</template>

<script setup>
import { ref, computed, nextTick, onMounted, onUnmounted, watch } from 'vue'
import {
  fetchAiContext,
  fetchAiStatus,
  fetchAiHealth,
  fetchTaskStatus,
  submitAiTask
} from '../api/index.js'
import { useSSEChat } from '../composables/useSSEChat.js'
import { useToast } from '../composables/useToast.js'
import ChatMessage from '../components/ChatMessage.vue'
import TaskStatusCard from '../components/TaskStatusCard.vue'

// ─── State ────────────────────────────────────────────────────────────────────
const inputText = ref('')
const chatContainer = ref(null)
const textarea = ref(null)
const { showToast } = useToast()

const ctxLoading = ref(false)
const aiContext = ref(null)
const aiConfigured = ref(false)
const aiHealthData = ref(null)

const asyncTasks = ref([]) // Track submitted async tasks

// ─── Polling Manager (supports multiple concurrent tasks) ────────────────────
const pollingTimers = new Map() // taskId -> intervalId

function startTaskPolling(taskId) {
  stopTaskPolling(taskId)
  let pollCount = 0
  const MAX_POLLS = 150 // 2s * 150 = 5min timeout
  const timer = setInterval(async () => {
    pollCount++
    if (pollCount >= MAX_POLLS) {
      updateAsyncTask(taskId, { status: 'failed', error: '任务超时' })
      stopTaskPolling(taskId)
      return
    }
    try {
      const status = await fetchTaskStatus(taskId)
      const updates = { status: status.status, progress: status.progress || 0 }
      if (status.status === 'completed') {
        updates.result = status.result
        updateAsyncTask(taskId, updates)
        stopTaskPolling(taskId)
      } else if (status.status === 'failed') {
        updates.error = status.error || '任务失败'
        updateAsyncTask(taskId, updates)
        stopTaskPolling(taskId)
      } else {
        updateAsyncTask(taskId, updates)
      }
    } catch (err) {
      updateAsyncTask(taskId, { status: 'failed', error: err.message })
      stopTaskPolling(taskId)
    }
  }, 2000)
  pollingTimers.set(taskId, timer)
}

function stopTaskPolling(taskId) {
  const timer = pollingTimers.get(taskId)
  if (timer) {
    clearInterval(timer)
    pollingTimers.delete(taskId)
  }
}

// ─── SSE Chat Composable ─────────────────────────────────────────────────────
const {
  messages: sseMessages,
  isStreaming,
  error: sseChatError,
  sendChat,
  addMessage,
  abort: abortChat
} = useSSEChat({
  onFallback(event) {
    // Show toast notification for degradation (event is full {type, message} object)
    console.warn('AI fallback triggered:', event.message)
  }
})

// Map sseMessages to template-friendly format
const chatMessages = computed(() => sseMessages.value)

// Show toast when SSE chat encounters an error
watch(sseChatError, (err) => {
  if (err) showToast(err, 'error')
})

// ─── Preset Questions ─────────────────────────────────────────────────────────
const presetQuestions = [
  { id: 1, label: '分析瓶颈根因', key: 'bottleneck_cause' },
  { id: 2, label: '生成ECRS改善方案', key: 'ecrs_plan' },
  { id: 3, label: '标准工时评估', key: 'std_time_eval' },
  { id: 4, label: '行业标杆对比', key: 'benchmark' },
  { id: 5, label: '利用率提升建议', key: 'utilization_improve' },
  { id: 6, label: '产能恢复方案', key: 'capacity_recover' }
]

function buildPresetText(q) {
  const ctx = aiContext.value
  if (!ctx) return '请等待产线数据加载后再提问。'
  const templates = {
    bottleneck_cause: `分析 ${ctx.bottleneckStation} 成为瓶颈的根本原因，并给出具体改善措施。当前平衡率 ${ctx.balanceRate}%，节拍时间 ${ctx.taktTime}s。`,
    ecrs_plan: `根据当前产线数据（平衡率 ${ctx.balanceRate}%，瓶颈工位 ${ctx.bottleneckStation}，产能损失 ${ctx.lostCapacity} 件/天），生成完整的 ECRS 改善方案，按优先级排序。`,
    std_time_eval: `当前利用率 ${ctx.utilization}%，标准工时达成率 ${ctx.stdtimeAchievement}%，非增值比 ${ctx.wasteRatio}%。请评估标准工时设定的合理性，分析可能的作业方法问题。`,
    benchmark: `我们当前产线平衡率为 ${ctx.balanceRate}%，利用率 ${ctx.utilization}%。离散制造业的行业标杆水平是多少？我们处于什么位置？`,
    utilization_improve: `当前利用率 ${ctx.utilization}%，非增值比 ${ctx.wasteRatio}%。请分析主要非增值来源，提供动作改善建议。`,
    capacity_recover: `瓶颈工位 ${ctx.bottleneckStation} 导致每天产能损失 ${ctx.lostCapacity} 件。请提供最快的改善方案（一周内可实施）。`
  }
  return templates[q.key] || q.label
}

// ─── Build System Prompt ──────────────────────────────────────────────────────
const systemPrompt = computed(() => {
  const ctx = aiContext.value
  const baseRole = `你是一位资深工业工程（IE）专家，精通精益生产、工时分析和产线平衡优化。`

  if (!ctx) {
    return (
      baseRole +
      `\n\n当前暂无实时产线数据，请基于通用 IE 原理和行业最佳实践进行分析，并提醒用户提供具体数据。`
    )
  }

  return `${baseRole}

当前实时产线数据（请基于此数据进行分析）：
- 产线平衡率: ${ctx.balanceRate}% (目标: >90%)
- 瓶颈工位: ${ctx.bottleneckStation}
- 节拍时间: ${ctx.taktTime}s
- 日产能损失: ${ctx.lostCapacity} 件
- 利用率: ${ctx.utilization}%
- 标准工时达成率: ${ctx.stdtimeAchievement}%
- 非增值比: ${ctx.wasteRatio}%

请使用专业但清晰的语言，提供具体可执行的建议，尽可能给出量化数据。`
})

// ─── Send Chat Message (SSE Streaming) ────────────────────────────────────────
async function handleSendChat() {
  const text = inputText.value.trim()
  if (!text || isStreaming.value) return

  inputText.value = ''
  autoResize()
  await scrollToBottom()

  try {
    // Build context from aiContext data
    const context = aiContext.value || {}

    await sendChat(text, {
      ...context,
      systemPrompt: systemPrompt.value
    })
  } catch {
    // Error is handled in useSSEChat, just scroll
  } finally {
    await scrollToBottom()
  }
}

function sendPresetChat(text) {
  inputText.value = text
  nextTick(() => handleSendChat())
}

// ─── Async Task Submission ────────────────────────────────────────────────────
async function submitAsyncTask(analysisType, params = {}) {
  if (!aiContext.value) return

  try {
    const res = await submitAiTask(analysisType, params)
    const newTask = {
      taskId: res.task_id,
      analysisType,
      status: 'pending',
      progress: 0,
      result: null,
      error: '',
      createdAt: Date.now(),
      params,
      cancelling: false
    }
    asyncTasks.value = [newTask, ...asyncTasks.value]

    // Start polling for this specific task
    startTaskPolling(newTask.taskId)

    await scrollToBottom()
  } catch (err) {
    // Task submission failed - show error in chat
    console.error('Failed to submit async task:', err)
    addMessage({
      id: `task-error-${Date.now()}`,
      role: 'assistant',
      content: `任务提交失败: ${err.message || '未知错误'}，请稍后重试。`,
      isStreaming: false,
      isFallback: false,
      timestamp: Date.now()
    })
  }
}

function updateAsyncTask(taskId, updates) {
  const idx = asyncTasks.value.findIndex(t => t.taskId === taskId)
  if (idx !== -1) {
    asyncTasks.value = asyncTasks.value.map((t, i) =>
      i === idx ? { ...t, ...updates } : t
    )
  }
}

async function handleCancelTask(taskId) {
  // Backend does not support task cancellation yet
  updateAsyncTask(taskId, { status: 'cancelled', cancelling: false })
}

function handleViewResult({ taskId, result }) {
  // Push the result as a chat message for viewing
  const text = typeof result === 'string' ? result : result?.content || result?.summary || JSON.stringify(result, null, 2)
  if (text) {
    addMessage({
      id: `task-result-${taskId}`,
      role: 'assistant',
      content: text,
      isStreaming: false,
      isFallback: false,
      timestamp: Date.now()
    })
    scrollToBottom()
  }
}

function handleRetryTask({ analysisType, params }) {
  submitAsyncTask(analysisType, params)
}

const hasCompletedTasks = computed(() =>
  asyncTasks.value.some(t => t.status === 'completed' || t.status === 'failed')
)

function clearCompletedTasks() {
  asyncTasks.value = asyncTasks.value.filter(
    t => !['completed', 'failed', 'cancelled', 'revoked'].includes(t.status)
  )
}

// ─── Context & Status Loading ────────────────────────────────────────────────
async function checkAiStatus() {
  try {
    const status = await fetchAiStatus()
    aiConfigured.value = status.configured
  } catch {
    aiConfigured.value = false
  }
}

async function loadAiHealth() {
  try {
    aiHealthData.value = await fetchAiHealth()
  } catch {
    aiHealthData.value = null
  }
}

async function loadContext() {
  ctxLoading.value = true
  try {
    aiContext.value = await fetchAiContext()
  } catch {
    aiContext.value = null
  } finally {
    ctxLoading.value = false
  }
}

// ─── UI Helpers ──────────────────────────────────────────────────────────────
function clearAll() {
  abortChat()
  // 清除所有轮询定时器
  for (const [taskId, timer] of pollingTimers) {
    clearInterval(timer)
  }
  pollingTimers.clear()
  asyncTasks.value = []
}

function autoResize() {
  const el = textarea.value
  if (!el) return
  el.style.height = 'auto'
  el.style.height = Math.min(el.scrollHeight, 120) + 'px'
}

async function scrollToBottom() {
  await nextTick()
  if (chatContainer.value) {
    chatContainer.value.scrollTop = chatContainer.value.scrollHeight
  }
}

// ─── ESC key to abort streaming ──────────────────────────────────────────────
function onKeydown(e) {
  if (e.key === 'Escape' && isStreaming.value) {
    abortChat()
  }
}

// ─── Lifecycle ───────────────────────────────────────────────────────────────
let healthInterval = null

// P2 #85: 页面不可见时暂停健康检查轮询
function onVisibilityChange() {
  if (document.hidden) {
    if (healthInterval) {
      clearInterval(healthInterval)
      healthInterval = null
    }
  } else {
    if (!healthInterval) {
      loadAiHealth()
      healthInterval = setInterval(loadAiHealth, 300000)
    }
  }
}

onMounted(() => {
  document.addEventListener('keydown', onKeydown)
  document.addEventListener('visibilitychange', onVisibilityChange)
  loadContext()
  checkAiStatus()
  loadAiHealth()
  healthInterval = setInterval(loadAiHealth, 300000)
})

onUnmounted(() => {
  document.removeEventListener('keydown', onKeydown)
  document.removeEventListener('visibilitychange', onVisibilityChange)
  if (healthInterval) {
    clearInterval(healthInterval)
    healthInterval = null
  }
  // P2 #86: 清理所有任务轮询定时器
  for (const [taskId, timer] of pollingTimers) {
    clearInterval(timer)
  }
  pollingTimers.clear()
})
</script>

<style scoped>
.ai-page {
  display: flex;
  flex-direction: column;
  gap: 20px;
  height: calc(100vh - 140px);
}

.ai-layout {
  display: flex;
  gap: 16px;
  flex: 1;
  min-height: 0;
}

/* Model Badge */
.model-badge {
  display: flex;
  align-items: center;
  gap: 6px;
  padding: 4px 12px;
  background: linear-gradient(135deg, #0f172a, #1e293b);
  color: #a5f3fc;
  border-radius: 20px;
  font-size: var(--font-size-xs);
  font-weight: 600;
}
.model-dot {
  width: 7px;
  height: 7px;
  background: #22d3ee;
  border-radius: 50%;
  animation: pulse-blue 2s infinite;
}
@keyframes pulse-blue {
  0%, 100% { box-shadow: 0 0 0 2px rgba(34, 211, 238, 0.2); }
  50% { box-shadow: 0 0 0 5px rgba(34, 211, 238, 0.1); }
}

/* Context Panel */
.context-panel {
  width: 280px;
  flex-shrink: 0;
  display: flex;
  flex-direction: column;
  overflow-y: auto;
  padding: 0;
}
.context-header {
  padding: 16px 16px 12px;
  border-bottom: 1px solid var(--gray-100);
}
.context-title {
  font-size: var(--font-size-base);
  font-weight: 600;
  color: var(--gray-800);
}
.context-subtitle {
  font-size: var(--font-size-xs);
  color: var(--gray-400);
  margin-top: 2px;
}

.context-section {
  padding: 12px 16px;
  border-bottom: 1px solid var(--gray-100);
}
.ctx-section-label {
  font-size: 10px;
  font-weight: 700;
  text-transform: uppercase;
  letter-spacing: 0.08em;
  color: var(--gray-400);
  margin-bottom: 8px;
  display: flex;
  align-items: center;
  justify-content: space-between;
}
.ctx-refresh-btn {
  background: none;
  border: none;
  cursor: pointer;
  padding: 2px;
  color: var(--gray-400);
  display: flex;
  align-items: center;
  border-radius: 4px;
  transition: color 0.2s;
}
.ctx-refresh-btn:hover:not(:disabled) { color: var(--primary); }
.ctx-refresh-btn:disabled { opacity: 0.4; cursor: not-allowed; }
.no-data { color: var(--gray-400); font-size: var(--font-size-xs); padding: 4px 0; }
.ctx-item { display: flex; justify-content: space-between; align-items: center; padding: 3px 0; font-size: var(--font-size-xs); }
.ctx-key { color: var(--gray-500); }
.ctx-val { font-weight: 600; color: var(--gray-800); }
.val-success { color: var(--success); }
.val-warning { color: var(--warning); }
.val-danger { color: var(--danger); }

.preset-btns { display: flex; flex-direction: column; gap: 5px; }
.preset-btn {
  text-align: left;
  padding: 7px 10px;
  background: var(--gray-50);
  border: 1px solid var(--gray-200);
  border-radius: 6px;
  font-size: var(--font-size-xs);
  color: var(--gray-700);
  cursor: pointer;
  transition: var(--transition-fast);
  line-height: 1.4;
}
.preset-btn:hover { background: var(--primary-bg); border-color: var(--primary); color: var(--primary); }
.preset-btn:disabled { opacity: 0.4; cursor: not-allowed; }
.preset-btn-task {
  border-left: 3px solid var(--primary);
}

/* Chat Panel */
.chat-panel {
  flex: 1;
  min-width: 0;
  display: flex;
  flex-direction: column;
  padding: 0;
  overflow: hidden;
}

.chat-messages {
  flex: 1;
  overflow-y: auto;
  padding: 20px;
  display: flex;
  flex-direction: column;
  gap: 16px;
}

/* Welcome */
.chat-welcome {
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  flex: 1;
  text-align: center;
  gap: 10px;
  padding: 40px 20px;
}
.welcome-icon {
  width: 60px;
  height: 60px;
  background: linear-gradient(135deg, var(--primary-bg), #e0e7ff);
  border-radius: 16px;
  display: flex;
  align-items: center;
  justify-content: center;
  color: var(--primary);
}
.welcome-title { font-size: 18px; font-weight: 700; color: var(--gray-800); }
.welcome-desc { font-size: var(--font-size-sm); color: var(--gray-500); max-width: 360px; }
.welcome-tips { display: grid; grid-template-columns: 1fr 1fr; gap: 8px; margin-top: 8px; width: 100%; max-width: 480px; }
.welcome-tip {
  padding: 10px 12px;
  background: var(--gray-50);
  border: 1px solid var(--gray-200);
  border-radius: 8px;
  font-size: var(--font-size-xs);
  color: var(--gray-600);
  cursor: pointer;
  text-align: left;
  transition: var(--transition-fast);
}
.welcome-tip:hover { background: var(--primary-bg); border-color: var(--primary); color: var(--primary); }

/* Async Tasks Panel */
.async-tasks-panel {
  margin-top: 12px;
  padding-top: 12px;
  border-top: 1px solid var(--gray-200);
}
.async-tasks-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  margin-bottom: 8px;
  font-size: 12px;
  font-weight: 600;
  color: var(--gray-500);
  text-transform: uppercase;
  letter-spacing: 0.05em;
}
.btn-clear-tasks {
  background: none;
  border: none;
  color: var(--gray-400);
  font-size: 11px;
  cursor: pointer;
  padding: 2px 6px;
  border-radius: 4px;
  transition: color 0.15s;
}
.btn-clear-tasks:hover { color: var(--danger); }

/* Input Area */
.chat-input-area { padding: 14px 16px; border-top: 1px solid var(--gray-100); }
.chat-input-wrap { display: flex; gap: 8px; align-items: flex-end; }
.chat-textarea {
  flex: 1;
  padding: 10px 14px;
  border: 1px solid var(--gray-200);
  border-radius: 10px;
  font-size: var(--font-size-sm);
  line-height: 1.5;
  resize: none;
  outline: none;
  font-family: var(--font-family);
  color: var(--gray-800);
  transition: border-color 0.2s;
  min-height: 40px;
}
.chat-textarea:focus { border-color: var(--primary); }
.send-btn {
  width: 40px;
  height: 40px;
  border-radius: 10px;
  background: var(--primary);
  color: #fff;
  border: none;
  cursor: pointer;
  display: flex;
  align-items: center;
  justify-content: center;
  transition: var(--transition-fast);
  flex-shrink: 0;
}
.send-btn:hover:not(:disabled) { background: var(--primary-dark); }
.send-btn:disabled { background: var(--gray-200); color: var(--gray-400); cursor: not-allowed; }
.input-hint { font-size: 11px; color: var(--gray-400); margin-top: 5px; }
.stream-hint { color: var(--primary); }
.btn-inline {
  background: none;
  border: 1px solid var(--primary);
  border-radius: 3px;
  padding: 0 4px;
  font-size: 11px;
  color: var(--primary);
  cursor: pointer;
  font-family: inherit;
  margin: 0 2px;
}
.btn-inline:hover { background: var(--primary-bg); }

/* Status dot */
.status-dot { display: inline-block; width: 7px; height: 7px; border-radius: 50%; }
.status-ok { background: #22c55e; box-shadow: 0 0 0 2px rgba(34, 197, 94, 0.2); }
.status-off { background: #ef4444; box-shadow: 0 0 0 2px rgba(239, 68, 68, 0.2); }

.spin { animation: spin 1s linear infinite; }
@keyframes spin { from { transform: rotate(0deg); } to { transform: rotate(360deg); } }

@media (max-width: 900px) {
  .ai-layout { flex-direction: column; height: auto; }
  .context-panel { width: 100%; }
  .ai-page { height: auto; }
}
</style>
