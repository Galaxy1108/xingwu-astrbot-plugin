import { api } from './client'
import type {
  AdminBot,
  AdminConversationList,
  AdminLedgerAdjustPayload,
  AdminLedgerAdjustResult,
  AdminOrder,
  AdminOrderConfirmResult,
  AdminOrderCreatePayload,
  AdminOrderCreateResult,
  AdminOverview,
  AdminUser,
  AdminUserPatch,
  AdminUserQuery,
  ConfProfile,
  AuditLog,
  AuditQuery,
  Bot,
  MemoryExportResult,
  MemoryItem,
  MemoryListQuery,
  MemoryPatch,
  MemorySettings,
  MemorySettingsKind,
  MemorySettingsPatch,
  MemorySettingsTestResult,
  ModelProfile,
  ModelProfileInput,
  ModelProfileList,
  PageResult,
  Template,
  TemplateInput,
} from '@/types'

export function listConfProfiles(): Promise<{ items: ConfProfile[] }> {
  return api.get<{ items: ConfProfile[] }>('/admin/conf-profiles')
}

export function getAdminOverview(): Promise<AdminOverview> {
  return api.get<AdminOverview>('/admin/overview')
}

export function listAdminTemplates(): Promise<{ items: Template[] }> {
  return api.get<{ items: Template[] }>('/admin/templates')
}

export function createAdminTemplate(payload: TemplateInput): Promise<{ template: Template }> {
  return api.post<{ template: Template }>('/admin/templates', payload)
}

export function updateAdminTemplate(id: string, payload: Partial<TemplateInput>): Promise<{ template: Template }> {
  return api.patch<{ template: Template }>(`/admin/templates/${encodeURIComponent(id)}`, payload)
}

export function deleteAdminTemplate(id: string): Promise<{ deleted: boolean }> {
  return api.delete<{ deleted: boolean }>(`/admin/templates/${encodeURIComponent(id)}`)
}

export function listAdminUsers(params: AdminUserQuery = {}): Promise<PageResult<AdminUser>> {
  return api.get<PageResult<AdminUser>>('/admin/users', {
    page: params.page,
    page_size: params.page_size,
    q: params.q,
    status: params.status,
  })
}

export function patchAdminUser(id: string, payload: AdminUserPatch): Promise<{ user: AdminUser }> {
  return api.patch<{ user: AdminUser }>(`/admin/users/${encodeURIComponent(id)}`, payload)
}

export function listAdminBots(): Promise<{ items: AdminBot[] }> {
  return api.get<{ items: AdminBot[] }>('/admin/bots')
}

export function disableAdminBot(id: string): Promise<{ bot: Bot }> {
  return api.post<{ bot: Bot }>(`/admin/bots/${encodeURIComponent(id)}/disable`)
}

export function deleteAdminBot(id: string, confirmName: string): Promise<{ deleted: boolean }> {
  return api.delete<{ deleted: boolean }>(`/admin/bots/${encodeURIComponent(id)}`, {
    confirm_name: confirmName,
  })
}

export function listAdminAudit(params: AuditQuery = {}): Promise<PageResult<AuditLog>> {
  return api.get<PageResult<AuditLog>>('/admin/audit', {
    page: params.page,
    page_size: params.page_size,
    action: params.action,
    actor_id: params.actor_id,
    target_id: params.target_id,
  })
}

// ------------------------------------------------------------------ M3 手动额度
export function listAdminOrders(
  params: { page?: number; page_size?: number } = {},
): Promise<PageResult<AdminOrder>> {
  return api.get<PageResult<AdminOrder>>('/admin/orders', {
    page: params.page,
    page_size: params.page_size,
  })
}

export function createAdminOrder(
  payload: AdminOrderCreatePayload,
): Promise<AdminOrderCreateResult> {
  return api.post<AdminOrderCreateResult>('/admin/orders', payload)
}

export function confirmAdminOrder(orderId: string): Promise<AdminOrderConfirmResult> {
  return api.post<AdminOrderConfirmResult>(
    `/admin/orders/${encodeURIComponent(orderId)}/confirm`,
  )
}

export function adjustAdminLedger(
  payload: AdminLedgerAdjustPayload,
): Promise<AdminLedgerAdjustResult> {
  return api.post<AdminLedgerAdjustResult>('/admin/ledger', payload)
}

export function reconcileAdminWallet(
  userId: string,
): Promise<{ user_id: string; balance: number }> {
  return api.post<{ user_id: string; balance: number }>(
    `/admin/users/${encodeURIComponent(userId)}/wallet/reconcile`,
  )
}

// ------------------------------------------------------------------ 管理端内容查看
export function listAdminBotConversations(botId: string): Promise<AdminConversationList> {
  return api.get<AdminConversationList>(
    `/admin/bots/${encodeURIComponent(botId)}/conversations`,
  )
}

export function listAdminBotMemories(
  botId: string,
  query: MemoryListQuery = {},
): Promise<PageResult<MemoryItem>> {
  return api.get<PageResult<MemoryItem>>(
    `/admin/bots/${encodeURIComponent(botId)}/memories`,
    {
      page: query.page,
      page_size: query.page_size,
      kind: query.kind,
      q: query.q,
    },
  )
}

export function patchAdminBotMemory(
  botId: string,
  memoryId: number,
  payload: MemoryPatch,
): Promise<{ memory: MemoryItem }> {
  return api.patch<{ memory: MemoryItem }>(
    `/admin/bots/${encodeURIComponent(botId)}/memories/${memoryId}`,
    payload,
  )
}

export function deleteAdminBotMemory(
  botId: string,
  memoryId: number,
): Promise<{ deleted: boolean }> {
  return api.delete<{ deleted: boolean }>(
    `/admin/bots/${encodeURIComponent(botId)}/memories/${memoryId}`,
  )
}

/** 管理端记忆导出：必须显式二次确认，服务端会记录审计。 */
export function exportAdminBotMemories(botId: string): Promise<MemoryExportResult> {
  return api.post<MemoryExportResult>(
    `/admin/bots/${encodeURIComponent(botId)}/memories/export`,
    { confirm: true },
  )
}

// ------------------------------------------------------------------ 记忆 API 设置
export function getMemorySettings(): Promise<MemorySettings> {
  return api.get<MemorySettings>('/admin/settings/memory')
}

export function updateMemorySettings(
  payload: MemorySettingsPatch,
): Promise<MemorySettings> {
  return api.put<MemorySettings>('/admin/settings/memory', payload)
}

export function testMemorySettings(
  kind: MemorySettingsKind,
): Promise<MemorySettingsTestResult> {
  return api.post<MemorySettingsTestResult>('/admin/settings/memory/test', { kind })
}

// ------------------------------------------------------------------ 模型与定价
export function listAdminModels(): Promise<ModelProfileList> {
  return api.get<ModelProfileList>('/admin/models')
}

export function createAdminModel(
  payload: ModelProfileInput,
): Promise<{ model: ModelProfile }> {
  return api.post<{ model: ModelProfile }>('/admin/models', payload)
}

export function updateAdminModel(
  id: string,
  payload: Partial<ModelProfileInput>,
): Promise<{ model: ModelProfile }> {
  return api.patch<{ model: ModelProfile }>(
    `/admin/models/${encodeURIComponent(id)}`,
    payload,
  )
}

/** 删除即软禁用（enabled=false），保留历史用量/定价。 */
export function deleteAdminModel(id: string): Promise<{ deleted: boolean }> {
  return api.delete<{ deleted: boolean }>(`/admin/models/${encodeURIComponent(id)}`)
}
