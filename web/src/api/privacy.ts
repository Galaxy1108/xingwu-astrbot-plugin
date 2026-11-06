import { api } from './client'
import type { AccessLogEntry, EncryptionStatus, PageResult } from '@/types'

export function listAccessLog(page = 1, pageSize = 20): Promise<PageResult<AccessLogEntry>> {
  return api.get<PageResult<AccessLogEntry>>('/access-log', { page, page_size: pageSize })
}

export function getEncryptionStatus(): Promise<EncryptionStatus> {
  return api.get<EncryptionStatus>('/me/encryption')
}
