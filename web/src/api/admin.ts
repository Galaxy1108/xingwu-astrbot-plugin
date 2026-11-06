import { api } from './client'
import type {
  AdminBot,
  AdminLedgerAdjustPayload,
  AdminLedgerAdjustResult,
  AdminOrder,
  AdminOrderConfirmResult,
  AdminOrderCreatePayload,
  AdminOrderCreateResult,
  AdminUser,
  AdminUserPatch,
  AdminUserQuery,
  AuditLog,
  AuditQuery,
  Bot,
  PageResult,
  Template,
  TemplateInput,
} from '@/types'

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
