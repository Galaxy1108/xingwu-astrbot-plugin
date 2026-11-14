<template>
  <div>
    <PageHeader title="Agent 沙盒" description="为所有 SaaS 管理的 Bot 统一配置 Computer Use 沙盒与资源上限。">
      <template #actions>
        <v-btn variant="text" prepend-icon="mdi-refresh" :loading="loading" @click="load">刷新</v-btn>
      </template>
    </PageHeader>

    <v-alert v-if="error" type="error" variant="tonal" class="mb-4">{{ error }}</v-alert>
    <v-alert v-if="saved" type="success" variant="tonal" class="mb-4" closable @click:close="saved = ''">{{ saved }}</v-alert>

    <v-row>
      <v-col cols="12" lg="8">
        <v-card class="pa-5 mb-4">
          <div class="section-head">
            <div>
              <h2 class="section-title">运行环境</h2>
              <p class="section-sub text-muted">AstrBot Computer Use Runtime；本地沙盒依赖操作系统能力。</p>
            </div>
            <v-switch v-model="policy.enabled" color="primary" inset hide-details label="启用" />
          </div>

          <v-select
            v-model="policy.runtime"
            :items="runtimeOptions"
            item-title="title"
            item-value="value"
            label="沙盒运行方式"
            class="mt-3"
          />
          <v-select
            v-if="policy.runtime === 'sandbox'"
            v-model="policy.booter"
            :items="booterOptions"
            item-title="title"
            item-value="value"
            label="第三方沙盒后端"
            class="mt-2"
          />
          <div class="switch-row">
            <div>
              <div class="switch-title">仅管理员可使用 Computer Use</div>
              <div class="text-muted switch-desc">对应 AstrBot `computer_use_require_admin`；普通租户无法调用文件/命令工具。</div>
            </div>
            <v-switch v-model="policy.require_admin" color="primary" inset hide-details />
          </div>

          <v-alert :type="platform.available ? 'success' : 'warning'" variant="tonal" density="compact" class="mt-3">
            <strong>{{ platform.os }} · {{ platform.backend }}</strong>
            <div v-if="platform.available">
              已检测到 {{ platform.backend }}（{{ platform.binary || '可用' }}），本地受限沙盒可用。
            </div>
            <div v-else>{{ platform.hint }}</div>
          </v-alert>
        </v-card>

        <v-card class="pa-5">
          <h2 class="section-title">资源限制（本地沙盒）</h2>
          <p class="section-sub text-muted mb-4">对本地受限进程应用 CPU 时间、内存、文件大小、文件描述符与进程数上限；第三方沙盒由容器自身限制。</p>
          <v-row dense>
            <v-col cols="12" sm="6" md="4">
              <v-text-field v-model.number="policy.limits.cpu_seconds" label="CPU 时间（秒）" type="number" min="1" max="3600" />
            </v-col>
            <v-col cols="12" sm="6" md="4">
              <v-text-field v-model.number="policy.limits.memory_mb" label="内存上限（MB）" type="number" min="64" max="16384" />
            </v-col>
            <v-col cols="12" sm="6" md="4">
              <v-text-field v-model.number="policy.limits.file_size_mb" label="单文件上限（MB）" type="number" min="1" max="4096" />
            </v-col>
            <v-col cols="12" sm="6" md="4">
              <v-text-field v-model.number="policy.limits.open_files" label="打开文件数" type="number" min="16" max="8192" />
            </v-col>
            <v-col cols="12" sm="6" md="4">
              <v-text-field v-model.number="policy.limits.processes" label="进程数上限" type="number" min="8" max="4096" />
            </v-col>
          </v-row>
        </v-card>
      </v-col>

      <v-col cols="12" lg="4">
        <v-card class="pa-5">
          <h2 class="section-title">应用范围</h2>
          <ul class="tips">
            <li>保存后写入所有现有 Bot 的配置文件，并作为新 Bot 的默认策略。</li>
            <li>Linux：本地沙盒使用 bubblewrap；未安装时请选 none 或第三方沙盒。</li>
            <li>macOS：使用 Seatbelt；Windows 不支持本地进程沙盒。</li>
            <li>资源上限通过进程 rlimit 执行；仅本地沙盒生效，修改后无需重启。</li>
          </ul>
          <v-btn block color="primary" variant="tonal" size="large" :loading="saving" class="mt-4" @click="save">
            保存并应用到全部 Bot
          </v-btn>
          <div v-if="applied" class="text-caption muted mt-3">
            已更新 {{ applied.bots_updated ?? 0 }} 个 Bot 配置 · 资源限制{{ applied.limits_installed ? '已安装' : '未安装' }}
          </div>
        </v-card>
      </v-col>
    </v-row>
  </div>
</template>

<script setup lang="ts">
import { onMounted, ref } from 'vue'
import PageHeader from '@/components/PageHeader.vue'
import { getSandboxConfig, updateSandboxConfig } from '@/api/admin'
import type { SandboxConfig, SandboxPolicy, SandboxPlatform } from '@/types'
import { errorMessage } from '@/utils/errors'

const loading = ref(false)
const saving = ref(false)
const error = ref('')
const saved = ref('')
const applied = ref<SandboxConfig | null>(null)
const platform = ref<SandboxPlatform>({ os: '', backend: '', available: false, binary: '', hint: '' })
const policy = ref<SandboxPolicy>({
  enabled: false,
  runtime: 'none',
  require_admin: true,
  booter: 'docker',
  limits: { cpu_seconds: 300, memory_mb: 1024, file_size_mb: 100, open_files: 256, processes: 256 },
})
const runtimeOptions = [
  { title: '关闭 Computer Use（none）', value: 'none' },
  { title: '本地受限沙盒（local）', value: 'local' },
  { title: '第三方沙盒（sandbox）', value: 'sandbox' },
]
const booterOptions = [
  { title: 'Docker', value: 'docker' },
  { title: 'Shipyard Neo', value: 'shipyard_neo' },
  { title: 'CUA', value: 'cua' },
]

onMounted(load)

async function load(): Promise<void> {
  loading.value = true
  error.value = ''
  try {
    const result = await getSandboxConfig()
    policy.value = result.policy
    platform.value = result.platform
  } catch (err) {
    error.value = errorMessage(err, '加载沙盒配置失败')
  } finally {
    loading.value = false
  }
}

async function save(): Promise<void> {
  saving.value = true
  error.value = ''
  saved.value = ''
  try {
    const result = await updateSandboxConfig(policy.value)
    policy.value = result.policy
    platform.value = result.platform
    applied.value = result
    saved.value = '沙盒策略已保存并应用'
  } catch (err) {
    error.value = errorMessage(err, '保存沙盒配置失败')
  } finally {
    saving.value = false
  }
}
</script>

<style scoped>
.section-head {
  display: flex;
  justify-content: space-between;
  gap: 16px;
  align-items: flex-start;
}
.section-title {
  margin: 0;
  font-size: 16px;
  font-weight: 650;
}
.section-sub {
  margin: 3px 0 0;
  font-size: 12.5px;
}
.switch-row {
  display: flex;
  justify-content: space-between;
  gap: 16px;
  align-items: flex-start;
  margin-top: 18px;
  padding-top: 14px;
  border-top: 1px solid var(--console-border);
}
.switch-title {
  font-size: 14px;
  font-weight: 550;
}
.switch-desc {
  margin-top: 3px;
  font-size: 12.5px;
}
.tips {
  margin: 12px 0 0;
  padding-left: 18px;
  color: var(--console-text-muted);
  font-size: 12.5px;
  line-height: 1.75;
}
</style>
