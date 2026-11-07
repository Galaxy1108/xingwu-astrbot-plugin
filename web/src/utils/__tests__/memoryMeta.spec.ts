import { describe, expect, it } from 'vitest'
import { importanceText, isAutoExtracted, memoryImportanceOptions } from '../memoryMeta'
import type { MemoryItem } from '@/types'

function memory(overrides: Partial<MemoryItem> = {}): MemoryItem {
  return {
    id: 1,
    kind: 'fact',
    kind_label: '事实',
    content: 'test',
    reasoning: '',
    importance: 3,
    pinned: false,
    tags: [],
    metadata: {},
    created_at: 0,
    updated_at: 0,
    last_recalled_at: 0,
    recall_count: 0,
    ...overrides,
  }
}

describe('记忆重要度 / 自动提取', () => {
  it('重要度 6 显示为总是注入，并出现在选项里', () => {
    expect(importanceText(6)).toBe('总是注入')
    expect(importanceText(5)).toBe('★ 5/6')
    expect(memoryImportanceOptions.some((item) => item.value === 6)).toBe(true)
  })

  it('兼容 metadata 自动提取标记', () => {
    expect(isAutoExtracted(memory({ metadata: { auto_extracted: true } }))).toBe(true)
    expect(isAutoExtracted(memory({ metadata: { source: 'auto' } }))).toBe(true)
    expect(isAutoExtracted(memory({ tags: ['自动提取'] }))).toBe(true)
    expect(isAutoExtracted(memory())).toBe(false)
  })
})
