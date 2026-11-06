import { api } from './client'
import type {
  AdminBot,
  AdminUser,
  AdminUserPatch,
  AuditLog,
  AuditQuery,
  Bot,
  PageResult,
  Template,
  TemplateInput,
  AdminUserQuery,
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
