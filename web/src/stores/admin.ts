import { defineStore } from 'pinia'
import { ref } from 'vue'
import * as adminApi from '@/api/admin'
import { toApiError, type ApiError } from '@/api/client'
import type {
  AdminBot,
  AdminLedgerAdjustPayload,
  AdminLedgerAdjustResult,
  AdminOrder,
  AdminOrderConfirmResult,
  AdminOrderCreatePayload,
  AdminOrderCreateResult,
  AdminUser,
  AdminOverview,
  AdminUserQuery,
  AuditLog,
  ConfProfile,
  AuditQuery,
  PageResult,
  Quota,
  Template,
  TemplateInput,
} from '@/types'

export const useAdminStore = defineStore('admin', () => {
  const templates = ref<Template[]>([])
  const templatesLoading = ref(false)
  const templatesError = ref<ApiError | null>(null)
  const confProfiles = ref<ConfProfile[]>([])
  const overview = ref<AdminOverview | null>(null)
  const overviewLoading = ref(false)
  const overviewError = ref<ApiError | null>(null)

  const users = ref<AdminUser[]>([])
  const usersTotal = ref(0)
  const usersPage = ref(1)
  const usersPageSize = ref(20)
  const usersLoading = ref(false)
  const usersError = ref<ApiError | null>(null)

  const bots = ref<AdminBot[]>([])
  const botsLoading = ref(false)
  const botsError = ref<ApiError | null>(null)

  const orders = ref<AdminOrder[]>([])
  const ordersTotal = ref(0)
  const ordersPage = ref(1)
  const ordersPageSize = ref(20)
  const ordersLoading = ref(false)
  const ordersError = ref<ApiError | null>(null)

  const audit = ref<AuditLog[]>([])
  const auditTotal = ref(0)
  const auditPage = ref(1)
  const auditPageSize = ref(20)
  const auditLoading = ref(false)
  const auditError = ref<ApiError | null>(null)

  async function loadConfProfiles(): Promise<ConfProfile[]> {
    try {
      const result = await adminApi.listConfProfiles()
      confProfiles.value = result.items ?? []
      return confProfiles.value
    } catch {
      confProfiles.value = [{ id: 'default', name: '默认配置', is_default: true }]
      return confProfiles.value
    }
  }

  async function loadOverview(): Promise<AdminOverview | null> {
    overviewLoading.value = true
    overviewError.value = null
    try {
      overview.value = await adminApi.getAdminOverview()
      return overview.value
    } catch (err) {
      overviewError.value = toApiError(err)
      return null
    } finally {
      overviewLoading.value = false
    }
  }

  async function loadTemplates(): Promise<Template[]> {
    templatesLoading.value = true
    templatesError.value = null
    try {
      const result = await adminApi.listAdminTemplates()
      templates.value = result.items ?? []
      return templates.value
    } catch (err) {
      templatesError.value = toApiError(err)
      throw templatesError.value
    } finally {
      templatesLoading.value = false
    }
  }

  async function createTemplate(payload: TemplateInput): Promise<Template> {
    const result = await adminApi.createAdminTemplate(payload)
    templates.value = [result.template, ...templates.value]
    return result.template
  }

  async function updateTemplate(id: string, payload: Partial<TemplateInput>): Promise<Template> {
    const result = await adminApi.updateAdminTemplate(id, payload)
    const index = templates.value.findIndex((item) => item.id === id)
    if (index >= 0) templates.value.splice(index, 1, result.template)
    return result.template
  }

  async function removeTemplate(id: string): Promise<void> {
    await adminApi.deleteAdminTemplate(id)
    const target = templates.value.find((item) => item.id === id)
    if (target) target.enabled = false
  }

  async function loadUsers(query: AdminUserQuery = {}): Promise<PageResult<AdminUser>> {
    usersLoading.value = true
    usersError.value = null
    try {
      const result = await adminApi.listAdminUsers(query)
      users.value = result.items ?? []
      usersTotal.value = result.total ?? 0
      usersPage.value = result.page ?? query.page ?? 1
      usersPageSize.value = result.page_size ?? query.page_size ?? 20
      return result
    } catch (err) {
      usersError.value = toApiError(err)
      throw usersError.value
    } finally {
      usersLoading.value = false
    }
  }

  async function setUserStatus(
    id: string,
    status: 'active' | 'disabled',
    reason = '',
  ): Promise<AdminUser> {
    const result = await adminApi.patchAdminUser(id, { status, ...(reason ? { reason } : {}) })
    const index = users.value.findIndex((item) => item.id === id)
    if (index >= 0) users.value.splice(index, 1, result.user)
    return result.user
  }

  async function updateUserQuota(id: string, quota: Quota): Promise<AdminUser> {
    const result = await adminApi.patchAdminUser(id, { quota })
    const index = users.value.findIndex((item) => item.id === id)
    if (index >= 0) users.value.splice(index, 1, result.user)
    return result.user
  }

  async function loadBots(): Promise<AdminBot[]> {
    botsLoading.value = true
    botsError.value = null
    try {
      const result = await adminApi.listAdminBots()
      bots.value = result.items ?? []
      return bots.value
    } catch (err) {
      botsError.value = toApiError(err)
      throw botsError.value
    } finally {
      botsLoading.value = false
    }
  }

  async function disableBot(id: string, reason = ''): Promise<void> {
    const result = await adminApi.disableAdminBot(id, reason)
    const index = bots.value.findIndex((item) => item.id === id)
    if (index >= 0) bots.value.splice(index, 1, { ...bots.value[index], ...result.bot })
  }

  async function loadAudit(query: AuditQuery = {}): Promise<PageResult<AuditLog>> {
    auditLoading.value = true
    auditError.value = null
    try {
      const result = await adminApi.listAdminAudit(query)
      audit.value = result.items ?? []
      auditTotal.value = result.total ?? 0
      auditPage.value = result.page ?? query.page ?? 1
      auditPageSize.value = result.page_size ?? query.page_size ?? 20
      return result
    } catch (err) {
      auditError.value = toApiError(err)
      throw auditError.value
    } finally {
      auditLoading.value = false
    }
  }

  async function loadOrders(
    query: { page?: number; page_size?: number } = {},
  ): Promise<PageResult<AdminOrder>> {
    ordersLoading.value = true
    ordersError.value = null
    try {
      const result = await adminApi.listAdminOrders(query)
      orders.value = result.items ?? []
      ordersTotal.value = result.total ?? 0
      ordersPage.value = result.page ?? query.page ?? 1
      ordersPageSize.value = result.page_size ?? query.page_size ?? 20
      return result
    } catch (err) {
      ordersError.value = toApiError(err)
      throw ordersError.value
    } finally {
      ordersLoading.value = false
    }
  }

  async function createOrder(payload: AdminOrderCreatePayload): Promise<AdminOrderCreateResult> {
    return adminApi.createAdminOrder(payload)
  }

  async function confirmOrder(orderId: string): Promise<AdminOrderConfirmResult> {
    const result = await adminApi.confirmAdminOrder(orderId)
    const index = orders.value.findIndex((order) => order.id === orderId)
    if (index >= 0) orders.value.splice(index, 1, { ...orders.value[index], ...result.order })
    return result
  }

  async function adjustLedger(
    payload: AdminLedgerAdjustPayload,
  ): Promise<AdminLedgerAdjustResult> {
    return adminApi.adjustAdminLedger(payload)
  }

  return {
    templates,
    templatesLoading,
    templatesError,
    confProfiles,
    overview,
    overviewLoading,
    overviewError,
    loadConfProfiles,
    loadOverview,
    users,
    usersTotal,
    usersPage,
    usersPageSize,
    usersLoading,
    usersError,
    bots,
    botsLoading,
    botsError,
    orders,
    ordersTotal,
    ordersPage,
    ordersPageSize,
    ordersLoading,
    ordersError,
    audit,
    auditTotal,
    auditPage,
    auditPageSize,
    auditLoading,
    auditError,
    loadTemplates,
    createTemplate,
    updateTemplate,
    removeTemplate,
    loadUsers,
    setUserStatus,
    updateUserQuota,
    loadBots,
    disableBot,
    loadAudit,
    loadOrders,
    createOrder,
    confirmOrder,
    adjustLedger,
  }
})
