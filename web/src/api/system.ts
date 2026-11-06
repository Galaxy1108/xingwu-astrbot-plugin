import { api } from './client'
import type { VersionInfo } from '@/types'

export function getVersion(): Promise<VersionInfo> {
  return api.get<VersionInfo>('/version')
}
