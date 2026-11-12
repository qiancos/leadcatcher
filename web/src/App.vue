<script setup>
import { computed, onMounted, ref } from 'vue'
import { api } from './api'

const config = ref(null)

onMounted(async () => {
  try {
    config.value = await api.config()
  } catch {
    /* 口令未配置时静默失败，不打断主流程 */
  }
})

const providerClass = computed(() => (config.value?.provider === 'mock' ? 'mock' : 'live'))
const providerText = computed(() => {
  if (!config.value) return '连接中…'
  return config.value.provider === 'mock'
    ? '本地规则引擎 · 未配置模型 Key'
    : `已接入 ${config.value.model}`
})
const promptVersion = computed(() => config.value?.prompt_version || '—')
</script>

<template>
  <div class="app-shell">
    <aside class="sidebar">
      <div class="brand">
        <div class="brand-mark">LC</div>
        <div>
          <div class="brand-name">线索捕手</div>
          <div class="brand-sub">LEADCATCHER</div>
        </div>
      </div>

      <nav class="nav">
        <router-link to="/" exact-active-class="active">
          <span class="nav-dot"></span>线索看板
        </router-link>
        <router-link to="/input"><span class="nav-dot"></span>线索录入</router-link>
        <router-link to="/stats"><span class="nav-dot"></span>数据大盘</router-link>
      </nav>

      <div class="sidebar-foot">
        <div class="provider-pill" :class="providerClass">{{ providerText }}</div>
        <div style="font-size: 11px; color: #667085; margin-top: 8px; padding: 0 2px">
          Prompt {{ promptVersion }} · V1 Demo
        </div>
      </div>
    </aside>

    <main class="main">
      <router-view />
    </main>
  </div>
</template>
