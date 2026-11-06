import { defineStore } from 'pinia'
import { reactive } from 'vue'
import {
  deleteMemory as deleteMemoryApi,
  exportMemories,
  listMemories,
  patchMemory,
  searchMemories,
} from '@/api/memory'
import { toApiError, type ApiError } from '@/api/client'
import type {
  MemoryItem,
  MemoryListQuery,
  MemoryPatch,
  MemoryExportResult,
  MemorySearchPayload,
  PageResult,
} from '@/types'

/** 按 botId 分桶缓存：切换 Bot 不清空其它 Bot 的列表与筛选。 */
export interface MemoryBucket {
  items: MemoryItem[]
  total: number
  page: number
  pageSize: number
  loading: boolean
  loaded: boolean
  error: ApiError | null
}

function emptyBucket(): MemoryBucket {
  return {
    items: [],
    total: 0,
    page: 1,
    pageSize: 20,
    loading: false,
    loaded: false,
    error: null,
  }
}

export const useMemoryStore = defineStore('memory', () => {
  const buckets = reactive<Record<string, MemoryBucket>>({})

  function bucket(botId: string): MemoryBucket {
    if (!buckets[botId]) buckets[botId] = emptyBucket()
    return buckets[botId]
  }

  async function fetchList(
    botId: string,
    query: MemoryListQuery = {},
  ): Promise<PageResult<MemoryItem>> {
    const target = bucket(botId)
    target.loading = true
    target.error = null
    try {
      const result = await listMemories(botId, query)
      target.items = result.items ?? []
      target.total = result.total ?? 0
      target.page = result.page ?? query.page ?? 1
      target.pageSize = result.page_size ?? query.page_size ?? 20
      target.loaded = true
      return result
    } catch (error) {
      target.error = toApiError(error)
      throw target.error
    } finally {
      target.loading = false
    }
  }

  function replaceItem(botId: string, item: MemoryItem): void {
    const target = bucket(botId)
    const index = target.items.findIndex((memory) => memory.id === item.id)
    if (index >= 0) target.items.splice(index, 1, item)
  }

  async function updateMemory(
    botId: string,
    memoryId: number,
    patch: MemoryPatch,
  ): Promise<MemoryItem> {
    const result = await patchMemory(botId, memoryId, patch)
    replaceItem(botId, result.memory)
    return result.memory
  }

  async function deleteMemory(botId: string, memoryId: number): Promise<void> {
    await deleteMemoryApi(botId, memoryId)
    const target = bucket(botId)
    const before = target.items.length
    target.items = target.items.filter((memory) => memory.id !== memoryId)
    if (target.items.length < before) {
      target.total = Math.max(0, target.total - 1)
    }
  }

  async function search(
    botId: string,
    payload: MemorySearchPayload,
  ): Promise<PageResult<MemoryItem>> {
    return searchMemories(botId, payload)
  }

  async function exportAll(botId: string): Promise<MemoryExportResult> {
    return exportMemories(botId)
  }

  function reset(botId: string): void {
    delete buckets[botId]
  }

  return { buckets, bucket, fetchList, updateMemory, deleteMemory, search, exportAll, reset }
})
