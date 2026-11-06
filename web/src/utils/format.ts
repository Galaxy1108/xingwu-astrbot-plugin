import dayjs from 'dayjs'
import relativeTime from 'dayjs/plugin/relativeTime'
import 'dayjs/locale/zh-cn'
import type { BotStatus, EncryptionState, Platform, QrStatus } from '@/types'

dayjs.extend(relativeTime)
dayjs.locale('zh-cn')

export function formatDateTime(timestamp?: number | null): string {
  if (!timestamp) return '—'
  return dayjs(timestamp * 1000).format('YYYY-MM-DD HH:mm')
}

export function formatDate(timestamp?: number | null): string {
  if (!timestamp) return '—'
  return dayjs(timestamp * 1000).format('YYYY-MM-DD')
}

export function formatRelative(timestamp?: number | null): string {
  if (!timestamp) return '—'
  return dayjs(timestamp * 1000).fromNow()
}

export function formatNumber(value?: number | null): string {
  if (value === null || value === undefined || Number.isNaN(value)) return '—'
  return new Intl.NumberFormat('zh-CN').format(value)
}

export function formatSeconds(seconds: number): string {
  const safe = Math.max(0, Math.floor(seconds))
  const mm = String(Math.floor(safe / 60)).padStart(2, '0')
  const ss = String(safe % 60).padStart(2, '0')
  return `${mm}:${ss}`
}

export const platformLabels: Record<Platform, string> = {
  weixin_oc: '微信（个人号 · 官方接口）',
  qq_official: 'QQ 官方机器人',
}

export function platformLabel(platform: string): string {
  if (platform === 'weixin_oc' || platform === 'qq_official') return platformLabels[platform]
  return platform || '未知平台'
}

export function platformShortLabel(platform: string): string {
  if (platform === 'weixin_oc') return '微信'
  if (platform === 'qq_official') return 'QQ'
  return platform || '未知'
}

export interface StatusMeta {
  label: string
  color: string
  icon: string
}

export const botStatusMeta: Record<BotStatus, StatusMeta> = {
  creating: { label: '创建中', color: 'info', icon: 'mdi-progress-clock' },
  pending_qr: { label: '待扫码', color: 'warning', icon: 'mdi-qrcode' },
  ready: { label: '运行中', color: 'success', icon: 'mdi-check-circle' },
  disabled: { label: '已停用', color: 'default', icon: 'mdi-pause-circle' },
  deleting: { label: '删除中', color: 'warning', icon: 'mdi-delete-clock' },
  deleted: { label: '已删除', color: 'default', icon: 'mdi-delete' },
}

export const qrStatusMeta: Record<QrStatus, StatusMeta> = {
  pending: { label: '等待扫码', color: 'info', icon: 'mdi-qrcode' },
  scanned: { label: '已扫码，请在手机上确认', color: 'warning', icon: 'mdi-cellphone-check' },
  created: { label: '已确认，正在完成接入', color: 'success', icon: 'mdi-check-circle' },
  expired: { label: '二维码已过期', color: 'error', icon: 'mdi-qrcode-remove' },
}

export const userStatusMeta: Record<string, StatusMeta> = {
  active: { label: '正常', color: 'success', icon: 'mdi-account-check' },
  disabled: { label: '已禁用', color: 'error', icon: 'mdi-account-off' },
  deleted: { label: '已删除', color: 'default', icon: 'mdi-account-remove' },
}

export const encryptionStateMeta: Record<EncryptionState, StatusMeta> = {
  encrypted: { label: '已加密', color: 'success', icon: 'mdi-lock' },
  decrypting: { label: '解密中', color: 'warning', icon: 'mdi-lock-open-alert' },
  decrypted: { label: '已解密', color: 'default', icon: 'mdi-lock-open' },
  encrypting: { label: '加密中', color: 'info', icon: 'mdi-lock-clock' },
  paused: { label: '已暂停', color: 'error', icon: 'mdi-alert-circle' },
  plaintext: { label: '明文存储', color: 'error', icon: 'mdi-lock-open-variant' },
}

export function botStatus(status: string): StatusMeta {
  return botStatusMeta[status as BotStatus] ?? { label: status || '未知', color: 'default', icon: 'mdi-help-circle' }
}

export function userStatus(status: string): StatusMeta {
  return userStatusMeta[status] ?? { label: status || '未知', color: 'default', icon: 'mdi-help-circle' }
}

export function encryptionState(state: string): StatusMeta {
  return encryptionStateMeta[state as EncryptionState] ?? { label: state || '未知', color: 'default', icon: 'mdi-help-circle' }
}

export function shortId(id?: string | null): string {
  if (!id) return '—'
  return id.length > 14 ? `${id.slice(0, 10)}…` : id
}

export function truncate(value: string, max = 80): string {
  return value.length > max ? `${value.slice(0, max)}…` : value
}
