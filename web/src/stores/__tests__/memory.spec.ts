import { createPinia, setActivePinia } from 'pinia'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import type { MemoryItem, PageResult } from '@/types'

vi.mock('@/api/memory', () => ({
  listMemories: vi.fn(),
  getMemory: vi.fn(),
  patchMemory: vi.fn(),
  deleteMemory: vi.fn(),
  searchMemories: vi.fn(),
  exportMemories: vi.fn(),
}))

import * as memoryApi from '@/api/memory'
import { useMemoryStore } from '../memory'

function memoryItem(overrides: Partial<MemoryItem> = {}): MemoryItem {
  return {
    id: 1,
    kind: 'fact',
    kind_label: '事实',
    content: '用户喜欢喝咖啡',
    reasoning: '',
    importance: 3,
    pinned: false,
    tags: ['饮品'],
    metadata: {},
    created_at: 1000,
    updated_at: 1000,
    last_recalled_at: 0,
    recall_count: 0,
    ...overrides,
  }
}

function page(
  items: MemoryItem[],
  total = items.length,
  pageNo = 1,
  size = 20,
): PageResult<MemoryItem> {
  return { items, total, page: pageNo, page_size: size }
}

beforeEach(() => {
  setActivePinia(createPinia())
  vi.clearAllMocks()
})

describe('memory store · 列表与筛选参数透传', () => {
  it('把 page/page_size/kind/tag/q 原样传给 API，并按 botId 分桶缓存', async () => {
    vi.mocked(memoryApi.listMemories)
      .mockResolvedValueOnce(page([memoryItem({ id: 1 })], 6, 2))
      .mockResolvedValueOnce(page([memoryItem({ id: 2, content: '杭州出差' })], 1))

    const store = useMemoryStore()
    await store.fetchList('b_1', {
      page: 2,
      page_size: 20,
      kind: 'preference',
      tag: '杭州',
      q: '咖啡',
    })

    expect(memoryApi.listMemories).toHaveBeenNthCalledWith(1, 'b_1', {
      page: 2,
      page_size: 20,
      kind: 'preference',
      tag: '杭州',
      q: '咖啡',
    })
    expect(store.bucket('b_1').items[0].id).toBe(1)
    expect(store.bucket('b_1').total).toBe(6)
    expect(store.bucket('b_1').page).toBe(2)

    await store.fetchList('b_2', {})
    expect(store.bucket('b_2').items[0].id).toBe(2)
    // 切换 Bot 不清空其它 Bot 的桶
    expect(store.bucket('b_1').items[0].id).toBe(1)
    expect(store.bucket('b_1').page).toBe(2)
  })

  it('列表失败时写入 bucket.error，供页面展示重试', async () => {
    vi.mocked(memoryApi.listMemories).mockRejectedValueOnce(new Error('boom'))

    const store = useMemoryStore()
    await expect(store.fetchList('b_1', { page: 1 })).rejects.toMatchObject({
      code: 'network_error',
      message: 'boom',
    })
    expect(store.bucket('b_1').error?.message).toBe('boom')
    expect(store.bucket('b_1').loading).toBe(false)
  })

  it('search 透传关键词/类型/limit', async () => {
    vi.mocked(memoryApi.searchMemories).mockResolvedValueOnce(
      page([memoryItem({ id: 3, content: '喜欢杭州' })], 1),
    )

    const store = useMemoryStore()
    const result = await store.search('b_1', { q: '杭州', kind: 'preference', limit: 10 })

    expect(memoryApi.searchMemories).toHaveBeenCalledWith('b_1', {
      q: '杭州',
      kind: 'preference',
      limit: 10,
    })
    expect(result.items).toHaveLength(1)
  })
})

describe('memory store · 编辑与删除', () => {
  it('updateMemory 只提交传入字段，并用服务端返回替换桶内条目', async () => {
    vi.mocked(memoryApi.listMemories).mockResolvedValueOnce(page([memoryItem({ id: 5 })]))
    vi.mocked(memoryApi.patchMemory).mockResolvedValueOnce({
      memory: memoryItem({ id: 5, content: '新内容', pinned: true, importance: 5 }),
    })

    const store = useMemoryStore()
    await store.fetchList('b_1', {})
    await store.updateMemory('b_1', 5, {
      content: '新内容',
      pinned: true,
      importance: 5,
      tags: ['杭州'],
      metadata: { source: 'manual' },
    })

    expect(memoryApi.patchMemory).toHaveBeenCalledWith('b_1', 5, {
      content: '新内容',
      pinned: true,
      importance: 5,
      tags: ['杭州'],
      metadata: { source: 'manual' },
    })
    expect(store.bucket('b_1').items[0].content).toBe('新内容')
    expect(store.bucket('b_1').items[0].pinned).toBe(true)
  })

  it('deleteMemory 成功后移除条目并修正 total', async () => {
    vi.mocked(memoryApi.listMemories).mockResolvedValueOnce(
      page([memoryItem({ id: 1 }), memoryItem({ id: 2 })], 2),
    )
    vi.mocked(memoryApi.deleteMemory).mockResolvedValueOnce({ deleted: true })

    const store = useMemoryStore()
    await store.fetchList('b_1', {})
    await store.deleteMemory('b_1', 1)

    expect(memoryApi.deleteMemory).toHaveBeenCalledWith('b_1', 1)
    expect(store.bucket('b_1').items.map((item) => item.id)).toEqual([2])
    expect(store.bucket('b_1').total).toBe(1)
  })

  it('删除失败时不从列表移除条目（确认后仍需服务端成功）', async () => {
    vi.mocked(memoryApi.listMemories).mockResolvedValueOnce(page([memoryItem({ id: 1 })]))
    vi.mocked(memoryApi.deleteMemory).mockRejectedValueOnce(new Error('forbidden'))

    const store = useMemoryStore()
    await store.fetchList('b_1', {})
    await expect(store.deleteMemory('b_1', 1)).rejects.toThrow('forbidden')

    expect(store.bucket('b_1').items).toHaveLength(1)
    expect(store.bucket('b_1').total).toBe(1)
  })
})
