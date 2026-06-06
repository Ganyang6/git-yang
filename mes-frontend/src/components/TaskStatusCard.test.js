/**
 * TaskStatusCard.vue component unit tests
 *
 * Covers:
 *   - renders task type and status text in Chinese
 *   - renders all statuses: pending, processing, completed, failed, cancelled, revoked
 *   - shows progress bar when processing with progress > 0
 *   - shows result preview when completed with result text
 *   - shows error message when failed
 *   - shows correct action button per status
 *   - emits cancel/view/retry events
 *   - handles missing optional props gracefully
 *   - trims result text beyond 120 chars
 *   - invalid createdAt returns empty string
 */

import { describe, it, expect, vi, beforeEach } from 'vitest'
import { mount, flushPromises } from '@vue/test-utils'
import TaskStatusCard from './TaskStatusCard.vue'

describe('TaskStatusCard', () => {
  const baseProps = { taskId: 'task-001' }

  it('renders with minimum required props (taskId only)', () => {
    const wrapper = mount(TaskStatusCard, { props: baseProps })
    // Default status is 'pending', default type is 'worktime'
    expect(wrapper.find('.task-card').exists()).toBe(true)
    expect(wrapper.text()).toContain('工时分析')
    expect(wrapper.text()).toContain('等待中')
  })

  it('displays correct Chinese text for analysis types', () => {
    const types = [
      { key: 'worktime', label: '工时分析' },
      { key: 'line_balance', label: '线平衡分析' },
      { key: 'anomaly', label: '异常检测' },
      { key: 'report', label: '报表生成' },
      { key: 'therblig_optimization', label: '动素优化' },
      { key: 'unknown_type', label: 'unknown_type' }
    ]

    for (const { key, label } of types) {
      const wrapper = mount(TaskStatusCard, {
        props: { ...baseProps, analysisType: key }
      })
      expect(wrapper.text()).toContain(label)
    }
  })

  it('displays correct Chinese text for each status', () => {
    const statuses = [
      { key: 'pending', label: '等待中' },
      { key: 'processing', label: '处理中' },
      { key: 'completed', label: '已完成' },
      { key: 'failed', label: '失败' },
      { key: 'cancelled', label: '已取消' },
      { key: 'revoked', label: '已撤销' }
    ]

    for (const { key, label } of statuses) {
      const wrapper = mount(TaskStatusCard, {
        props: { ...baseProps, status: key }
      })
      expect(wrapper.text()).toContain(label)
    }
  })

  it('applies status CSS class on the root element', () => {
    const statuses = ['pending', 'processing', 'completed', 'failed']
    for (const status of statuses) {
      const wrapper = mount(TaskStatusCard, {
        props: { ...baseProps, status }
      })
      expect(wrapper.classes()).toContain(status)
    }
  })

  it('shows progress bar when processing with progress > 0', () => {
    const wrapper = mount(TaskStatusCard, {
      props: { ...baseProps, status: 'processing', progress: 45 }
    })
    expect(wrapper.find('.progress-wrap').exists()).toBe(true)
    expect(wrapper.find('.progress-fill').exists()).toBe(true)
    expect(wrapper.text()).toContain('45%')
  })

  it('does not show progress bar when progress is 0', () => {
    const wrapper = mount(TaskStatusCard, {
      props: { ...baseProps, status: 'processing', progress: 0 }
    })
    expect(wrapper.find('.progress-wrap').exists()).toBe(false)
  })

  it('shows result text when completed with result string', () => {
    const wrapper = mount(TaskStatusCard, {
      props: { ...baseProps, status: 'completed', result: '分析完成，共发现12个异常' }
    })
    expect(wrapper.find('.task-result').exists()).toBe(true)
    expect(wrapper.text()).toContain('分析完成，共发现12个异常')
  })

  it('shows result.content text when result is an object with content', () => {
    const wrapper = mount(TaskStatusCard, {
      props: {
        ...baseProps,
        status: 'completed',
        result: { content: '详细分析报告内容', summary: '总览' }
      }
    })
    expect(wrapper.text()).toContain('详细分析报告内容')
  })

  it('shows result.summary when result object has no content', () => {
    const wrapper = mount(TaskStatusCard, {
      props: {
        ...baseProps,
        status: 'completed',
        result: { summary: '总览信息' }
      }
    })
    expect(wrapper.text()).toContain('总览信息')
  })

  it('shows default text when result is an empty object', () => {
    const wrapper = mount(TaskStatusCard, {
      props: { ...baseProps, status: 'completed', result: {} }
    })
    expect(wrapper.text()).toContain('分析已完成')
  })

  it('truncates result text beyond 120 characters', () => {
    const longText = 'A'.repeat(150)
    const wrapper = mount(TaskStatusCard, {
      props: { ...baseProps, status: 'completed', result: longText }
    })
    expect(wrapper.text()).toContain('...')
    expect(wrapper.find('.task-result').text().length).toBeLessThanOrEqual(124) // 120 + '...'
  })

  it('shows error message when status is failed', () => {
    const wrapper = mount(TaskStatusCard, {
      props: { ...baseProps, status: 'failed', error: '网络连接超时' }
    })
    expect(wrapper.find('.task-error').exists()).toBe(true)
    expect(wrapper.text()).toContain('网络连接超时')
  })

  it('shows error from result.error when no explicit error prop', () => {
    const wrapper = mount(TaskStatusCard, {
      props: {
        ...baseProps,
        status: 'failed',
        result: { error: '分析数据不足' }
      }
    })
    expect(wrapper.text()).toContain('分析数据不足')
  })

  it('shows cancel button for pending/processing status', () => {
    for (const status of ['pending', 'processing']) {
      const wrapper = mount(TaskStatusCard, {
        props: { ...baseProps, status }
      })
      const btn = wrapper.find('.btn-cancel')
      expect(btn.exists()).toBe(true)
      expect(btn.text()).toContain('取消')
    }
  })

  it('shows view button for completed status', () => {
    const wrapper = mount(TaskStatusCard, {
      props: { ...baseProps, status: 'completed' }
    })
    expect(wrapper.find('.btn-view').exists()).toBe(true)
    expect(wrapper.find('.btn-view').text()).toContain('查看')
  })

  it('shows retry button for failed status', () => {
    const wrapper = mount(TaskStatusCard, {
      props: { ...baseProps, status: 'failed' }
    })
    expect(wrapper.find('.btn-retry').exists()).toBe(true)
    expect(wrapper.find('.btn-retry').text()).toContain('重试')
  })

  it('disables cancel button when cancelling prop is true', () => {
    const wrapper = mount(TaskStatusCard, {
      props: { ...baseProps, status: 'processing', cancelling: true }
    })
    const btn = wrapper.find('.btn-cancel')
    expect(btn.attributes('disabled')).toBeDefined()
    expect(btn.text()).toContain('取消中...')
  })

  it('emits cancel event with taskId', async () => {
    const wrapper = mount(TaskStatusCard, {
      props: { ...baseProps, status: 'pending' }
    })
    await wrapper.find('.btn-cancel').trigger('click')
    expect(wrapper.emitted('cancel')).toBeTruthy()
    expect(wrapper.emitted('cancel')[0]).toEqual(['task-001'])
  })

  it('emits view event with task info', async () => {
    const result = { content: '结果内容' }
    const wrapper = mount(TaskStatusCard, {
      props: { ...baseProps, status: 'completed', result }
    })
    await wrapper.find('.btn-view').trigger('click')
    expect(wrapper.emitted('view')).toBeTruthy()
    expect(wrapper.emitted('view')[0][0]).toEqual({ taskId: 'task-001', result })
  })

  it('emits retry event with analysis type and params', async () => {
    const params = { startTime: '2024-01-01' }
    const wrapper = mount(TaskStatusCard, {
      props: { ...baseProps, status: 'failed', analysisType: 'worktime', params }
    })
    await wrapper.find('.btn-retry').trigger('click')
    expect(wrapper.emitted('retry')).toBeTruthy()
    expect(wrapper.emitted('retry')[0][0]).toEqual({ analysisType: 'worktime', params })
  })

  it('formats createdAt timestamp correctly', () => {
    const ts = new Date('2024-03-15T14:30:00').getTime()
    const wrapper = mount(TaskStatusCard, {
      props: { ...baseProps, createdAt: ts }
    })
    // Chinese locale format: MM/DD, HH:MM
    const timeText = wrapper.find('.task-time').text()
    expect(timeText).toContain('03/15')
    expect(timeText).toContain('14:30')
  })

  it('accepts createdAt as ISO string', () => {
    const wrapper = mount(TaskStatusCard, {
      props: { ...baseProps, createdAt: '2024-06-01T09:00:00Z' }
    })
    expect(wrapper.find('.task-time').text()).toBeTruthy()
  })

  it('handles invalid createdAt as empty string', () => {
    const wrapper = mount(TaskStatusCard, {
      props: { ...baseProps, createdAt: 'not-a-date' }
    })
    expect(wrapper.find('.task-time').text()).toBe('')
  })

  it('renders no actions for cancelled/revoked status', () => {
    for (const status of ['cancelled', 'revoked']) {
      const wrapper = mount(TaskStatusCard, {
        props: { ...baseProps, status }
      })
      expect(wrapper.find('.task-actions').exists()).toBe(true)
      expect(wrapper.findAll('button').length).toBe(0)
    }
  })
})
