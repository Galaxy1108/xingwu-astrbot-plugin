<template>
  <div class="auth-shell">
    <div class="auth-brand">
      <v-icon color="primary" size="30">mdi-robot-outline</v-icon>
      <span class="auth-brand__name">AstrBot</span>
      <v-chip size="x-small" variant="tonal" color="primary">SaaS 控制台</v-chip>
    </div>
    <v-card class="auth-card" elevation="2">
      <router-view />
    </v-card>
    <p class="auth-footer">加密存储 · 租户隔离 · 操作留痕</p>
  </div>
</template>

<script setup lang="ts"></script>

<style scoped>
.auth-shell {
  min-height: 100vh;
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  gap: 20px;
  padding: 24px 16px;
  background:
    radial-gradient(circle at 18% 12%, rgba(60, 150, 202, 0.12), transparent 42%),
    radial-gradient(circle at 82% 88%, rgba(60, 150, 202, 0.1), transparent 38%),
    var(--console-bg);
  box-sizing: border-box;
}

.auth-brand {
  display: flex;
  align-items: center;
  gap: 8px;
}

.auth-brand__name {
  font-size: 1.25rem;
  font-weight: 700;
  letter-spacing: 0.02em;
}

.auth-card {
  width: 100%;
  max-width: 440px;
  border-radius: var(--console-radius);
  overflow: hidden;
}

.auth-footer {
  margin: 0;
  color: var(--console-text-muted);
  font-size: 0.78rem;
}
</style>
