import { api } from './client'
import type { LedgerEntry, PageResult, Template, Wallet } from '@/types'

export function listTemplates(): Promise<{ items: Template[] }> {
  return api.get<{ items: Template[] }>('/templates')
}

export function getWallet(): Promise<Wallet> {
  return api.get<Wallet>('/wallet')
}

export function getWalletLedger(page = 1, pageSize = 20): Promise<PageResult<LedgerEntry>> {
  return api.get<PageResult<LedgerEntry>>('/wallet/ledger', { page, page_size: pageSize })
}
