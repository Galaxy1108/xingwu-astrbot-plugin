import { api } from './client'
import type { Appeal, AppealTarget } from '@/types'

export interface AppealCreatePayload {
  target_type: AppealTarget
  target_id?: string
  reason: string
}

export function submitAppeal(payload: AppealCreatePayload): Promise<{ appeal: Appeal }> {
  return api.post<{ appeal: Appeal }>('/appeals', payload)
}

export function listMyAppeals(): Promise<{ items: Appeal[] }> {
  return api.get<{ items: Appeal[] }>('/me/appeals')
}

export function listAdminAppeals(status?: string): Promise<{ items: Appeal[] }> {
  return api.get<{ items: Appeal[] }>('/admin/appeals', { status })
}

export function approveAppeal(id: string | number, note = ''): Promise<{ appeal: Appeal }> {
  return api.post<{ appeal: Appeal }>(`/admin/appeals/${encodeURIComponent(String(id))}/approve`, { note })
}

export function rejectAppeal(id: string | number, note = ''): Promise<{ appeal: Appeal }> {
  return api.post<{ appeal: Appeal }>(`/admin/appeals/${encodeURIComponent(String(id))}/reject`, { note })
}
