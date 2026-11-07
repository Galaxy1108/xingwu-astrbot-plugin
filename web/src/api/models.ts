import { api } from './client'
import type { ModelProfileList } from '@/types'

/** 用户可选模型配置（enabled 的公开目录）。 */
export function listModels(): Promise<ModelProfileList> {
  return api.get<ModelProfileList>('/models')
}
