/**
 * P2 #90: Shared string-to-color utility
 * Generates a consistent color from a string (e.g. customer name).
 * Used across Customers.vue (and previously duplicated in Orders.vue).
 */

const COLORS = [
  '#1a6ef5', '#10b981', '#f59e0b', '#ef4444', '#8b5cf6',
  '#06b6d4', '#ec4899', '#84cc16', '#6366f1', '#14b8a6'
]

/**
 * @param {string} str - input string
 * @returns {string} hex color
 */
export function strColor(str) {
  let hash = 0
  for (let i = 0; i < str.length; i++) {
    hash = str.charCodeAt(i) + ((hash << 5) - hash)
  }
  return COLORS[Math.abs(hash) % COLORS.length]
}
