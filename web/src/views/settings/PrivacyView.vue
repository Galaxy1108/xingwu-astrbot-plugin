<template>
  <div>
    <PageHeader
      title="隐私与加密"
      description="查看当前账号的加密状态。M1 阶段只读展示，切换能力将在 M3 开放。"
    >
      <template #actions>
        <v-btn variant="tonal" prepend-icon="mdi-file-eye-outline" to="/access-log">访问记录</v-btn>
        <v-btn variant="text" prepend-icon="mdi-refresh" :loading="loading" @click="load">刷新</v-btn>
      </template>
    </PageHeader>

    <v-alert v-if="error" type="error" variant="tonal" class="mb-4">
      <div class="alert-row">
        <span>{{ error }}</span>
        <v-btn size="small" variant="text" color="error" @click="load">重试</v-btn>
      </div>
    </v-alert>

    <LoadingSkeleton v-if="loading && !encryption.status" variant="detail" />

    <template v-else>
      <EncryptionSwitch
        :enabled="encryption.enabled"
        :state="encryption.state"
        :done="encryption.status?.done ?? 0"
        :total="encryption.status?.total ?? 0"
        :eta="encryption.status?.eta ?? null"
        :readonly="false"
        @toggle="onToggle"
      />

      <v-card class="privacy-info mt-4">
        <h2 class="section-title">关于加密</h2>
        <ul class="privacy-list">
          <li>对话与记忆使用租户密钥加密后落盘，密钥由平台根密钥信封加密。</li>
          <li>管理员直接查看明文内容属于受审计操作，会写入访问记录。</li>
          <li>关闭加密后数据将以明文存储，存在被管理员直接查看的风险。</li>
          <li>关闭操作需要逐条确认后果，并在输入框中输入「确认解密」。</li>
        </ul>
        <v-btn variant="text" color="primary" prepend-icon="mdi-arrow-left" to="/">返回总览</v-btn>
      </v-card>
    </template>

    <ConfirmDialog
      v-model="confirmOpen"
      title="关闭加密并解密全部数据？"
      :message="confirmMessage"
      confirm-text="确认解密"
      danger
      type-to-confirm="确认解密"
      @confirm="onConfirm"
      @cancel="confirmOpen = false"
    >
      <div class="confirm-list">
        <p>关闭后：</p>
        <ol>
          <li>新产生的对话与记忆将以明文写入磁盘。</li>
          <li>已有密文会在后台逐条解密，期间服务可用但性能下降。</li>
          <li>管理员可在不额外授权的情况下查看内容（访问仍会留痕）。</li>
          <li>该操作不可自动回滚，重新开启需要再次加密全量数据。</li>
        </ol>
        <p class="text-muted">M1 为只读展示：确认后不会发起真实切换请求。</p>
      </div>
    </ConfirmDialog>
  </div>
</template>

<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import PageHeader from '@/components/PageHeader.vue'
import EncryptionSwitch from '@/components/EncryptionSwitch.vue'
import ConfirmDialog from '@/components/ConfirmDialog.vue'
import LoadingSkeleton from '@/components/LoadingSkeleton.vue'
import { useEncryptionStore } from '@/stores/encryption'
import { useUiStore } from '@/stores/ui'
import { errorMessage } from '@/utils/errors'

const encryption = useEncryptionStore()
const ui = useUiStore()

const loading = ref(false)
const error = ref('')
const confirmOpen = ref(false)

const confirmMessage = computed(() =>
  encryption.isPlaintext
    ? '当前已是明文存储；如需重新开启加密，请等待 M3。'
    : '该操作会逐条解密你的对话与记忆，并可能影响正在进行中的会话。',
)

onMounted(() => {
  void load()
})

async function load(): Promise<void> {
  loading.value = true
  error.value = ''
  try {
    await encryption.fetchStatus()
  } catch (err) {
    error.value = errorMessage(err, '加载加密状态失败')
  } finally {
    loading.value = false
  }
}

function onToggle(): void {
  confirmOpen.value = true
}

function onConfirm(): void {
  confirmOpen.value = false
  ui.notify('M1 阶段加密切换暂未开放，将在 M3 提供（本次未提交任何变更）。', 'info', 6000)
}
</script>

<style scoped>
.alert-row {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
  flex-wrap: wrap;
}

.privacy-info {
  padding: 20px;
}

.privacy-list {
  margin: 0 0 16px;
  padding-left: 20px;
  color: var(--console-text-muted);
  font-size: 0.85rem;
  line-height: 1.8;
}

.confirm-list {
  color: var(--console-text-muted);
  font-size: 0.85rem;
  line-height: 1.7;
}

.confirm-list p {
  margin: 0 0 6px;
}

.confirm-list ol {
  margin: 0 0 10px;
  padding-left: 20px;
}
</style>
