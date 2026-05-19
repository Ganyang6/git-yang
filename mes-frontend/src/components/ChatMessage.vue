<template>
  <div class="msg-row" :class="role">
    <div class="msg-avatar" :class="role === 'assistant' ? 'avatar-ai' : 'avatar-user'">
      <template v-if="role === 'assistant'">AI</template>
      <template v-else>ME</template>
    </div>
    <div class="msg-bubble" :class="role === 'assistant' ? 'bubble-ai' : 'bubble-user'">
      <div v-if="isStreaming" class="typing-indicator">
        <span></span><span></span><span></span>
      </div>
      <div
        v-else
        class="msg-content markdown-body"
        v-html="renderedContent"
      ></div>
      <FallbackBadge
        v-if="isFallback && !isStreaming"
        :severity="fallbackSeverity"
        class="fallback-inline"
      />
      <div class="msg-time">{{ formattedTime }}</div>
    </div>
  </div>
</template>

<script setup>
import { computed } from 'vue'
import { Marked } from 'marked'
import DOMPurify from 'dompurify'
import FallbackBadge from './FallbackBadge.vue'

// Module-level singleton - shared across all ChatMessage instances
const markedInstance = new Marked({ breaks: true, gfm: true })

const props = defineProps({
  /** Message role */
  role: {
    type: String,
    required: true,
    validator: v => ['user', 'assistant'].includes(v)
  },
  /** Message content (plain text or markdown) */
  content: {
    type: String,
    default: ''
  },
  /** Whether this message is currently being streamed */
  isStreaming: {
    type: Boolean,
    default: false
  },
  /** Whether AI response came from fallback (cache/rule engine) */
  isFallback: {
    type: Boolean,
    default: false
  },
  /** Fallback severity */
  fallbackSeverity: {
    type: String,
    default: 'cache'
  },
  /** Timestamp (epoch ms or formatted string) */
  timestamp: {
    type: [Number, String],
    default: null
  }
})

// Module-level singleton defined above

const renderedContent = computed(() => {
  if (!props.content) return ''
  // P1: user messages should render as plain text, not Markdown
  if (props.role === 'user') return DOMPurify.sanitize(props.content)
  let rawHtml = ''
  try {
    rawHtml = markedInstance.parse(props.content, { async: false })
  } catch (e) {
    console.error('[ChatMessage] Markdown parse error:', e)
    rawHtml = DOMPurify.sanitize(props.content) // fallback to plain text
  }
  return DOMPurify.sanitize(rawHtml, {
    ALLOWED_TAGS: [
      'p', 'br', 'strong', 'em', 'b', 'i', 'u', 's',
      'code', 'pre', 'h1', 'h2', 'h3', 'h4', 'h5', 'h6',
      'ul', 'ol', 'li', 'a', 'blockquote', 'table', 'thead', 'tbody', 'tr', 'th', 'td', 'hr', 'span', 'div'
    ],
    ALLOWED_ATTR: ['href', 'target', 'class'],
    ALLOW_DATA_ATTR: false,
    // Auto-add rel="noopener noreferrer" to target="_blank" links to prevent window.opener attacks
    ALLOWED_URI_REGEXP: /^(?:(?:(?:f|ht)tps?|mailto|tel):|[^a-z]|[a-z+.-]+(?:[^a-z+.\-:]|$))/i
  }).replace(/<a([^>]*?)\s+target="_blank"/gi, '<a$1 target="_blank" rel="noopener noreferrer"')
})

const formattedTime = computed(() => {
  if (!props.timestamp) return ''
  const ts = typeof props.timestamp === 'number' ? props.timestamp : new Date(props.timestamp).getTime()
  return new Date(ts).toLocaleTimeString('zh-CN', { hour: '2-digit', minute: '2-digit' })
})
</script>

<style scoped>
.msg-row {
  display: flex;
  gap: 10px;
  align-items: flex-start;
}
.msg-row.user {
  flex-direction: row-reverse;
}

.msg-avatar {
  width: 32px;
  height: 32px;
  border-radius: 8px;
  display: flex;
  align-items: center;
  justify-content: center;
  font-size: 11px;
  font-weight: 700;
  flex-shrink: 0;
}
.avatar-ai {
  background: linear-gradient(135deg, #0f172a, #1e3a5f);
  color: #a5f3fc;
}
.avatar-user {
  background: var(--primary, #4f46e5);
  color: #fff;
}

.msg-bubble {
  max-width: 72%;
  padding: 12px 14px;
  border-radius: 12px;
}
.bubble-ai {
  background: #fff;
  border: 1px solid var(--gray-200, #e5e7eb);
  color: var(--gray-800, #1f2937);
  border-top-left-radius: 4px;
}
.bubble-user {
  background: var(--primary, #4f46e5);
  color: #fff;
  border-top-right-radius: 4px;
}

.msg-content {
  font-size: var(--font-size-sm, 13px);
  line-height: 1.65;
  word-break: break-word;
}

.msg-time {
  font-size: 10px;
  color: var(--gray-400, #9ca3af);
  margin-top: 4px;
  text-align: right;
}
.bubble-user .msg-time {
  color: rgba(255, 255, 255, 0.6);
}

.fallback-inline {
  margin-top: 6px;
}

/* Typing indicator */
.typing-indicator {
  display: flex;
  gap: 4px;
  align-items: center;
  padding: 4px 0;
}
.typing-indicator span {
  width: 7px;
  height: 7px;
  background: var(--gray-400, #9ca3af);
  border-radius: 50%;
  animation: msg-bounce 1.2s infinite ease-in-out;
}
.typing-indicator span:nth-child(2) {
  animation-delay: 0.2s;
}
.typing-indicator span:nth-child(3) {
  animation-delay: 0.4s;
}
@keyframes msg-bounce {
  0%, 80%, 100% {
    transform: scale(0.7);
    opacity: 0.5;
  }
  40% {
    transform: scale(1);
    opacity: 1;
  }
}

/* Markdown content styles */
:deep(.markdown-body p) { margin: 4px 0; }
:deep(.markdown-body h1),
:deep(.markdown-body h2),
:deep(.markdown-body h3) {
  font-size: 14px;
  font-weight: 700;
  color: var(--gray-800, #1f2937);
  margin: 8px 0 4px;
}
:deep(.markdown-body ul),
:deep(.markdown-body ol) { padding-left: 18px; margin: 4px 0; }
:deep(.markdown-body li) { margin: 2px 0; }
:deep(.markdown-body code) {
  background: var(--gray-100, #f3f4f6);
  border-radius: 3px;
  padding: 1px 5px;
  font-family: monospace;
  font-size: 12px;
  color: var(--danger, #ef4444);
}
:deep(.markdown-body pre) {
  background: var(--gray-100, #f3f4f6);
  border-radius: 6px;
  padding: 10px;
  margin: 6px 0;
  overflow-x: auto;
}
:deep(.markdown-body pre code) {
  background: none;
  padding: 0;
  color: var(--gray-800, #1f2937);
}
:deep(.markdown-body a) {
  color: var(--primary, #4f46e5);
  text-decoration: none;
}
:deep(.markdown-body a:hover) { text-decoration: underline; }
:deep(.markdown-body table) {
  border-collapse: collapse;
  margin: 6px 0;
  font-size: var(--font-size-xs, 12px);
}
:deep(.markdown-body th),
:deep(.markdown-body td) {
  border: 1px solid var(--gray-200, #e5e7eb);
  padding: 4px 8px;
}
:deep(.markdown-body th) {
  background: var(--gray-50, #f9fafb);
  font-weight: 600;
}
</style>
