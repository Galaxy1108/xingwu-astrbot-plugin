import { api } from './client'

/**
 * 开发模式专用：模拟扫码状态机（仅当 GET /api/version 返回 dev_mode=true 时展示入口）。
 * 生产构建不会主动调用这些接口。
 */
export type DevQrAction = 'scanned' | 'confirm' | 'expire'

export function devQrAction(action: DevQrAction, botId: string): Promise<{ ok?: boolean }> {
  return api.post<{ ok?: boolean }>(`/dev/qr/${encodeURIComponent(botId)}/${action}`)
}
