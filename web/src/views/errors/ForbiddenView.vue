<template>
  <div class="error-page">
    <v-icon size="64" color="warning">mdi-shield-lock-outline</v-icon>
    <h1 class="error-title">403 · 无权限</h1>
    <p class="error-desc">
      当前账号没有访问该页面的权限。如需开通，请联系管理员；也可以先回到可用的页面继续操作。
    </p>
    <div class="error-actions">
      <v-btn
        color="primary"
        prepend-icon="mdi-home-outline"
        data-testid="back-home"
        to="/"
      >
        返回总览
      </v-btn>
      <v-btn variant="tonal" prepend-icon="mdi-refresh" data-testid="reload-page" @click="reload">
        刷新页面
      </v-btn>
      <v-btn variant="text" to="/bots">我的 Bot</v-btn>
    </div>
  </div>
</template>

<script setup lang="ts">
function reload(): void {
  window.location.reload()
}
</script>

<style scoped>
.error-page {
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  text-align: center;
  min-height: 60vh;
  gap: 8px;
}

.error-title {
  margin: 8px 0 0;
  font-size: 1.4rem;
  font-weight: 650;
}

.error-desc {
  margin: 0;
  max-width: 440px;
  color: var(--console-text-muted);
  font-size: 0.9rem;
  line-height: 1.6;
}

.error-actions {
  display: flex;
  gap: 8px;
  margin-top: 12px;
  flex-wrap: wrap;
  justify-content: center;
}
</style>
