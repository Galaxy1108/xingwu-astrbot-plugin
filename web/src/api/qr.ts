import { api } from './client'
import type { Bot, Platform, QrConnectSession } from '@/types'

export function createQrSession(payload: {
  platform: Platform
  name: string
  template_id: string
}): Promise<{ session: QrConnectSession }> {
  return api.post<{ session: QrConnectSession }>('/qr/sessions', payload)
}

export function pollQrSession(id: string): Promise<{ session: QrConnectSession }> {
  return api.get<{ session: QrConnectSession }>(
    `/qr/sessions/${encodeURIComponent(id)}/poll`,
  )
}

export function finalizeQrSession(id: string): Promise<{ bot: Bot }> {
  return api.post<{ bot: Bot }>(
    `/qr/sessions/${encodeURIComponent(id)}/finalize`,
  )
}

export function cancelQrSession(id: string): Promise<{ cancelled?: boolean }> {
  return api.delete<{ cancelled?: boolean }>(
    `/qr/sessions/${encodeURIComponent(id)}`,
  )
}
