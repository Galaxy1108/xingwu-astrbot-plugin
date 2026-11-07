<template>
  <div>
    <PageHeader title="邀请码" description="邀请码用于注册；一次性展示完整码，请生成后立即复制保存。">
      <template #actions>
        <v-btn variant="text" prepend-icon="mdi-refresh" :loading="loading" @click="load">刷新</v-btn>
        <v-btn color="primary" variant="tonal" prepend-icon="mdi-plus" @click="openCreate">
          生成邀请码
        </v-btn>
      </template>
    </PageHeader>

    <v-alert v-if="error" type="error" variant="tonal" class="mb-4">
      <div class="alert-row">
        <span>{{ error }}</span>
        <v-btn size="small" variant="text" color="error" @click="load">重试</v-btn>
      </div>
    </v-alert>

    <v-card class="table-card">
      <div class="table-head">
        <span class="text-muted">共 {{ total }} 个邀请码</span>
        <span class="text-muted">完整邀请码仅在生成时显示一次</span>
      </div>
      <LoadingSkeleton v-if="loading && !items.length" variant="table" :rows="4" />
      <EmptyState
        v-else-if="!error && !items.length"
        icon="mdi-ticket-outline"
        title="暂无邀请码"
        description="生成邀请码后，把它发给需要注册的用户。"
        :actions="[{ label: '生成邀请码', onClick: openCreate }]"
      />
      <div v-else class="table-scroll">
        <v-table hover density="comfortable">
          <thead>
            <tr>
              <th>邀请码前缀</th>
              <th>已用 / 上限</th>
              <th>状态</th>
              <th>备注</th>
              <th>过期时间</th>
              <th>创建时间</th>
              <th class="text-right">操作</th>
            </tr>
          </thead>
          <tbody>
            <tr v-for="invite in items" :key="invite.code_hint + invite.created_at">
              <td class="text-mono">{{ invite.code_hint }}…</td>
              <td>{{ invite.used_count }} / {{ invite.max_uses }}</td>
              <td><v-chip size="x-small" variant="tonal" :color="statusColor(invite.status)">{{ statusLabel(invite.status) }}</v-chip></td>
              <td>{{ invite.note || '—' }}</td>
              <td class="nowrap">{{ formatDateTime(invite.expires_at) }}</td>
              <td class="nowrap">{{ formatDateTime(invite.created_at) }}</td>
              <td class="text-right">
                <v-btn
                  size="small"
                  variant="text"
                  color="error"
                  :disabled="invite.status === 'revoked'"
                  @click="askRevoke(invite)"
                >撤销</v-btn>
              </td>
            </tr>
          </tbody>
        </v-table>
      </div>
    </v-card>

    <v-dialog v-model="createOpen" max-width="520" persistent>
      <v-card>
        <v-card-title class="dialog-title">生成邀请码</v-card-title>
        <v-card-text>
          <v-alert v-if="createError" type="error" variant="tonal" density="compact" class="mb-3">
            {{ createError }}
          </v-alert>
          <v-row dense>
            <v-col cols="12" sm="6">
              <v-text-field v-model.number="form.max_uses" label="可用次数" type="number" min="1" max="100" />
            </v-col>
            <v-col cols="12" sm="6">
              <v-text-field v-model.number="form.ttl_hours" label="有效小时" type="number" min="1" max="720" />
            </v-col>
          </v-row>
          <v-text-field v-model="form.note" label="备注（可选）" class="mt-2" />
          <v-alert type="warning" variant="tonal" density="compact" class="mt-2">
            完整邀请码只会显示一次，关闭后无法再次查看。
          </v-alert>
        </v-card-text>
        <v-card-actions>
          <v-spacer />
          <v-btn variant="text" @click="createOpen = false">取消</v-btn>
          <v-btn color="primary" variant="tonal" :loading="creating" @click="create">生成</v-btn>
        </v-card-actions>
      </v-card>
    </v-dialog>

    <v-dialog v-model="resultOpen" max-width="520">
      <v-card>
        <v-card-title class="dialog-title">邀请码已生成</v-card-title>
        <v-card-text>
          <p class="text-muted mb-2">复制并发送给用户；此码只展示一次。</p>
          <div class="code-box">
            <code>{{ generatedCode }}</code>
            <v-btn size="small" variant="tonal" prepend-icon="mdi-content-copy" @click="copyCode">复制</v-btn>
          </div>
          <v-alert type="warning" variant="tonal" density="compact" class="mt-3">
            关闭弹窗后将无法再次查看完整邀请码。
          </v-alert>
        </v-card-text>
        <v-card-actions>
          <v-spacer />
          <v-btn color="primary" variant="tonal" @click="resultOpen = false">我已保存</v-btn>
        </v-card-actions>
      </v-card>
    </v-dialog>

    <ConfirmDialog
      v-model="revokeOpen"
      title="撤销邀请码？"
      :message="`撤销后，前缀 ${revokeTarget?.code_hint || ''}… 的邀请码将不能再注册。`"
      confirm-text="撤销"
      danger
      @confirm="revoke"
    />
  </div>
</template>

<script setup lang="ts">
import { onMounted, reactive, ref } from 'vue'
import PageHeader from '@/components/PageHeader.vue'
import EmptyState from '@/components/EmptyState.vue'
import LoadingSkeleton from '@/components/LoadingSkeleton.vue'
import ConfirmDialog from '@/components/ConfirmDialog.vue'
import { createAdminInvite, listAdminInvites, revokeAdminInvite } from '@/api/admin'
import type { AdminInvite } from '@/types'
import { formatDateTime } from '@/utils/format'
import { useUiStore } from '@/stores/ui'

const ui = useUiStore()
const items = ref<AdminInvite[]>([])
const total = ref(0)
const loading = ref(false)
const error = ref('')
const createOpen = ref(false)
const creating = ref(false)
const createError = ref('')
const resultOpen = ref(false)
const generatedCode = ref('')
const revokeOpen = ref(false)
const revokeTarget = ref<AdminInvite | null>(null)
const form = reactive({ max_uses: 1, ttl_hours: 72, note: '' })

onMounted(load)

async function load(): Promise<void> {
  loading.value = true
  error.value = ''
  try {
    const result = await listAdminInvites()
    items.value = result.items ?? []
    total.value = result.total ?? 0
  } catch (err) {
    error.value = (err as Error).message || '加载邀请码失败'
  } finally {
    loading.value = false
  }
}

function openCreate(): void {
  createError.value = ''
  createOpen.value = true
}

async function create(): Promise<void> {
  creating.value = true
  createError.value = ''
  try {
    const result = await createAdminInvite({ ...form })
    generatedCode.value = result.invite.code
    createOpen.value = false
    resultOpen.value = true
    await load()
  } catch (err) {
    createError.value = (err as Error).message || '生成失败'
  } finally {
    creating.value = false
  }
}

async function copyCode(): Promise<void> {
  try {
    await navigator.clipboard.writeText(generatedCode.value)
    ui.notify('邀请码已复制', 'success')
  } catch {
    ui.notifyError('复制失败，请手动选择复制')
  }
}

function askRevoke(invite: AdminInvite): void {
  revokeTarget.value = invite
  revokeOpen.value = true
}

async function revoke(): Promise<void> {
  if (!revokeTarget.value) return
  try {
    await revokeAdminInvite(revokeTarget.value.code_hint)
    revokeOpen.value = false
    ui.notify('邀请码已撤销', 'success')
    await load()
  } catch (err) {
    ui.notifyError(err instanceof Error ? err.message : String(err))
  }
}

function statusLabel(status: AdminInvite['status']): string {
  return { active: '可用', used: '已用完', expired: '已过期', revoked: '已撤销' }[status] ?? status
}

function statusColor(status: AdminInvite['status']): string {
  return { active: 'success', used: 'default', expired: 'warning', revoked: 'error' }[status] ?? 'default'
}
</script>

<style scoped>
.table-head {
  display: flex;
  justify-content: space-between;
  gap: 12px;
  flex-wrap: wrap;
  padding: 16px 20px 4px;
  font-size: 12.5px;
}
.table-scroll {
  overflow-x: auto;
}
.code-box {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
  padding: 14px 16px;
  border: 1px dashed var(--console-border);
  border-radius: 8px;
  background: var(--console-surface-variant);
  font-size: 16px;
  letter-spacing: 1px;
  word-break: break-all;
}
</style>
