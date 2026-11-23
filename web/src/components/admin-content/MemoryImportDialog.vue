<template>
  <v-dialog v-model="importOpen" max-width="560" persistent>
    <v-card class="import-card">
      <v-card-title class="import-title">导入 JSON 快照</v-card-title>
      <v-card-text>
        <v-alert type="info" variant="tonal" density="compact" class="mb-3">
          快照包含记忆与笔记；导入按内容去重，可重复执行。加密用户需确认后才会解密导入。
        </v-alert>
        <v-alert v-if="importError" type="error" variant="tonal" density="compact" class="mb-3">
          {{ importError }}
        </v-alert>
        <v-file-input
          v-model="importFile"
          label="选择 JSON 快照"
          accept=".json,application/json"
          prepend-icon="mdi-paperclip"
          density="compact"
          show-size
          class="mb-2"
          @update:model-value="onImportFileChange"
        />
        <v-checkbox
          v-model="importDryRun"
          label="仅预检（dry-run，不写入）"
          density="compact"
          hide-details
        />
        <v-alert
          v-if="importReport"
          :type="importReport.dry_run ? 'info' : 'success'"
          variant="tonal"
          density="compact"
          class="mt-3"
          data-testid="admin-memory-import-report"
        >
          <div>
            记忆：导入 {{ importReport.memories.imported }} · 跳过 {{ importReport.memories.skipped }} ·
            失败 {{ importReport.memories.failed }}
          </div>
          <div>
            笔记：导入 {{ importReport.notes.imported }} · 跳过 {{ importReport.notes.skipped }} ·
            失败 {{ importReport.notes.failed }}
          </div>
          <div v-if="importReport.dry_run" class="mt-1">当前为预检结果，未写入任何数据。</div>
        </v-alert>
      </v-card-text>
      <v-card-actions>
        <v-spacer />
        <v-btn variant="text" :disabled="importing" @click="importOpen = false">关闭</v-btn>
        <v-btn
          color="primary"
          variant="tonal"
          :loading="importing"
          data-testid="admin-memory-import-submit"
          @click="submitImport()"
        >
          开始导入
        </v-btn>
      </v-card-actions>
    </v-card>
  </v-dialog>
</template>

<script setup lang="ts">
import { useAdminContentContext } from '@/composables/useAdminContent'

/* JSON 快照导入对话框；状态与请求见 useAdminContent。 */
const {
  importOpen,
  importFile,
  importDryRun,
  importing,
  importError,
  importReport,
  onImportFileChange,
  submitImport,
} = useAdminContentContext()
</script>

<style scoped>
.import-card {
  padding: 8px;
}

.import-title {
  font-size: 1.05rem;
  font-weight: 650;
  padding: 12px 20px 0;
}
</style>
