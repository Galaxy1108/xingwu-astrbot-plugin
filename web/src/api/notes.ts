import { api } from './client'
import type { NoteDetail, NoteReadPage, NoteSummary, PageResult } from '@/types'

export interface NoteListQuery {
  page?: number
  page_size?: number
  q?: string
  tag?: string
}

export function listNotes(
  botId: string,
  query: NoteListQuery = {},
): Promise<PageResult<NoteSummary>> {
  return api.get<PageResult<NoteSummary>>(`/bots/${encodeURIComponent(botId)}/notes`, {
    page: query.page,
    page_size: query.page_size,
    q: query.q,
    tag: query.tag,
  })
}

export function createNote(
  botId: string,
  payload: { title: string; content: string; tags?: string[] },
): Promise<{ note: NoteDetail }> {
  return api.post<{ note: NoteDetail }>(`/bots/${encodeURIComponent(botId)}/notes`, payload)
}

export function getNote(botId: string, shortId: string): Promise<{ note: NoteDetail }> {
  return api.get<{ note: NoteDetail }>(
    `/bots/${encodeURIComponent(botId)}/notes/${encodeURIComponent(shortId)}`,
  )
}

export function readNote(
  botId: string,
  shortId: string,
  offset = 0,
  limit = 4000,
): Promise<NoteReadPage> {
  return api.get<NoteReadPage>(
    `/bots/${encodeURIComponent(botId)}/notes/${encodeURIComponent(shortId)}/read`,
    { offset, limit },
  )
}

export function deleteNote(botId: string, shortId: string): Promise<{ deleted: boolean }> {
  return api.delete<{ deleted: boolean }>(
    `/bots/${encodeURIComponent(botId)}/notes/${encodeURIComponent(shortId)}`,
  )
}
