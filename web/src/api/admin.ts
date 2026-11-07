import { api, isApiError } from './client'
import type {
  AdminBot,
  AdminConversationList,
  AdminLedgerAdjustPayload,
  AdminLedgerAdjustResult,
  AdminOrder,
  AdminOrderConfirmResult,
  AdminOrderCreatePayload,
  AdminOrderCreateResult,
  AdminInvite,
  AdminInviteCreatePayload,
  AdminOAuthSettings,
  AdminOverview,
  AdminUser,
  AdminUserDetail,
  AdminUserPatch,
  AdminUserUsage,
  AdminUserQuery,
  ConfProfile,
  AuditLog,
  AuditQuery,
  Bot,
  MemoryExportResult,
  MemoryImportReport,
  NoteReadPage,
  NoteSummary,
  RedemptionCode,
  RedemptionCodeCreatePayload,
  RedemptionCodeCreateResult,
  MemoryItem,
  MemoryListQuery,
  MemoryPatch,
  MemorySettings,
  MemorySettingsKind,
  MemorySettingsPatch,
  MemorySettingsStatus,
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

export async function disableAdminBot(
  id: string,
  reason = '',
): Promise<{ bot: Bot }> {
  try {
    return await api.patch<{ bot: Bot }>(`/admin/bots/${encodeURIComponent(id)}`, {
      disabled: true,
      reason,
    })
  } catch (error) {
    if (isApiError(error) && (error.status === 404 || error.status === 405)) {
      return api.post<{ bot: Bot }>(`/admin/bots/${encodeURIComponent(id)}/disable`)
    }
    throw error
  }
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
export function listAdminBotConversations(
  botId: string,
  confirm = false,
): Promise<AdminConversationList> {
  return api.get<AdminConversationList>(
    `/admin/bots/${encodeURIComponent(botId)}/conversations`,
    confirm ? { confirm: 1 } : undefined,
  )
}

export function listAdminBotMemories(
  botId: string,
  query: MemoryListQuery = {},
  confirm = false,
): Promise<PageResult<MemoryItem>> {
  const params: Record<string, string | number | undefined> = {
    page: query.page,
    page_size: query.page_size,
    kind: query.kind,
    q: query.q,
    importance: query.importance,
  }
  if (confirm) params.confirm = 1
  return api.get<PageResult<MemoryItem>>(
    `/admin/bots/${encodeURIComponent(botId)}/memories`,
    params,
  )
}

export function patchAdminBotMemory(
  botId: string,
  memoryId: number,
  payload: MemoryPatch,
  confirm = false,
): Promise<{ memory: MemoryItem }> {
  return api.patch<{ memory: MemoryItem }>(
    `/admin/bots/${encodeURIComponent(botId)}/memories/${memoryId}${confirm ? '?confirm=1' : ''}`,
    payload,
  )
}

export function deleteAdminBotMemory(
  botId: string,
  memoryId: number,
  confirm = false,
): Promise<{ deleted: boolean }> {
  return api.delete<{ deleted: boolean }>(
    `/admin/bots/${encodeURIComponent(botId)}/memories/${memoryId}${confirm ? '?confirm=1' : ''}`,
  )
}

/** 管理端记忆导出：必须显式二次确认，服务端会记录审计。 */
export function exportAdminBotMemories(
  botId: string,
  confirm = false,
): Promise<MemoryExportResult> {
  return api.post<MemoryExportResult>(
    `/admin/bots/${encodeURIComponent(botId)}/memories/export${confirm ? '?confirm=1' : ''}`,
    { confirm: true },
  )
}

/** 管理端快照导入；加密用户需 confirm=1（服务端记录访问审计）。 */
export function importAdminBotMemories(
  botId: string,
  snapshot: Record<string, unknown>,
  dryRun = false,
  confirm = false,
): Promise<MemoryImportReport> {
  return api.post<MemoryImportReport>(
    `/admin/bots/${encodeURIComponent(botId)}/memories/import${confirm ? '?confirm=1' : ''}`,
    { snapshot, dry_run: dryRun },
  )
}

// ------------------------------------------------------------------ 记忆 API 设置
export function getMemorySettings(): Promise<MemorySettings> {
  return api.get<MemorySettings>('/admin/settings/memory')
}

export function getAdminOAuthSettings(): Promise<AdminOAuthSettings> {
  return api.get<AdminOAuthSettings>('/admin/settings/oauth')
}

export function updateAdminOAuthSettings(
  payload: AdminOAuthSettings & { client_secret?: string },
): Promise<AdminOAuthSettings> {
  return api.put<AdminOAuthSettings>('/admin/settings/oauth', payload)
}

export function getMemorySettingsStatus(): Promise<MemorySettingsStatus> {
  return api.get<MemorySettingsStatus>('/admin/settings/memory/status')
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

// ------------------------------------------------------------------ 兑换码
export function listRedemptionCodes(
  params: { page?: number; page_size?: number } = {},
): Promise<PageResult<RedemptionCode>> {
  return api.get<PageResult<RedemptionCode>>('/admin/redemption-codes', {
    page: params.page,
    page_size: params.page_size,
  })
}

export function createRedemptionCodes(
  payload: RedemptionCodeCreatePayload,
): Promise<RedemptionCodeCreateResult> {
  return api.post<RedemptionCodeCreateResult>('/admin/redemption-codes', payload)
}

/** 禁用兑换码；兼容 POST .../{code}/disable 与 DELETE 两种实现。 */
export async function disableRedemptionCode(code: string): Promise<{ disabled?: boolean }> {
  try {
    return await api.post<{ disabled?: boolean }>(
      `/admin/redemption-codes/${encodeURIComponent(code)}/disable`,
    )
  } catch (error) {
    if (isApiError(error) && error.status === 404) {
      return api.delete<{ disabled?: boolean }>(
        `/admin/redemption-codes/${encodeURIComponent(code)}`,
      )
    }
    throw error
  }
}

// ------------------------------------------------------------------ 用户详情（M4）
export function getAdminUser(
  id: string,
): Promise<AdminUserDetail | { user: AdminUserDetail }> {
  return api.get<AdminUserDetail | { user: AdminUserDetail }>(
    `/admin/users/${encodeURIComponent(id)}`,
  )
}

export function getAdminUserUsage(
  id: string,
  page = 1,
  pageSize = 20,
): Promise<AdminUserUsage> {
  return api.get<AdminUserUsage>(`/admin/users/${encodeURIComponent(id)}/usage`, {
    page,
    page_size: pageSize,
  })
}

// ------------------------------------------------------------------ 管理端笔记
export function listAdminBotNotes(
  botId: string,
  query: { page?: number; page_size?: number; q?: string; tag?: string } = {},
  confirm = false,
): Promise<PageResult<NoteSummary>> {
  const params: Record<string, string | number | undefined> = {
    page: query.page,
    page_size: query.page_size,
    q: query.q,
    tag: query.tag,
  }
  if (confirm) params.confirm = 1
  return api.get<PageResult<NoteSummary>>(
    `/admin/bots/${encodeURIComponent(botId)}/notes`,
    params,
  )
}

export function readAdminBotNote(
  botId: string,
  shortId: string,
  confirm = false,
): Promise<NoteReadPage> {
  return api.get<NoteReadPage>(
    `/admin/bots/${encodeURIComponent(botId)}/notes/${encodeURIComponent(shortId)}${confirm ? '?confirm=1' : ''}`,
  )
}

export function deleteAdminBotNote(
  botId: string,
  shortId: string,
  confirm = false,
): Promise<{ deleted: boolean }> {
  return api.delete<{ deleted: boolean }>(
    `/admin/bots/${encodeURIComponent(botId)}/notes/${encodeURIComponent(shortId)}${confirm ? '?confirm=1' : ''}`,
  )
}


export function listAdminInvites(page = 1, pageSize = 50): Promise<PageResult<AdminInvite>> {
  return api.get<PageResult<AdminInvite>>('/admin/invites', { page, page_size: pageSize })
}

export function createAdminInvite(
  payload: AdminInviteCreatePayload,
): Promise<{ invite: AdminInvite & { code: string } }> {
  return api.post<{ invite: AdminInvite & { code: string } }>('/admin/invites', payload)
}

export function revokeAdminInvite(codeHint: string): Promise<{ revoked: boolean }> {
  return api.delete<{ revoked: boolean }>(`/admin/invites/${encodeURIComponent(codeHint)}`)
}
