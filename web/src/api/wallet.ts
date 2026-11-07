import { api } from './client'
import type { LedgerEntry, PageResult, Template, UsageByBot, UsageDaily, Wallet, WalletUsage } from '@/types'

export function listTemplates(): Promise<{ items: Template[] }> {
  return api.get<{ items: Template[] }>('/templates')
}

export function getWallet(): Promise<Wallet> {
  return api.get<Wallet>('/wallet')
}

export function getWalletLedger(page = 1, pageSize = 20): Promise<PageResult<LedgerEntry>> {
  return api.get<PageResult<LedgerEntry>>('/wallet/ledger', { page, page_size: pageSize })
}

/** 平台点数账本的每日余额走势（不是上游模型账户余额）。 */
export function getWalletUsage(days = 14): Promise<WalletUsage> {
  return api.get<WalletUsage>('/wallet/usage', { days })
}

/** 每日点数消耗（来自 usage_records，图表用）。 */
export function getDailyUsage(days = 30, botId?: string): Promise<UsageDaily> {
  return api.get<UsageDaily>('/me/usage/daily', { days, bot_id: botId || undefined })
}

export function getUsageByBot(days = 30): Promise<{ days: number; items: UsageByBot[] }> {
  return api.get<{ days: number; items: UsageByBot[] }>('/me/usage/by-bot', { days })
}
