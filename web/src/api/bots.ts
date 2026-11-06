import { api } from './client'
import type { Bot, BotCreatePayload, BotPatchPayload, QrPollResult, QrSession } from '@/types'

export function listBots(): Promise<{ items: Bot[] }> {
  return api.get<{ items: Bot[] }>('/bots')
}

export function createBot(payload: BotCreatePayload): Promise<{ bot: Bot }> {
  return api.post<{ bot: Bot }>('/bots', payload)
}

export function getBot(id: string): Promise<{ bot: Bot }> {
  return api.get<{ bot: Bot }>(`/bots/${encodeURIComponent(id)}`)
}

export function patchBot(id: string, payload: BotPatchPayload): Promise<{ bot: Bot }> {
  return api.patch<{ bot: Bot }>(`/bots/${encodeURIComponent(id)}`, payload)
}

export function deleteBot(id: string, confirmName: string): Promise<{ deleted: boolean }> {
  return api.delete<{ deleted: boolean }>(`/bots/${encodeURIComponent(id)}`, { confirm_name: confirmName })
}

export function startQr(id: string): Promise<{ qr: QrSession }> {
  return api.post<{ qr: QrSession }>(`/bots/${encodeURIComponent(id)}/qr/start`)
}

export function pollQr(id: string): Promise<QrPollResult> {
  return api.get<QrPollResult>(`/bots/${encodeURIComponent(id)}/qr/poll`)
}

export function finalizeQr(id: string): Promise<{ bot: Bot }> {
  return api.post<{ bot: Bot }>(`/bots/${encodeURIComponent(id)}/qr/finalize`)
}
