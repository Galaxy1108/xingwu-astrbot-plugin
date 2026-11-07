<template>
  <div>
    <PageHeader
      title="兑换码"
      description="生成内测兑换码并管理状态；用户可在「额度与账单」页兑换点数。旧的手动充值单仍可在 /admin/orders 直达查看。"
    >
      <template #actions>
        <v-btn variant="text" prepend-icon="mdi-refresh" :loading="loading" @click="load">刷新</v-btn>
        <v-btn color="primary" variant="tonal" prepend-icon="mdi-plus" data-testid="redemption-create" @click="openCreate">
          生成兑换码
        </v-btn>
      </template>
    </PageHeader>

    <v-alert type="info" variant="tonal" density="compact" class="mb-4" icon="mdi-ticket-percent-outline">
      兑换码一次最多可生成一批；每个码有独立可用次数与有效期。禁用后用户不能继续兑换，已兑换点数不受影响。
    </v-alert>

    <v-alert v-if="error" type="error" variant="tonal" class="mb-4">
      <div class="alert-row">
        <span>{{ error }}</span>
        <v-btn size="small" variant="text" color="error" @click="load">重试</v-btn>
      </div>
    </v-alert>

    <LoadingSkeleton v-if="loading && !codes.length" variant="table" :rows="5" />

    <EmptyState
      v-else-if="!error && codes.length === 0"
      icon="mdi-ticket-percent-outline"
      title="还没有兑换码"
      description="生成一批兑换码后，管理员可直接发给内测用户。"
      :actions="[{ label: '生成兑换码', onClick: openCreate }]"
    />

    <v-card v-else-if="codes.length" class="table-card">
      <div class="table-head">
        <span class="text-muted table-count">共 {{ total }} 个兑换码 · 当前第 {{ page }} 页</span>
        <span class="text-muted table-hint">兑换码只展示明文一次，请生成后及时复制</span>
      </div>
      <div class="table-scroll">
        <v-table hover class="codes-table">
          <thead>
            <tr>
              <th>兑换码</th>
              <th>点数</th>
              <th>备注</th>
              <th>已用 / 上限</th>
              <th>过期时间</th>
              <th>状态</th>
              <th class="text-right">操作</th>
            </tr>
          </thead>
          <tbody>
            <tr v-for="item in codes" :key="item.code" data-testid="redemption-row">
              <td class="code-cell">
                <span class="text-mono code-text">{{ item.code }}</span>
                <v-btn
                  icon
                  size="small"
                  variant="text"
                  :aria-label="copiedCode === item.code ? '已复制' : '复制兑换码'"
                  :title="copiedCode === item.code ? '已复制' : '复制兑换码'"
                  @click="copy(item.code)"
                >
                  <v-icon size="16">{{ copiedCode === item.code ? 'mdi-check' : 'mdi-content-copy' }}</v-icon>
                </v-btn>
              </td>
              <td class="nowrap">{{ formatNumber(item.credits) }} 点</td>
              <td class="note-cell" :title="item.note || ''">{{ item.note || '—' }}</td>
              <td class="nowrap">{{ item.used_count ?? 0 }} / {{ item.max_uses ?? 1 }}</td>
              <td class="nowrap">{{ item.expires_at ? formatDateTime(item.expires_at) : '永久' }}</td>
              <td>
                <v-chip :color="statusMeta(item).color" variant="tonal" size="small">
                  {{ statusMeta(item).label }}
                </v-chip>
              </td>
              <td class="text-right nowrap">
                <v-btn
                  v-if="statusMeta(item).key === 'active'"
                  size="small"
                  variant="text"
                  color="error"
                  :loading="disablingCode === item.code"
                  data-testid="redemption-disable"
                  @click="disable(item)"
                >
                  禁用
                </v-btn>
                <span v-else class="text-muted">—</span>
              </td>
            </tr>
          </tbody>
        </v-table>
      </div>
      <div v-if="total > pageSize" class="pager">
        <v-pagination
          :model-value="page"
          :length="pageCount"
          :total-visible="5"
          density="comfortable"
          @update:model-value="onPage"
        />
      </div>
    </v-card>

    <!-- 生成表单 -->
    <v-dialog v-model="createOpen" max-width="560" persistent>
      <v-card class="dialog-card">
        <v-card-title class="dialog-title">生成兑换码</v-card-title>
        <v-card-text>
          <v-alert v-if="createError" type="error" variant="tonal" density="compact" class="mb-3">
            {{ createError }}
          </v-alert>
          <v-text-field
            v-model="form.credits"
            label="点数（必填，正整数）"
            type="number"
            min="1"
            :error-messages="formErrors.credits"
            class="mb-2"
            data-testid="redemption-credits"
          />
          <v-text-field v-model.trim="form.note" label="备注（如：内测赠送）" class="mb-2" />
          <v-row dense>
            <v-col cols="12" sm="6">
              <v-text-field
                v-model="form.quantity"
                label="生成数量"
                type="number"
                min="1"
                max="100"
                :error-messages="formErrors.quantity"
              />
            </v-col>
            <v-col cols="12" sm="6">
              <v-text-field
                v-model="form.max_uses"
                label="单码可用次数"
                type="number"
                min="1"
                :error-messages="formErrors.max_uses"
              />
            </v-col>
          </v-row>
          <v-text-field
            v-model="form.expires_at"
            label="有效期"
            type="date"
            hint="留空永久有效"
            persistent-hint
          />
        </v-card-text>
        <v-card-actions>
          <v-spacer />
          <v-btn variant="text" :disabled="creating" @click="createOpen = false">取消</v-btn>
          <v-btn
            color="primary"
            variant="tonal"
            :loading="creating"
            data-testid="redemption-submit"
            @click="submitCreate"
          >
            生成
          </v-btn>
        </v-card-actions>
      </v-card>
    </v-dialog>

    <!-- 生成结果 -->
    <v-dialog v-model="resultOpen" max-width="560">
      <v-card class="dialog-card">
        <v-card-title class="dialog-title">兑换码已生成</v-card-title>
        <v-card-text>
          <v-alert type="warning" variant="tonal" density="compact" class="mb-3">
            兑换码只在此处显示明文，请立即复制保存。
          </v-alert>
          <div v-if="generatedCodes.length" class="generated-list" data-testid="redemption-generated">
            <div v-for="code in generatedCodes" :key="code" class="generated-item">
              <span class="text-mono">{{ code }}</span>
              <v-btn icon size="small" variant="text" aria-label="复制兑换码" @click="copy(code)">
                <v-icon size="16">{{ copiedCode === code ? 'mdi-check' : 'mdi-content-copy' }}</v-icon>
              </v-btn>
            </div>
          </div>
          <v-alert v-else type="info" variant="tonal" density="compact">
            已创建成功，但后端未返回明文兑换码；请刷新列表查看。
          </v-alert>
        </v-card-text>
        <v-card-actions>
          <v-btn variant="text" prepend-icon="mdi-content-copy" :disabled="!generatedCodes.length" @click="copyAll">
            全部复制
          </v-btn>
          <v-spacer />
          <v-btn color="primary" variant="tonal" @click="resultOpen = false">关闭</v-btn>
        </v-card-actions>
      </v-card>
    </v-dialog>
  </div>
</template>

<script setup lang="ts">
import { computed, reactive, ref, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import PageHeader from '@/components/PageHeader.vue'
import EmptyState from '@/components/EmptyState.vue'
import LoadingSkeleton from '@/components/LoadingSkeleton.vue'
import { useUiStore } from '@/stores/ui'
import { useClipboard } from '@/composables/useClipboard'
import {
  createRedemptionCodes,
  disableRedemptionCode,
  listRedemptionCodes,
} from '@/api/admin'
import { toApiError } from '@/api/client'
import type { RedemptionCode } from '@/types'
import { errorMessage } from '@/utils/errors'
import { formatDateTime, formatNumber } from '@/utils/format'

const route = useRoute()
const router = useRouter()
const ui = useUiStore()
const { copied, copy: copyText } = useClipboard()

const codes = ref<RedemptionCode[]>([])
const total = ref(0)
const page = ref(1)
const pageSize = ref(20)
const loading = ref(false)
const error = ref('')
const copiedCode = ref('')

const createOpen = ref(false)
const creating = ref(false)
const createError = ref('')
const form = reactive({
  credits: '',
  note: '',
  quantity: '1',
  max_uses: '1',
  expires_at: '',
})
const formErrors = reactive<Record<string, string | undefined>>({})

const resultOpen = ref(false)
const generatedCodes = ref<string[]>([])
const disablingCode = ref('')

const pageCount = computed(() => Math.max(1, Math.ceil(total.value / Math.max(1, pageSize.value))))

watch(
  () => route.query,
  () => {
    void load()
  },
  { immediate: true },
)

function stringQuery(value: unknown): string {
  const raw = Array.isArray(value) ? value[0] : value
  return typeof raw === 'string' ? raw : ''
}

function readPage(): number {
  const parsed = Number(stringQuery(route.query.page))
  return Number.isFinite(parsed) && parsed >= 1 ? Math.floor(parsed) : 1
}

async function load(): Promise<void> {
  loading.value = true
  error.value = ''
  page.value = readPage()
  try {
    const result = await listRedemptionCodes({ page: page.value, page_size: pageSize.value })
    codes.value = result.items ?? []
    total.value = result.total ?? 0
    page.value = result.page ?? page.value
    pageSize.value = result.page_size ?? pageSize.value
  } catch (err) {
    const apiError = toApiError(err)
    error.value =
      apiError.status === 404 || apiError.status === 405 || apiError.status === 501
        ? '兑换码接口尚未就绪，请稍后刷新重试。'
        : errorMessage(apiError, '加载兑换码失败')
  } finally {
    loading.value = false
  }
}

async function onPage(next: number): Promise<void> {
  await router.replace({ query: { ...route.query, page: String(next) } })
}

function openCreate(): void {
  form.credits = ''
  form.note = ''
  form.quantity = '1'
  form.max_uses = '1'
  form.expires_at = ''
  clearErrors()
  createError.value = ''
  createOpen.value = true
}

function clearErrors(): void {
  formErrors.credits = undefined
  formErrors.quantity = undefined
  formErrors.max_uses = undefined
}

function validate(): boolean {
  clearErrors()
  const credits = Number(form.credits)
  if (!form.credits || !Number.isInteger(credits) || credits <= 0) {
    formErrors.credits = '点数必须是正整数'
  }
  const quantity = Number(form.quantity)
  if (!Number.isInteger(quantity) || quantity < 1 || quantity > 100) {
    formErrors.quantity = '数量必须是 1–100 的整数'
  }
  const maxUses = Number(form.max_uses)
  if (!Number.isInteger(maxUses) || maxUses < 1) {
    formErrors.max_uses = '可用次数必须是正整数'
  }
  return !Object.values(formErrors).some(Boolean)
}

async function submitCreate(): Promise<void> {
  createError.value = ''
  if (!validate()) return
  creating.value = true
  try {
    const expires = form.expires_at
      ? Math.floor(new Date(`${form.expires_at}T23:59:59`).getTime() / 1000)
      : undefined
    const result = await createRedemptionCodes({
      credits: Number(form.credits),
      note: form.note.trim() || undefined,
      quantity: Number(form.quantity),
      max_uses: Number(form.max_uses),
      expires_at: expires,
    })
    generatedCodes.value = (result.codes ?? [])
      .map((item) => (typeof item === 'string' ? item : item.code))
      .filter(Boolean)
    createOpen.value = false
    resultOpen.value = true
    ui.notify(`已生成 ${generatedCodes.value.length || result.count || 0} 个兑换码`, 'success')
    await load()
  } catch (err) {
    const apiError = toApiError(err)
    createError.value =
      apiError.status === 404 || apiError.status === 405 || apiError.status === 501
        ? '兑换码接口尚未就绪，暂时无法生成。'
        : errorMessage(apiError, '生成兑换码失败')
  } finally {
    creating.value = false
  }
}

function statusMeta(item: RedemptionCode): {
  key: 'active' | 'used' | 'expired' | 'disabled'
  label: string
  color: string
} {
  if (item.disabled || item.status === 'disabled' || item.status === 'revoked' || item.revoked_at) {
    return { key: 'disabled', label: '已禁用', color: 'default' }
  }
  if (item.status === 'expired' || (item.expires_at && item.expires_at * 1000 < Date.now())) {
    return { key: 'expired', label: '已过期', color: 'warning' }
  }
  const maxUses = item.max_uses ?? 1
  if ((item.used_count ?? 0) >= maxUses) {
    return { key: 'used', label: '已用完', color: 'info' }
  }
  return { key: 'active', label: '可用', color: 'success' }
}

async function disable(item: RedemptionCode): Promise<void> {
  disablingCode.value = item.code
  try {
    await disableRedemptionCode(item.code)
    ui.notify('兑换码已禁用', 'success')
    await load()
  } catch (err) {
    const apiError = toApiError(err)
    ui.notifyError(
      apiError.status === 404 || apiError.status === 405 || apiError.status === 501
        ? '禁用接口尚未就绪，请稍后重试。'
        : errorMessage(apiError, '禁用失败'),
    )
  } finally {
    disablingCode.value = ''
  }
}

async function copy(code: string): Promise<void> {
  await copyText(code)
  copiedCode.value = code
  ui.notify('兑换码已复制', 'success')
  setTimeout(() => {
    if (copiedCode.value === code) copiedCode.value = ''
  }, 2000)
}

async function copyAll(): Promise<void> {
  if (!generatedCodes.value.length) return
  await copyText(generatedCodes.value.join('\n'))
  ui.notify(`已复制 ${generatedCodes.value.length} 个兑换码`, 'success')
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

.table-hint {
  font-size: 0.76rem;
}

.table-scroll {
  overflow-x: auto;
}

.codes-table {
  min-width: 920px;
}

.codes-table :deep(th) {
  white-space: nowrap;
}

.code-cell {
  white-space: nowrap;
  font-weight: 600;
}

.code-text {
  margin-right: 2px;
}

.note-cell {
  max-width: 220px;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
  color: var(--console-text-muted);
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

.generated-list {
  max-height: 280px;
  overflow-y: auto;
  border: 1px solid var(--console-border);
  border-radius: 8px;
}

.generated-item {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 10px;
  padding: 6px 12px;
  border-bottom: 1px solid var(--console-border);
  font-size: 0.85rem;
}

.generated-item:last-child {
  border-bottom: none;
}

@media (max-width: 599px) {
  .table-head {
    flex-direction: column;
    align-items: flex-start;
    gap: 2px;
  }
}
</style>
