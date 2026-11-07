<template>
  <div>
    <PageHeader
      title="手动充值"
      description="创建充值单并确认到账，或直接对账本做加/扣；所有额度变动只写 append-only 账本，重复提交幂等。"
    >
      <template #actions>
        <v-btn variant="text" prepend-icon="mdi-refresh" :loading="admin.ordersLoading" @click="reload">
          刷新
        </v-btn>
        <v-btn variant="tonal" prepend-icon="mdi-account-cash-outline" @click="openAdjust">
          手动加/扣额度
        </v-btn>
        <v-btn color="primary" prepend-icon="mdi-plus" @click="openCreate" variant="tonal">新建充值单</v-btn>
      </template>
    </PageHeader>

    <v-alert type="info" variant="tonal" density="compact" class="mb-4" icon="mdi-bookshelf">
      余额由账本汇总决定：确认到账、同一外部单号、同一幂等键重复提交都不会重复入账。
    </v-alert>

    <v-alert v-if="admin.ordersError" type="error" variant="tonal" class="mb-4">
      <div class="alert-row">
        <span>{{ admin.ordersError.message }}</span>
        <v-btn size="small" variant="text" color="error" @click="reload">重试</v-btn>
      </div>
    </v-alert>

    <LoadingSkeleton v-if="admin.ordersLoading && !admin.orders.length" variant="table" :rows="5" />

    <EmptyState
      v-else-if="!admin.ordersError && admin.orders.length === 0"
      icon="mdi-cash-plus"
      title="暂无充值订单"
      description="新建充值单后，管理员确认到账才会写入账本并增加用户余额。"
      :actions="[{ label: '新建充值单', onClick: openCreate }]"
    />

    <v-card v-else-if="admin.orders.length" class="table-card">
      <div class="table-head">
        <div class="text-muted table-count">
          共 {{ admin.ordersTotal }} 单 · 当前第 {{ admin.ordersPage }} 页
        </div>
        <div class="text-muted table-hint">待确认订单需管理员确认后入账</div>
      </div>
      <div class="table-scroll">
        <v-table hover>
          <thead>
            <tr>
              <th>订单号</th>
              <th>用户</th>
              <th>金额</th>
              <th>点数</th>
              <th>状态</th>
              <th class="nowrap">创建时间</th>
              <th class="nowrap">到账时间</th>
              <th class="text-right nowrap">操作</th>
            </tr>
          </thead>
          <tbody>
            <tr v-for="order in admin.orders" :key="order.id" data-testid="order-row">
              <td class="order-cell">
                <div class="text-mono order-id">{{ order.id }}</div>
                <div v-if="order.external_ref" class="text-mono text-muted order-ref" :title="order.external_ref">
                  {{ order.external_ref }}
                </div>
              </td>
              <td>
                <div class="user-email" :title="order.user_email || ''">
                  {{ order.user_email || '—' }}
                </div>
                <div class="text-mono text-muted user-id">{{ order.user_id }}</div>
              </td>
              <td class="nowrap">{{ money(order.amount_cny) }}</td>
              <td class="nowrap credits">+{{ formatNumber(order.credits) }}</td>
              <td>
                <v-chip
                  :color="order.status === 'paid' ? 'success' : 'warning'"
                  variant="tonal"
                  size="small"
                  :prepend-icon="order.status === 'paid' ? 'mdi-check-circle' : 'mdi-clock-outline'"
                >
                  {{ order.status === 'paid' ? '已到账' : '待确认' }}
                </v-chip>
              </td>
              <td class="nowrap">{{ formatDateTime(order.created_at) }}</td>
              <td class="nowrap">{{ order.paid_at ? formatDateTime(order.paid_at) : '—' }}</td>
              <td class="text-right nowrap">
                <v-btn
                  v-if="order.status === 'pending'"
                  size="small"
                  color="primary"
                  variant="tonal"
                  data-testid="order-confirm"
                  @click="askConfirm(order)"
                >
                  确认到账
                </v-btn>
                <span v-else class="text-muted">—</span>
              </td>
            </tr>
          </tbody>
        </v-table>
      </div>

      <div v-if="admin.ordersTotal > admin.ordersPageSize" class="pager">
        <v-pagination
          :model-value="admin.ordersPage"
          :length="pageCount"
          :total-visible="5"
          density="comfortable"
          @update:model-value="onPage"
        />
      </div>
    </v-card>

    <!-- 新建充值单 -->
    <v-dialog v-model="createOpen" max-width="580" persistent>
      <v-card class="dialog-card">
        <v-card-title class="dialog-title">新建充值单</v-card-title>
        <v-card-text>
          <v-alert v-if="createError" type="error" variant="tonal" density="compact" class="mb-3">
            {{ createError }}
          </v-alert>
          <v-alert v-if="usersError" type="warning" variant="tonal" density="compact" class="mb-3">
            <div class="alert-row">
              <span>{{ usersError }}</span>
              <v-btn size="small" variant="text" @click="loadUsers">重试</v-btn>
            </div>
          </v-alert>

          <v-autocomplete
            v-model="orderForm.user_id"
            :items="userOptions"
            item-title="title"
            item-value="value"
            label="用户（可输入邮箱搜索）"
            :loading="usersLoading"
            no-data-text="暂无用户"
            :error-messages="orderErrors.user_id"
            class="mb-2"
          />
          <v-text-field
            v-model="orderForm.credits"
            label="点数（必填，正整数）"
            type="number"
            min="1"
            inputmode="numeric"
            :error-messages="orderErrors.credits"
            class="mb-2"
          />
          <v-text-field
            v-model="orderForm.amount_cny"
            label="金额（¥，可选）"
            type="number"
            min="0"
            step="0.01"
            :error-messages="orderErrors.amount_cny"
            class="mb-2"
          />
          <v-text-field
            v-model="orderForm.external_ref"
            label="外部单号（可选，用于防重）"
            hint="相同外部单号重复创建会返回已有订单，不会重复入账"
            persistent-hint
            class="mb-2"
          />
          <v-textarea
            v-model="orderForm.note"
            label="备注（写入审计）"
            rows="2"
            auto-grow
          />
        </v-card-text>
        <v-card-actions>
          <v-spacer />
          <v-btn variant="text" :disabled="creating" @click="createOpen = false">取消</v-btn>
          <v-btn color="primary" :loading="creating" data-testid="order-create-submit" @click="submitCreate" variant="tonal">
            创建
          </v-btn>
        </v-card-actions>
      </v-card>
    </v-dialog>

    <!-- 手动加/扣额度 -->
    <v-dialog v-model="adjustOpen" max-width="560" persistent>
      <v-card class="dialog-card">
        <v-card-title class="dialog-title">手动加 / 扣额度</v-card-title>
        <v-card-text>
          <v-alert v-if="adjustError" type="error" variant="tonal" density="compact" class="mb-3">
            {{ adjustError }}
          </v-alert>
          <v-alert v-if="usersError" type="warning" variant="tonal" density="compact" class="mb-3">
            <div class="alert-row">
              <span>{{ usersError }}</span>
              <v-btn size="small" variant="text" @click="loadUsers">重试</v-btn>
            </div>
          </v-alert>

          <v-autocomplete
            v-model="adjustForm.user_id"
            :items="userOptions"
            item-title="title"
            item-value="value"
            label="用户（可输入邮箱搜索）"
            :loading="usersLoading"
            no-data-text="暂无用户"
            :error-messages="adjustErrors.user_id"
            class="mb-2"
          />
          <v-text-field
            v-model="adjustForm.delta"
            label="调整点数（正数加、负数扣，不能为 0）"
            type="number"
            step="1"
            inputmode="numeric"
            :error-messages="adjustErrors.delta"
            data-testid="ledger-delta"
            class="mb-2"
          />
          <v-text-field
            v-model="adjustForm.reason"
            label="原因（写入审计）"
            class="mb-2"
          />
          <v-text-field
            v-model="adjustForm.idem_key"
            label="幂等键（可选，防重复扣减）"
            hint="相同幂等键重复提交只入账一次"
            persistent-hint
          />
          <p class="adjust-hint text-muted">
            直接写 append-only 账本并同步余额缓存；不会修改历史流水。对账异常时可让后端重算余额。
          </p>
        </v-card-text>
        <v-card-actions>
          <v-spacer />
          <v-btn variant="text" :disabled="adjusting" @click="adjustOpen = false">取消</v-btn>
          <v-btn color="primary" :loading="adjusting" data-testid="ledger-submit" @click="submitAdjust" variant="tonal">
            提交
          </v-btn>
        </v-card-actions>
      </v-card>
    </v-dialog>

    <ConfirmDialog
      v-model="confirmOpen"
      title="确认到账？"
      :message="confirmMessage"
      confirm-text="确认到账"
      :loading="confirming"
      @confirm="confirmArrival"
      @cancel="confirmOpen = false"
    />
  </div>
</template>

<script setup lang="ts">
import { computed, onMounted, reactive, ref, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import PageHeader from '@/components/PageHeader.vue'
import EmptyState from '@/components/EmptyState.vue'
import LoadingSkeleton from '@/components/LoadingSkeleton.vue'
import ConfirmDialog from '@/components/ConfirmDialog.vue'
import { useAdminStore } from '@/stores/admin'
import { useUiStore } from '@/stores/ui'
import { listAdminUsers } from '@/api/admin'
import { toApiError } from '@/api/client'
import type { AdminOrder, AdminUser } from '@/types'
import { errorMessage, fieldError } from '@/utils/errors'
import { formatDateTime, formatNumber } from '@/utils/format'
import {
  buildAdjustPayload,
  buildOrderPayload,
  hasErrors,
  validateAdjustForm,
  validateOrderForm,
  type AdjustFormErrors,
  type AdjustFormState,
  type OrderFormErrors,
  type OrderFormState,
} from '@/utils/walletAdmin'

const admin = useAdminStore()
const ui = useUiStore()
const route = useRoute()
const router = useRouter()

const orderUsers = ref<AdminUser[]>([])
const usersLoading = ref(false)
const usersError = ref('')

const createOpen = ref(false)
const creating = ref(false)
const createError = ref('')
const orderForm = reactive<OrderFormState>({
  user_id: '',
  credits: '',
  amount_cny: '',
  external_ref: '',
  note: '',
})
const orderErrors = reactive<OrderFormErrors>({})

const confirmOpen = ref(false)
const confirmTarget = ref<AdminOrder | null>(null)
const confirming = ref(false)

const adjustOpen = ref(false)
const adjusting = ref(false)
const adjustError = ref('')
const adjustForm = reactive<AdjustFormState>({
  user_id: '',
  delta: '',
  reason: '',
  idem_key: '',
})
const adjustErrors = reactive<AdjustFormErrors>({})

const userOptions = computed(() =>
  orderUsers.value.map((user) => ({
    title: `${user.email}（${user.id}）`,
    value: user.id,
  })),
)

const pageCount = computed(() =>
  Math.max(1, Math.ceil(admin.ordersTotal / Math.max(1, admin.ordersPageSize))),
)

const confirmMessage = computed(() => {
  const order = confirmTarget.value
  if (!order) return ''
  return [
    `用户：${order.user_email || order.user_id}`,
    `点数：+${formatNumber(order.credits)} · 金额：${money(order.amount_cny)}`,
    '确认后写入账本并增加余额；重复确认不会重复入账。',
  ].join('\n')
})

watch(
  () => route.query,
  () => {
    void load()
  },
  { immediate: true },
)

onMounted(() => {
  void loadUsers()
})

function stringQuery(value: unknown): string {
  const raw = Array.isArray(value) ? value[0] : value
  return typeof raw === 'string' ? raw : ''
}

function readPage(): number {
  const parsed = Number(stringQuery(route.query.page))
  return Number.isFinite(parsed) && parsed >= 1 ? Math.floor(parsed) : 1
}

async function load(): Promise<void> {
  try {
    await admin.loadOrders({ page: readPage(), page_size: 20 })
  } catch {
    /* store 已记录错误 */
  }
}

async function reload(): Promise<void> {
  await Promise.allSettled([load(), loadUsers()])
}

async function loadUsers(): Promise<void> {
  usersLoading.value = true
  usersError.value = ''
  try {
    const collected: AdminUser[] = []
    let page = 1
    for (;;) {
      const result = await listAdminUsers({ page, page_size: 100 })
      collected.push(...(result.items ?? []))
      if (!result.items?.length || collected.length >= (result.total ?? 0) || page >= 10) break
      page += 1
    }
    orderUsers.value = collected
  } catch (error) {
    usersError.value = errorMessage(error, '加载用户列表失败')
  } finally {
    usersLoading.value = false
  }
}

async function onPage(page: number): Promise<void> {
  await router.replace({ query: { ...route.query, page: String(page) } })
}

function openCreate(): void {
  Object.assign(orderForm, {
    user_id: '',
    credits: '',
    amount_cny: '',
    external_ref: '',
    note: '',
  })
  clearOrderErrors()
  createError.value = ''
  createOpen.value = true
  if (!orderUsers.value.length) void loadUsers()
}

function clearOrderErrors(): void {
  orderErrors.user_id = undefined
  orderErrors.credits = undefined
  orderErrors.amount_cny = undefined
}

async function submitCreate(): Promise<void> {
  clearOrderErrors()
  createError.value = ''
  const errors = validateOrderForm(orderForm)
  Object.assign(orderErrors, errors)
  if (hasErrors(errors)) return

  creating.value = true
  try {
    const result = await admin.createOrder(buildOrderPayload(orderForm))
    createOpen.value = false
    if (result.idempotent) {
      ui.notify('外部单号已存在，返回已有订单（未重复创建）', 'info', 6000)
    } else {
      ui.notify('充值单已创建（待确认到账）', 'success')
    }
    await router.replace({ query: {} })
    await load()
  } catch (error) {
    const apiError = toApiError(error)
    if (fieldError(apiError, 'credits')) orderErrors.credits = apiError.message
    createError.value = apiError.message
  } finally {
    creating.value = false
  }
}

function askConfirm(order: AdminOrder): void {
  confirmTarget.value = order
  confirmOpen.value = true
}

async function confirmArrival(): Promise<void> {
  if (!confirmTarget.value) return
  confirming.value = true
  try {
    const result = await admin.confirmOrder(confirmTarget.value.id)
    confirmOpen.value = false
    ui.notify(
      result.already_paid
        ? '该订单已到账（幂等，未重复入账）'
        : `已确认到账，${formatNumber(result.order.credits)} 点已入账`,
      'success',
    )
    await load()
  } catch (error) {
    confirmOpen.value = false
    ui.notifyError(errorMessage(error, '确认到账失败'))
  } finally {
    confirming.value = false
  }
}

function openAdjust(): void {
  Object.assign(adjustForm, {
    user_id: '',
    delta: '',
    reason: '',
    idem_key: '',
  })
  clearAdjustErrors()
  adjustError.value = ''
  adjustOpen.value = true
  if (!orderUsers.value.length) void loadUsers()
}

function clearAdjustErrors(): void {
  adjustErrors.user_id = undefined
  adjustErrors.delta = undefined
}

async function submitAdjust(): Promise<void> {
  clearAdjustErrors()
  adjustError.value = ''
  const errors = validateAdjustForm(adjustForm)
  Object.assign(adjustErrors, errors)
  if (hasErrors(errors)) return

  adjusting.value = true
  try {
    const delta = Number(adjustForm.delta)
    const result = await admin.adjustLedger(buildAdjustPayload(adjustForm))
    adjustOpen.value = false
    const action = delta > 0 ? '增加' : '扣减'
    ui.notify(
      result.idempotent
        ? `该幂等键已处理过，当前余额 ${formatNumber(result.balance)}`
        : `已${action} ${formatNumber(Math.abs(delta))} 点，当前余额 ${formatNumber(result.balance)}`,
      'success',
      6000,
    )
  } catch (error) {
    const apiError = toApiError(error)
    if (fieldError(apiError, 'delta')) adjustErrors.delta = apiError.message
    adjustError.value = apiError.message
  } finally {
    adjusting.value = false
  }
}

function money(value: number): string {
  return value > 0 ? `¥${value.toFixed(2)}` : '—'
}
</script>

<style scoped>
.table-card {
  padding: 4px 0;
}

.table-head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
  padding: 12px 16px 4px;
  font-size: 0.8rem;
}

.table-count {
  font-size: 0.8rem;
}

.table-hint {
  font-size: 0.76rem;
}

.table-scroll {
  overflow-x: auto;
}

.orders-table {
  min-width: 980px;
}

.order-cell {
  max-width: 190px;
}

.order-id {
  font-size: 0.76rem;
}

.order-ref {
  font-size: 0.7rem;
  max-width: 180px;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.user-email {
  font-weight: 600;
  max-width: 220px;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.user-id {
  font-size: 0.7rem;
  margin-top: 2px;
}

.credits {
  color: #2e7d32;
  font-weight: 600;
}

.nowrap {
  white-space: nowrap;
}

.pager {
  display: flex;
  justify-content: center;
  padding: 12px 0;
}

.alert-row {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
  flex-wrap: wrap;
}

.dialog-card {
  padding: 8px;
}

.dialog-title {
  font-size: 1.05rem;
  font-weight: 650;
  padding: 12px 20px 0;
}

.adjust-hint {
  margin: 12px 0 0;
  font-size: 0.76rem;
  line-height: 1.6;
}

@media (max-width: 599px) {
  .table-head {
    flex-direction: column;
    align-items: flex-start;
    gap: 2px;
  }
}
</style>
