<template>
  <div>
    <PageHeader
      title="访问记录"
      description="管理员查看你的对话或记忆时会产生访问记录。M1 阶段接口返回空列表。"
    >
      <template #actions>
        <v-btn variant="text" prepend-icon="mdi-refresh" :loading="loading" @click="load">刷新</v-btn>
        <v-btn variant="tonal" prepend-icon="mdi-shield-lock-outline" to="/settings/privacy">
          隐私与加密
        </v-btn>
      </template>
    </PageHeader>

    <v-card class="access-card">
      <AccessLogTable
        :items="items"
        :loading="loading"
        :error="error"
        :page="page"
        :page-size="pageSize"
        :total="total"
        @retry="load"
        @update:page="onPage"
      />
    </v-card>
  </div>
</template>

<script setup lang="ts">
import { onMounted, ref } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import PageHeader from '@/components/PageHeader.vue'
import AccessLogTable from '@/components/AccessLogTable.vue'
import { listAccessLog } from '@/api/privacy'
import { toApiError, type ApiError } from '@/api/client'
import type { AccessLogEntry } from '@/types'

const route = useRoute()
const router = useRouter()

const items = ref<AccessLogEntry[]>([])
const total = ref(0)
const page = ref(1)
const pageSize = ref(20)
const loading = ref(false)
const error = ref<ApiError | null>(null)

onMounted(() => {
  page.value = readPage()
  void load()
})

function readPage(): number {
  const raw = route.query.page
  const value = Array.isArray(raw) ? raw[0] : raw
  const parsed = Number(value)
  return Number.isFinite(parsed) && parsed >= 1 ? Math.floor(parsed) : 1
}

async function load(): Promise<void> {
  loading.value = true
  error.value = null
  try {
    const result = await listAccessLog(page.value, pageSize.value)
    items.value = result.items ?? []
    total.value = result.total ?? 0
    page.value = result.page ?? page.value
    pageSize.value = result.page_size ?? pageSize.value
  } catch (err) {
    error.value = toApiError(err)
  } finally {
    loading.value = false
  }
}

async function onPage(next: number): Promise<void> {
  page.value = next
  await router.replace({ query: { ...route.query, page: String(next) } })
  await load()
}
</script>

<style scoped>
.access-card {
  padding: 20px;
}
</style>
