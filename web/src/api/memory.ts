import { api } from './client'
import type {
  MemoryExportResult,
  MemoryItem,
  MemoryListQuery,
  MemoryPatch,
  MemorySearchPayload,
  PageResult,
} from '@/types'

export function listMemories(
  botId: string,
  query: MemoryListQuery = {},
): Promise<PageResult<MemoryItem>> {
  return api.get<PageResult<MemoryItem>>(`/bots/${encodeURIComponent(botId)}/memories`, {
    page: query.page,
    page_size: query.page_size,
    kind: query.kind,
    tag: query.tag,
    q: query.q,
  })
}

export function getMemory(botId: string, memoryId: number): Promise<{ memory: MemoryItem }> {
  return api.get<{ memory: MemoryItem }>(
    `/bots/${encodeURIComponent(botId)}/memories/${memoryId}`,
  )
}

export function patchMemory(
  botId: string,
  memoryId: number,
  payload: MemoryPatch,
): Promise<{ memory: MemoryItem }> {
  return api.patch<{ memory: MemoryItem }>(
    `/bots/${encodeURIComponent(botId)}/memories/${memoryId}`,
    payload,
  )
}

export function deleteMemory(botId: string, memoryId: number): Promise<{ deleted: boolean }> {
  return api.delete<{ deleted: boolean }>(
    `/bots/${encodeURIComponent(botId)}/memories/${memoryId}`,
  )
}

export function searchMemories(
  botId: string,
  payload: MemorySearchPayload,
): Promise<PageResult<MemoryItem>> {
  return api.post<PageResult<MemoryItem>>(
    `/bots/${encodeURIComponent(botId)}/memories/search`,
    payload,
  )
}

export function exportMemories(botId: string): Promise<MemoryExportResult> {
  return api.post<MemoryExportResult>(
    `/bots/${encodeURIComponent(botId)}/memories/export`,
  )
}
