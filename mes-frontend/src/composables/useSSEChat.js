/**
 * SSE Streaming Chat Composable
 *
 * Provides reactive SSE streaming chat with the AI backend.
 * Uses fetch + ReadableStream (not EventSource) because we need POST.
 * Token is obtained automatically from the shared API layer.
 *
 * Usage:
 *   const { messages, isStreaming, sendChat, abort, error, addMessage } = useSSEChat({
 *     onFallback: (event) => showWarning(event),
 *   })
 */

import { ref, readonly, shallowRef, onUnmounted } from 'vue'
import { getAuthToken } from '../api/index.js'

export function useSSEChat(options = {}) {
  const {
    baseUrl: baseUrlOption,
    onMessage = null,
    onFallback = null,
    onError = null,
  } = options

  const messages = shallowRef([])
  const isStreaming = ref(false)
  const error = ref(null)
  let abortController = null

  /**
   * Resolve base URL, consistent with useSSE / useWebSocket pattern.
   */
  function resolveBaseUrl() {
    if (baseUrlOption) return baseUrlOption
    return import.meta.env.VITE_API_BASE || 'http://localhost:8000'
  }

  /**
   * Send a chat message and receive streaming response via SSE.
   *
   * @param {string} userMessage - The user's message text.
   * @param {object} context - Optional context data for the AI.
   */
  async function sendChat(userMessage, context = null) {
    const token = getAuthToken()
    if (!token) {
      error.value = 'Authentication required'
      if (onError) onError('Authentication required')
      return
    }

    isStreaming.value = true
    error.value = null

    // Add user message to the list
    const userMsg = {
      id: Date.now(),
      role: 'user',
      content: userMessage,
      timestamp: new Date().toISOString(),
    }
    messages.value = [...messages.value, userMsg]

    // Prepare assistant message placeholder
    const assistantMsg = {
      id: Date.now() + 1,
      role: 'assistant',
      content: '',
      source: '',
      timestamp: new Date().toISOString(),
    }
    messages.value = [...messages.value, assistantMsg]

    abortController = new AbortController()

    try {
      const base = resolveBaseUrl()
      const response = await fetch(`${base}/api/ai/chat/stream`, {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
          Authorization: `Bearer ${token}`,
        },
        body: JSON.stringify({
          message: userMessage,
          context: context,
        }),
        signal: abortController.signal,
      })

      if (!response.ok) {
        if (response.status === 401) {
          localStorage.removeItem('mes_auth_token')
          throw new Error('认证已过期')
        }
        throw new Error(`HTTP ${response.status}: ${response.statusText}`)
      }

      const reader = response.body.getReader()
      const decoder = new TextDecoder()
      let buffer = ''

      while (true) {
        const { done, value } = await reader.read()
        if (done) break

        buffer += decoder.decode(value, { stream: true })

        // Parse SSE lines
        const lines = buffer.split('\n')
        buffer = lines.pop() || '' // keep incomplete line in buffer

        for (const line of lines) {
          if (!line.startsWith('data: ')) continue

          const dataStr = line.slice(6).trim()
          if (!dataStr) continue

          try {
            const data = JSON.parse(dataStr)

            if (data.done) {
              // Stream completed
              continue
            }

            if (data.type === 'fallback') {
              // AI degradation notification - pass full event object to callback
              if (onFallback) onFallback(data)
              if (!assistantMsg.source) {
                assistantMsg.source = 'fallback'
              }
              continue
            }

            if (data.type === 'error') {
              error.value = data.message
              if (onError) onError(data.message)
              continue
            }

            if (data.content) {
              // Incremental content chunk
              assistantMsg.content += data.content
              if (!assistantMsg.source && data.level) {
                assistantMsg.source = data.level
              }
              // Update messages reactively (shallow copy to trigger reactivity)
              messages.value = [...messages.value]
              if (onMessage) onMessage(data.content, assistantMsg.content)
            }
          } catch (e) {
            // Skip malformed JSON lines, but log for debugging
            console.debug('[sse-chat] skipped malformed SSE chunk:', e.message)
          }
        }
      }
    } catch (err) {
      if (err.name === 'AbortError') {
        // User aborted the stream
        assistantMsg.content += '\n[Stream interrupted by user]'
      } else {
        error.value = err.message
        if (onError) onError(err.message)
      }
    } finally {
      isStreaming.value = false
      abortController = null
      messages.value = [...messages.value]
    }
  }

  /**
   * Programmatically add a message (e.g., from async task result).
   * This bypasses readonly because it writes to the internal shallowRef.
   *
   * @param {{ role: string, content: string, isFallback?: boolean, source?: string }} msg
   */
  function addMessage(msg) {
    messages.value = [
      ...messages.value,
      {
        id: Date.now(),
        timestamp: new Date().toISOString(),
        isFallback: false,
        source: '',
        ...msg,
      },
    ]
  }

  /**
   * Abort the current streaming response.
   */
  function abort() {
    if (abortController) {
      abortController.abort()
      abortController = null
    }
  }

  /**
   * Clear all messages.
   */
  function clearMessages() {
    messages.value = []
    error.value = null
  }

  onUnmounted(() => {
    abort()
  })

  return {
    messages: readonly(messages),
    isStreaming: readonly(isStreaming),
    error: readonly(error),
    sendChat,
    addMessage,
    abort,
    clearMessages,
  }
}
