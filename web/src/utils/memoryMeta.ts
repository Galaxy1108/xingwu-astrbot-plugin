import type { MemoryItem } from '@/types'

/** 重要度 6 是「总是注入」，其余 1–5 为普通排序权重。 */
export const memoryImportanceOptions = [
  { title: '1 · 很低', value: 1 },
  { title: '2 · 较低', value: 2 },
  { title: '3 · 一般', value: 3 },
  { title: '4 · 较高', value: 4 },
  { title: '5 · 很高', value: 5 },
  { title: '6 · 总是注入（每条对话都注入）', value: 6 },
]

export function importanceText(value: number): string {
  return value >= 6 ? '总是注入' : `★ ${value}/6`
}

export function importanceColor(value: number): string {
  if (value >= 6) return 'error'
  if (value >= 5) return 'warning'
  if (value >= 4) return 'primary'
  return 'default'
}

/** 兼容后端不同的自动提取标记；无标记时返回 false。 */
export function isAutoExtracted(memory: Pick<MemoryItem, 'metadata' | 'tags'>): boolean {
  const meta = memory.metadata ?? {}
  if (meta.auto_extracted === true || meta.auto === true || meta.source === 'auto') return true
  return Array.isArray(memory.tags) && memory.tags.includes('自动提取')
}
