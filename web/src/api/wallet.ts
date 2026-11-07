import { api } from './client'
import type { LedgerEntry, PageResult, Template, Wallet, WalletUsage } from '@/types'

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
