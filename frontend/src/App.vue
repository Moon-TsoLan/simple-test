<script setup lang="ts">
import { computed } from 'vue'
import { useRoute } from 'vue-router'

const route = useRoute()
const title = computed(() => String(route.meta.title || '标讯关系台'))
const navigation = [
  { to: '/status', label: '总览', index: '01' },
  { to: '/import', label: '数据导入', index: '02' },
  { to: '/task1', label: '标的物检索', index: '03' },
  { to: '/task2', label: '关系场景', index: '04' },
  { to: '/graph', label: '关系图谱', index: '05' },
]
</script>

<template>
  <div class="shell">
    <aside class="sidebar">
      <div class="brand">
        <span class="brand-mark">采</span>
        <div><strong>标讯关系台</strong><small>PROCUREMENT INTELLIGENCE</small></div>
      </div>
      <nav aria-label="主导航">
        <RouterLink v-for="item in navigation" :key="item.to" :to="item.to">
          <span>{{ item.index }}</span>{{ item.label }}
        </RouterLink>
      </nav>
      <div class="sidebar-note">
        <span class="status-dot"></span>
        <div><strong>本地运行</strong><small>模型接入等待中</small></div>
      </div>
    </aside>
    <main>
      <header class="topbar">
        <div><p>四邮四电 · 招采标讯实体挖掘</p><h1>{{ title }}</h1></div>
        <div class="mode-pill"><span></span> 离线优先</div>
      </header>
      <RouterView />
    </main>
  </div>
</template>
