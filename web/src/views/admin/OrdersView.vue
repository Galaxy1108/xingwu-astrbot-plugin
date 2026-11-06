<template>
  <div>
    <PageHeader title="手动充值" description="创建充值单并确认到账；M1 阶段仅占位，接口在 M3 开放。" />
    <v-card class="panel">
      <EmptyState
        icon="mdi-cash-plus"
        title="手动充值将在 M3 开放"
        description="契约中的 POST /api/admin/orders 与 /api/admin/orders/{id}/confirm 在 M3 前返回 501 not_implemented。本期不提供建单入口，避免产生不可用操作。"
      >
        <template #actions>
          <v-btn variant="tonal" to="/admin/users">查看用户</v-btn>
          <v-btn variant="text" to="/admin/audit">查看审计</v-btn>
        </template>
      </EmptyState>
    </v-card>
  </div>
</template>

<script setup lang="ts">
import PageHeader from '@/components/PageHeader.vue'
import EmptyState from '@/components/EmptyState.vue'
</script>

<style scoped>
.panel {
  padding: 24px;
}
</style>
