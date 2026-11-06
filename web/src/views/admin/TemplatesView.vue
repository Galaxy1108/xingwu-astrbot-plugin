<template>
  <div>
    <PageHeader title="模板管理" description="维护人格模板、配额与默认配置；模板是创建 Bot 时的快照来源。">
      <template #actions>
        <v-btn variant="text" prepend-icon="mdi-refresh" :loading="admin.templatesLoading" @click="load">
          刷新
        </v-btn>
        <v-btn color="primary" prepend-icon="mdi-plus" @click="openCreate">新建模板</v-btn>
      </template>
    </PageHeader>

    <v-alert v-if="admin.templatesError" type="error" variant="tonal" class="mb-4">
      <div class="alert-row">
        <span>{{ admin.templatesError.message }}</span>
        <v-btn size="small" variant="text" color="error" @click="load">重试</v-btn>
      </div>
    </v-alert>

    <LoadingSkeleton v-if="admin.templatesLoading && !admin.templates.length" variant="table" :rows="4" />

    <EmptyState
      v-else-if="!admin.templatesError && admin.templates.length === 0"
      icon="mdi-file-document-multiple-outline"
      title="还没有模板"
      description="创建第一个模板后，用户才能新建 Bot。"
      :actions="[{ label: '新建模板', onClick: openCreate }]"
    />

    <v-card v-else-if="admin.templates.length" class="table-card">
      <div class="table-scroll">
        <v-table hover>
          <thead>
            <tr>
              <th>名称</th>
              <th>描述</th>
              <th>状态</th>
              <th>配额</th>
              <th>更新时间</th>
              <th class="text-right">操作</th>
            </tr>
          </thead>
          <tbody>
            <tr v-for="template in admin.templates" :key="template.id">
              <td>
                <div class="template-name">{{ template.name }}</div>
                <div class="text-mono text-muted template-id">{{ template.id }}</div>
              </td>
              <td class="desc-cell">{{ template.description || '—' }}</td>
              <td>
                <v-chip
                  :color="template.enabled ? 'success' : 'default'"
                  variant="tonal"
                  size="small"
                >
                  {{ template.enabled ? '已上架' : '已下架' }}
                </v-chip>
              </td>
              <td class="nowrap quota-cell">
                Bot {{ template.quota?.max_bots ?? '—' }} · 记忆 {{ template.quota?.max_memories ?? '—' }}
              </td>
              <td class="nowrap">{{ formatDateTime(template.updated_at) }}</td>
              <td class="text-right nowrap">
                <v-btn size="small" variant="text" @click="openEdit(template)">编辑</v-btn>
                <v-btn
                  size="small"
                  variant="text"
                  :color="template.enabled ? 'warning' : 'success'"
                  @click="toggleEnabled(template)"
                >
                  {{ template.enabled ? '下架' : '上架' }}
                </v-btn>
                <v-btn size="small" variant="text" color="error" @click="askDelete(template)">
                  删除
                </v-btn>
              </td>
            </tr>
          </tbody>
        </v-table>
      </div>
    </v-card>

    <v-dialog v-model="editorOpen" max-width="760" scrollable persistent>
      <v-card class="editor-card">
        <v-card-title class="editor-title">
          {{ editingId ? '编辑模板' : '新建模板' }}
        </v-card-title>
        <v-card-text class="editor-body">
          <v-alert v-if="submitError" type="error" variant="tonal" density="compact" class="mb-3">
            {{ submitError }}
          </v-alert>

          <v-text-field
            v-model.trim="form.name"
            label="模板名称"
            counter="64"
            maxlength="64"
            :error-messages="nameError"
          />
          <v-text-field v-model.trim="form.description" label="描述" class="mt-3" />
          <v-textarea
            v-model="form.persona_prompt"
            label="人格提示词（persona_prompt）"
            rows="4"
            auto-grow
            hint="支持 {bot_name} 占位符"
            persistent-hint
            class="mt-3"
          />
          <v-textarea
            v-model="form.begin_dialogs"
            label="开场白（每行一条）"
            rows="3"
            auto-grow
            class="mt-3"
          />
          <v-text-field
            v-model.trim="form.user_overridable"
            label="用户可改字段（逗号分隔）"
            hint="例如 persona_prompt, begin_dialogs"
            persistent-hint
            class="mt-3"
          />

          <v-divider class="my-5" />
          <h3 class="json-title">JSON 配置</h3>

          <v-textarea
            v-model="form.config_patch"
            label="config_patch（JSON 对象）"
            rows="3"
            auto-grow
            :error-messages="jsonErrors.config_patch"
            class="mt-3"
          />
          <v-textarea
            v-model="form.memory_defaults"
            label="memory_defaults（JSON 对象）"
            rows="3"
            auto-grow
            :error-messages="jsonErrors.memory_defaults"
            class="mt-3"
          />
          <v-textarea
            v-model="form.privacy_defaults"
            label="privacy_defaults（JSON 对象）"
            rows="2"
            auto-grow
            :error-messages="jsonErrors.privacy_defaults"
            class="mt-3"
          />
          <v-textarea
            v-model="form.quota"
            label="quota（JSON 对象）"
            rows="3"
            auto-grow
            :error-messages="jsonErrors.quota"
            class="mt-3"
          />

          <v-switch v-model="form.enabled" label="上架（用户可见）" color="primary" class="mt-4" />
        </v-card-text>
        <v-card-actions>
          <v-spacer />
          <v-btn variant="text" :disabled="saving" @click="editorOpen = false">取消</v-btn>
          <v-btn color="primary" :loading="saving" @click="submit">{{ editingId ? '保存' : '创建' }}</v-btn>
        </v-card-actions>
      </v-card>
    </v-dialog>

    <ConfirmDialog
      v-model="deleteOpen"
      :title="`下架并删除模板「${deleteTarget?.name || ''}」？`"
      message="模板将被软删除（enabled=false），已创建的 Bot 不受影响，但用户不能再基于该模板新建 Bot。"
      confirm-text="删除模板"
      danger
      :loading="deleting"
      @confirm="confirmDelete"
      @cancel="deleteOpen = false"
    />
  </div>
</template>

<script setup lang="ts">
import { computed, onMounted, reactive, ref } from 'vue'
import PageHeader from '@/components/PageHeader.vue'
import EmptyState from '@/components/EmptyState.vue'
import LoadingSkeleton from '@/components/LoadingSkeleton.vue'
import ConfirmDialog from '@/components/ConfirmDialog.vue'
import { useAdminStore } from '@/stores/admin'
import { useUiStore } from '@/stores/ui'
import { errorMessage, fieldError } from '@/utils/errors'
import { formatDateTime } from '@/utils/format'
import type { MemoryDefaults, PrivacyDefaults, Quota, Template, TemplateInput } from '@/types'

const admin = useAdminStore()
const ui = useUiStore()

const editorOpen = ref(false)
const editingId = ref('')
const saving = ref(false)
const submitError = ref('')
const nameError = ref('')
const jsonErrors = reactive<Record<string, string>>({
  config_patch: '',
  memory_defaults: '',
  privacy_defaults: '',
  quota: '',
})

const deleteOpen = ref(false)
const deleteTarget = ref<Template | null>(null)
const deleting = ref(false)

const emptyForm = () => ({
  name: '',
  description: '',
  persona_prompt: '',
  begin_dialogs: '',
  enabled: true,
  user_overridable: '',
  config_patch: '{}',
  memory_defaults: JSON.stringify(
    { auto: false, max_items: 2000, retention_days: 90, recall_top_k: 5 },
    null,
    2,
  ),
  privacy_defaults: JSON.stringify({ allow_disable: true }, null, 2),
  quota: JSON.stringify({ max_bots: 3, monthly_tokens: 1000000, max_memories: 2000 }, null, 2),
})

const form = reactive(emptyForm())

onMounted(() => {
  void load()
})

async function load(): Promise<void> {
  try {
    await admin.loadTemplates()
  } catch {
    /* store 已记录 */
  }
}

function openCreate(): void {
  editingId.value = ''
  Object.assign(form, emptyForm())
  clearErrors()
  editorOpen.value = true
}

function openEdit(template: Template): void {
  editingId.value = template.id
  Object.assign(form, {
    name: template.name,
    description: template.description ?? '',
    persona_prompt: template.persona_prompt ?? '',
    begin_dialogs: (template.begin_dialogs ?? []).join('\n'),
    enabled: template.enabled,
    user_overridable: (template.user_overridable ?? []).join(', '),
    config_patch: JSON.stringify(template.config_patch ?? {}, null, 2),
    memory_defaults: JSON.stringify(template.memory_defaults ?? {}, null, 2),
    privacy_defaults: JSON.stringify(template.privacy_defaults ?? {}, null, 2),
    quota: JSON.stringify(template.quota ?? {}, null, 2),
  })
  clearErrors()
  editorOpen.value = true
}

function clearErrors(): void {
  submitError.value = ''
  nameError.value = ''
  jsonErrors.config_patch = ''
  jsonErrors.memory_defaults = ''
  jsonErrors.privacy_defaults = ''
  jsonErrors.quota = ''
}

function parseJson<T>(raw: string, key: string): T | null {
  const text = raw.trim()
  if (!text) {
    jsonErrors[key] = ''
    return {} as T
  }
  try {
    const parsed = JSON.parse(text) as unknown
    if (!parsed || typeof parsed !== 'object' || Array.isArray(parsed)) {
      jsonErrors[key] = '必须是 JSON 对象'
      return null
    }
    jsonErrors[key] = ''
    return parsed as T
  } catch {
    jsonErrors[key] = '不是合法的 JSON'
    return null
  }
}

async function submit(): Promise<void> {
  clearErrors()
  const name = form.name.trim()
  if (!name) {
    nameError.value = '请输入模板名称'
    return
  }
  if (name.length > 64) {
    nameError.value = '名称最多 64 个字符'
    return
  }

  const configPatch = parseJson<Record<string, unknown>>(form.config_patch, 'config_patch')
  const memoryDefaults = parseJson<MemoryDefaults>(form.memory_defaults, 'memory_defaults')
  const privacyDefaults = parseJson<PrivacyDefaults>(form.privacy_defaults, 'privacy_defaults')
  const quota = parseJson<Quota>(form.quota, 'quota')
  if (!configPatch || !memoryDefaults || !privacyDefaults || !quota) {
    submitError.value = '请修正 JSON 配置后再提交'
    return
  }

  const payload: TemplateInput = {
    name,
    description: form.description.trim(),
    persona_prompt: form.persona_prompt,
    begin_dialogs: form.begin_dialogs
      .split('\n')
      .map((line) => line.trim())
      .filter(Boolean),
    config_patch: configPatch,
    memory_defaults: memoryDefaults,
    privacy_defaults: privacyDefaults,
    quota,
    user_overridable: form.user_overridable
      .split(',')
      .map((item) => item.trim())
      .filter(Boolean),
    enabled: form.enabled,
  }

  saving.value = true
  try {
    if (editingId.value) {
      await admin.updateTemplate(editingId.value, payload)
      ui.notify('模板已更新', 'success')
    } else {
      await admin.createTemplate(payload)
      ui.notify('模板已创建', 'success')
    }
    editorOpen.value = false
    await load()
  } catch (error) {
    if (fieldError(error, 'name')) nameError.value = errorMessage(error)
    submitError.value = errorMessage(error, '保存模板失败')
  } finally {
    saving.value = false
  }
}

async function toggleEnabled(template: Template): Promise<void> {
  try {
    await admin.updateTemplate(template.id, { enabled: !template.enabled })
    ui.notify(template.enabled ? '模板已下架' : '模板已上架', 'success')
  } catch (error) {
    ui.notifyError(errorMessage(error, '更新模板状态失败'))
  }
}

function askDelete(template: Template): void {
  deleteTarget.value = template
  deleteOpen.value = true
}

async function confirmDelete(): Promise<void> {
  if (!deleteTarget.value) return
  deleting.value = true
  try {
    await admin.removeTemplate(deleteTarget.value.id)
    deleteOpen.value = false
    ui.notify('模板已删除（软删）', 'success')
  } catch (error) {
    deleteOpen.value = false
    ui.notifyError(errorMessage(error, '删除模板失败'))
  } finally {
    deleting.value = false
  }
}

const hasTemplates = computed(() => admin.templates.length > 0)
</script>

<style scoped>
.table-card {
  padding: 4px 0;
}

.table-scroll {
  overflow-x: auto;
}

.template-name {
  font-weight: 600;
}

.template-id {
  font-size: 0.72rem;
  margin-top: 2px;
}

.desc-cell {
  max-width: 320px;
  color: var(--console-text-muted);
  font-size: 0.83rem;
}

.nowrap {
  white-space: nowrap;
}

.quota-cell {
  color: var(--console-text-muted);
  font-size: 0.8rem;
}

.alert-row {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
  flex-wrap: wrap;
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

.json-title {
  margin: 0 0 4px;
  font-size: 0.9rem;
  font-weight: 600;
}
</style>
