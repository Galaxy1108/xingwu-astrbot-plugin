<template>
  <div class="share-page">
    <div class="share-shell">
      <div class="share-brand">
        <BrandMark :size="28" />
        <span class="share-brand__name">星坞 <em>Alpha</em></span>
      </div>

      <v-card class="share-card">
        <LoadingSkeleton v-if="loading" variant="detail" />

        <template v-else-if="expired">
          <div class="share-state">
            <v-icon size="48" color="warning">mdi-link-off</v-icon>
            <h1 class="share-state__title">分享已过期</h1>
            <p class="text-muted share-state__desc">
              该对话分享链接已过期或被撤销，请联系分享者重新生成。
            </p>
          </div>
        </template>

        <template v-else-if="error">
          <div class="share-state">
            <v-icon size="48" color="error">mdi-alert-circle-outline</v-icon>
            <h1 class="share-state__title">无法查看分享</h1>
            <p class="text-muted share-state__desc">{{ error }}</p>
          </div>
        </template>

        <template v-else-if="conversation">
          <header class="share-head">
            <h1 class="share-title">{{ conversation.title || '对话分享' }}</h1>
            <p class="share-meta text-muted">
              {{ formatDateTime(conversation.created_at) }}
              <template v-if="conversation.expires_at">
                · 有效期至 {{ formatDateTime(conversation.expires_at) }}
              </template>
            </p>
          </header>
          <v-divider />
          <div class="share-messages">
            <ConversationMessages :messages="messages" />
          </div>
        </template>
      </v-card>

      <p class="share-foot text-muted">由 星坞 Alpha 提供只读分享 · 内容归分享者所有</p>
    </div>
  </div>
</template>

<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import { useRoute } from 'vue-router'
import BrandMark from '@/components/BrandMark.vue'
import ConversationMessages from '@/components/ConversationMessages.vue'
import LoadingSkeleton from '@/components/LoadingSkeleton.vue'
import { getPublicConversation } from '@/api/conversations'
import { toApiError } from '@/api/client'
import type { ConversationMessage, PublicConversation } from '@/types'
import { errorMessage } from '@/utils/errors'
import { formatDateTime } from '@/utils/format'

const route = useRoute()
const loading = ref(true)
const error = ref('')
const expired = ref(false)
const conversation = ref<PublicConversation | null>(null)
const messages = ref<ConversationMessage[]>([])

const token = computed(() => (typeof route.params.token === 'string' ? route.params.token : ''))

onMounted(() => {
  void load()
})

async function load(): Promise<void> {
  loading.value = true
  error.value = ''
  expired.value = false
  try {
    const raw = (await getPublicConversation(token.value)) as PublicConversation & {
      conversation?: PublicConversation
      history?: ConversationMessage[]
    }
    const data = raw.conversation ?? raw
    conversation.value = data
    messages.value = data.messages ?? raw.history ?? []
  } catch (err) {
    const apiError = toApiError(err)
    if (apiError.status === 410 || apiError.status === 404) {
      expired.value = true
    } else {
      error.value = errorMessage(apiError, '分享内容加载失败')
    }
  } finally {
    loading.value = false
  }
}
</script>

<style scoped>
.share-page {
  min-height: 100vh;
  padding: 40px 16px;
  box-sizing: border-box;
  background: var(--console-bg);
  color: var(--console-text);
}

.share-shell {
  width: 100%;
  max-width: 760px;
  margin: 0 auto;
}

.share-brand {
  display: flex;
  align-items: center;
  gap: 8px;
  margin-bottom: 14px;
  padding-left: 4px;
}

.share-brand__name {
  font-size: 15px;
  font-weight: 650;
}

.share-brand__name em {
  font-style: normal;
  font-size: 11px;
  color: var(--console-primary);
}

.share-card {
  padding: 24px;
  background: var(--console-surface);
  border: 1px solid var(--console-border);
  border-radius: 12px;
}

.share-head {
  padding-bottom: 12px;
}

.share-title {
  margin: 0;
  font-size: 20px;
  font-weight: 700;
  overflow-wrap: anywhere;
}

.share-meta {
  margin: 5px 0 0;
  font-size: 12px;
}

.share-messages {
  padding-top: 16px;
}

.share-state {
  display: flex;
  flex-direction: column;
  align-items: center;
  text-align: center;
  padding: 40px 10px;
  gap: 6px;
}

.share-state__title {
  margin: 8px 0 0;
  font-size: 18px;
  font-weight: 650;
}

.share-state__desc {
  margin: 0;
  max-width: 420px;
  font-size: 13px;
  line-height: 1.6;
}

.share-foot {
  margin: 14px 0 0;
  text-align: center;
  font-size: 11.5px;
}

@media (max-width: 599px) {
  .share-page {
    padding: 20px 12px;
  }

  .share-card {
    padding: 18px 14px;
  }
}
</style>
