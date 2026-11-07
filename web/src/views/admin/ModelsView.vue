<template>
  <div>
    <PageHeader
      title="模型与定价"
      description="维护上游模型接入与点数定价；定价用于 M4 用量计费，当前不接自动充值。"
    >
      <template #actions>
        <v-btn variant="text" prepend-icon="mdi-refresh" :loading="loading" @click="load">
          刷新
        </v-btn>
        <v-btn color="primary" prepend-icon="mdi-plus" data-testid="model-create" @click="openCreate">
          新建模型
        </v-btn>
      </template>
    </PageHeader>

    <v-alert type="info" variant="tonal" density="compact" icon="mdi-cash-multiple" class="mb-4">
      单价单位：<strong>点数 / 1k tokens</strong>（输入与输出分别计价）。删除模型等于软禁用，
      不会删除历史定价与用量记录；充值仍由「手动充值」维护，暂不接自动充值。
    </v-alert>

    <v-alert v-if="loadError" type="error" variant="tonal" class="mb-4">
      <div class="alert-row">
        <span>{{ loadError }}</span>
        <v-btn size="small" variant="text" color="error" @click="load">重试</v-btn>
      </div>
    </v-alert>

    <LoadingSkeleton v-if="loading && !models.length" variant="table" :rows="5" />

    <EmptyState
      v-else-if="!loadError && models.length === 0"
      icon="mdi-robot-happy-outline"
      title="还没有模型配置"
      description="添加第一个模型与定价后，模板即可引用它；用量计费将在 M4 接入。"
      :actions="[{ label: '新建模型', onClick: openCreate }]"
    />

    <v-card v-else-if="models.length" class="table-card">
      <div class="table-scroll">
        <v-table hover>
          <thead>
            <tr>
              <th>名称</th>
              <th>提供商</th>
              <th>模型</th>
              <th>单价（点 / 1k tokens）</th>
              <th>状态</th>
              <th>更新时间</th>
              <th class="text-right">操作</th>
            </tr>
          </thead>
          <tbody>
            <tr v-for="model in models" :key="model.id" data-testid="model-row">
              <td>
                <div class="model-name">
                  {{ model.name }}
                  <v-icon v-if="model.has_api_key || model.api_key" size="14" color="success" title="API Key 已配置">
                    mdi-key-variant
                  </v-icon>
                </div>
                <div class="text-mono text-muted model-id">{{ model.id }}</div>
              </td>
              <td class="nowrap">{{ providerLabel(model.provider) }}</td>
              <td>
                <div>{{ model.model || '—' }}</div>
                <div v-if="model.base_url" class="text-muted model-url" :title="model.base_url">
                  {{ model.base_url }}
                </div>
              </td>
              <td class="nowrap price-cell">
                <span>入 {{ formatPoints(model.points_per_1k_input) }}</span>
                <span class="price-sep">/</span>
                <span>出 {{ formatPoints(model.points_per_1k_output) }}</span>
                <div class="text-muted currency">{{ model.currency || 'CNY' }}</div>
              </td>
              <td>
                <v-chip :color="model.enabled ? 'success' : 'default'" variant="tonal" size="small">
                  {{ model.enabled ? '已启用' : '已禁用' }}
                </v-chip>
              </td>
              <td class="nowrap">{{ formatDateTime(model.updated_at) }}</td>
              <td class="text-right nowrap">
                <v-btn size="small" variant="text" data-testid="model-edit" @click="openEdit(model)">
                  编辑
                </v-btn>
                <v-btn
                  size="small"
                  variant="text"
                  :color="model.enabled ? 'warning' : 'success'"
                  @click="toggleEnabled(model)"
                >
                  {{ model.enabled ? '禁用' : '启用' }}
                </v-btn>
                <v-btn
                  size="small"
                  variant="text"
                  color="error"
                  data-testid="model-delete"
                  @click="askDelete(model)"
                >
                  删除
                </v-btn>
              </td>
            </tr>
          </tbody>
        </v-table>
      </div>
      <div class="table-foot text-muted">
        共 {{ models.length }} 个模型 · 删除为软禁用（enabled=false）
      </div>
    </v-card>

    <v-dialog v-model="editorOpen" max-width="720" scrollable persistent>
      <v-card class="editor-card">
        <v-card-title class="editor-title">
          {{ editingId ? '编辑模型' : '新建模型' }}
        </v-card-title>
        <v-card-text class="editor-body">
          <v-alert v-if="submitError" type="error" variant="tonal" density="compact" class="mb-3">
            {{ submitError }}
          </v-alert>

          <v-text-field
            v-model.trim="form.name"
            label="名称"
            counter="80"
            maxlength="80"
            :error-messages="fieldErrors.name"
            class="mb-2"
          />
          <v-row dense>
            <v-col cols="12" sm="6">
              <v-select
                v-model="form.provider"
                :items="MODEL_PROVIDERS"
                label="提供商"
                :error-messages="fieldErrors.provider"
              />
            </v-col>
            <v-col cols="12" sm="6">
              <v-select
                v-model="form.currency"
                :items="MODEL_CURRENCIES"
                label="币种"
                :error-messages="fieldErrors.currency"
              />
            </v-col>
          </v-row>
          <v-text-field
            v-model.trim="form.base_url"
            label="Base URL"
            placeholder="https://api.openai.com/v1"
            :error-messages="fieldErrors.base_url"
            class="mb-2"
          />
          <v-text-field
            v-model.trim="form.model"
            label="上游模型标识（model）"
            placeholder="gpt-4o-mini"
            :error-messages="fieldErrors.model"
            class="mb-2"
          />
          <v-text-field
            v-model="form.api_key"
            label="API Key"
            type="password"
            autocomplete="new-password"
            :placeholder="form.has_api_key ? '已配置（留空不修改）' : '未配置'"
            :error-messages="fieldErrors.api_key"
            class="mb-1"
          />
          <v-checkbox
            v-if="form.has_api_key"
            v-model="form.clear_api_key"
            label="清除已配置的 API Key"
            density="compact"
            hide-details
            color="error"
            class="mb-2"
          />
          <v-row dense>
            <v-col cols="12" sm="6">
              <v-text-field
                v-model.number="form.points_per_1k_input"
                label="输入单价（点 / 1k tokens）"
                type="number"
                min="0"
                step="0.01"
                :error-messages="fieldErrors.points_per_1k_input"
              />
            </v-col>
            <v-col cols="12" sm="6">
              <v-text-field
                v-model.number="form.points_per_1k_output"
                label="输出单价（点 / 1k tokens）"
                type="number"
                min="0"
                step="0.01"
                :error-messages="fieldErrors.points_per_1k_output"
              />
            </v-col>
          </v-row>
          <v-textarea v-model.trim="form.note" label="备注（可选）" rows="2" auto-grow class="mt-2" />
          <v-switch v-model="form.enabled" label="启用（模板可选择该模型）" color="primary" />

          <p class="editor-hint text-muted">
            API Key 由服务端加密保存，编辑时不回显。定价用于 M4 用量计费（按 1k tokens 折算点数）。
          </p>
        </v-card-text>
        <v-card-actions>
          <v-spacer />
          <v-btn variant="text" :disabled="saving" @click="editorOpen = false">取消</v-btn>
          <v-btn color="primary" :loading="saving" data-testid="model-save" @click="submit">
            {{ editingId ? '保存' : '创建' }}
          </v-btn>
        </v-card-actions>
      </v-card>
    </v-dialog>

    <ConfirmDialog
      v-model="deleteOpen"
      :title="`禁用模型「${deleteTarget?.name || ''}」？`"
      message="删除为软禁用：模型将从模板可选列表中移除，但历史定价与用量记录保留。已引用该模型的模板不会被改写。"
      confirm-text="禁用模型"
      danger
      :loading="deleting"
      @confirm="confirmDelete"
      @cancel="deleteOpen = false"
    />
  </div>
</template>

<script setup lang="ts">
import { onMounted, reactive, ref } from 'vue'
import PageHeader from '@/components/PageHeader.vue'
import EmptyState from '@/components/EmptyState.vue'
import LoadingSkeleton from '@/components/LoadingSkeleton.vue'
import ConfirmDialog from '@/components/ConfirmDialog.vue'
import { useUiStore } from '@/stores/ui'
import { isApiError } from '@/api/client'
import {
  createAdminModel,
  deleteAdminModel,
  listAdminModels,
  updateAdminModel,
} from '@/api/admin'
import { errorMessage, fieldError } from '@/utils/errors'
import { formatDateTime } from '@/utils/format'
import {
  buildModelPayload,
  emptyModelForm,
  formatPoints,
  MODEL_CURRENCIES,
  MODEL_PROVIDERS,
  modelFormFrom,
  normalizeModelList,
  providerLabel,
  validateModelForm,
  type ModelFormState,
} from '@/utils/modelProfiles'
import type { ModelProfile } from '@/types'

const ui = useUiStore()

const models = ref<ModelProfile[]>([])
const loading = ref(false)
const loadError = ref('')

const editorOpen = ref(false)
const editingId = ref('')
const saving = ref(false)
const submitError = ref('')
const fieldErrors = reactive<Record<string, string>>({})
const form = reactive<ModelFormState>(emptyModelForm())

const deleteOpen = ref(false)
const deleteTarget = ref<ModelProfile | null>(null)
const deleting = ref(false)

function friendlyError(error: unknown, fallback: string): string {
  if (isApiError(error) && (error.status === 404 || error.status === 501)) {
    return '后端接口尚未就绪（404/501），请稍后刷新重试。'
  }
  return errorMessage(error, fallback)
}

function clearFieldErrors(): void {
  for (const key of Object.keys(fieldErrors)) delete fieldErrors[key]
}

async function load(): Promise<void> {
  loading.value = true
  loadError.value = ''
  try {
    const result = await listAdminModels()
    models.value = normalizeModelList(result)
  } catch (error) {
    loadError.value = friendlyError(error, '加载模型列表失败')
  } finally {
    loading.value = false
  }
}

function openCreate(): void {
  editingId.value = ''
  Object.assign(form, emptyModelForm())
  submitError.value = ''
  clearFieldErrors()
  editorOpen.value = true
}

function openEdit(model: ModelProfile): void {
  editingId.value = model.id
  Object.assign(form, modelFormFrom(model))
  submitError.value = ''
  clearFieldErrors()
  editorOpen.value = true
}

async function submit(): Promise<void> {
  submitError.value = ''
  clearFieldErrors()
  const errors = validateModelForm(form)
  if (Object.keys(errors).length) {
    Object.assign(fieldErrors, errors)
    return
  }

  const payload = buildModelPayload(form)
  saving.value = true
  try {
    if (editingId.value) {
      await updateAdminModel(editingId.value, payload)
      ui.notify('模型已更新', 'success')
    } else {
      await createAdminModel(payload)
      ui.notify('模型已创建', 'success')
    }
    editorOpen.value = false
    await load()
  } catch (error) {
    const serverName = fieldError(error, 'name')
    if (serverName) fieldErrors.name = serverName
    submitError.value = friendlyError(error, '保存模型失败')
  } finally {
    saving.value = false
  }
}

async function toggleEnabled(model: ModelProfile): Promise<void> {
  try {
    await updateAdminModel(model.id, { enabled: !model.enabled })
    ui.notify(model.enabled ? '模型已禁用' : '模型已启用', 'success')
    await load()
  } catch (error) {
    ui.notifyError(friendlyError(error, '更新模型状态失败'))
  }
}

function askDelete(model: ModelProfile): void {
  deleteTarget.value = model
  deleteOpen.value = true
}

async function confirmDelete(): Promise<void> {
  if (!deleteTarget.value) return
  deleting.value = true
  try {
    await deleteAdminModel(deleteTarget.value.id)
    deleteOpen.value = false
    ui.notify('模型已禁用（软删除）', 'success')
    await load()
  } catch (error) {
    deleteOpen.value = false
    ui.notifyError(friendlyError(error, '禁用模型失败'))
  } finally {
    deleting.value = false
  }
}

onMounted(() => {
  void load()
})
</script>

<style scoped>
.alert-row {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
  flex-wrap: wrap;
}

.table-card {
  padding: 4px 0;
}

.table-scroll {
  overflow-x: auto;
}

.table-foot {
  padding: 10px 16px;
  font-size: 0.76rem;
}

.model-name {
  display: flex;
  align-items: center;
  gap: 6px;
  font-weight: 600;
}

.model-id {
  font-size: 0.72rem;
  margin-top: 2px;
}

.model-url {
  max-width: 260px;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
  font-size: 0.72rem;
}

.price-cell {
  font-variant-numeric: tabular-nums;
  font-size: 0.84rem;
}

.price-sep {
  color: var(--console-border);
  margin: 0 4px;
}

.currency {
  font-size: 0.7rem;
  margin-top: 2px;
}

.nowrap {
  white-space: nowrap;
}

.editor-card {
  padding: 8px;
}

.editor-title {
  font-size: 1.05rem;
  font-weight: 650;
  padding: 12px 20px 0;
}

.editor-body {
  max-height: 68vh;
}

.editor-hint {
  margin: 4px 0 0;
  font-size: 0.74rem;
  line-height: 1.55;
}
</style>
