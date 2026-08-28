<script setup lang="ts">
import { onMounted, ref } from 'vue'
import { api } from '../api'
import MetricCard from '../components/MetricCard.vue'
import type { PlatformStatus } from '../types'

const status = ref<PlatformStatus | null>(null)
const error = ref('')
async function load() {
  try { status.value = await api<PlatformStatus>('/api/status') }
  catch (value) { error.value = value instanceof Error ? value.message : '状态读取失败' }
}
onMounted(load)
</script>

<template>
  <section v-if="status" class="status-page">
    <div class="metrics">
      <MetricCard label="任务一实体" :value="status.task1.entities.toLocaleString()" :detail="`${status.task1.notices} 篇公告已入库`" tone="coral" />
      <MetricCard label="关系项目" :value="status.task2.projects" :detail="`${status.task2.organizations} 个主体`" tone="jade" />
      <MetricCard label="竞标记录" :value="status.task2.bids" :detail="`${status.task2.packages} 个包件`" />
      <MetricCard label="处理任务" :value="status.jobs.length" detail="最近 20 个本地任务" />
    </div>
    <div class="page-grid status-grid">
      <article class="panel system-card"><span class="eyebrow">SYSTEM READINESS</span><h2>功能链已就位，模型仍在准备</h2><p>解析、清洗、筛选、关系存储、检索导出和可视化可以独立运行。模型接入前，上传任务只会进入“等待流水线”状态。</p><div class="readiness-row"><span><i class="ok"></i>FastAPI / SQLite</span><span><i class="ok"></i>Vue / ECharts</span><span><i class="wait"></i>本地大模型</span></div></article>
      <article class="panel boundary-card"><span class="eyebrow">VALIDATION BOUNDARY</span><h3>当前可声明范围</h3><ul><li>合成数据与接口契约：可验证</li><li>空数据状态与错误边界：可验证</li><li>真实关系抽取准确率：待验证</li><li>P95 &lt; 1 秒：待真实规模压测</li></ul></article>
      <article class="panel span-2"><div class="panel-heading"><div><span class="eyebrow">RECENT JOBS</span><h3>最近处理任务</h3></div><button class="button ghost" @click="load">刷新</button></div><div v-if="status.jobs.length" class="table-scroll"><table><thead><tr><th>任务</th><th>类型</th><th>状态</th><th>阶段</th><th>文件</th><th>创建时间</th></tr></thead><tbody><tr v-for="job in status.jobs" :key="job.job_id"><td><code>{{ job.job_id.slice(0, 10) }}</code></td><td>{{ job.kind }}</td><td><span class="tag" :class="job.status">{{ job.status }}</span></td><td>{{ job.stage }}</td><td>{{ job.success_count }}/{{ job.file_count }}</td><td>{{ job.created_at }}</td></tr></tbody></table></div><p v-else class="muted">还没有处理任务。</p></article>
    </div>
  </section>
  <p v-else-if="error" class="error-text">{{ error }}</p>
</template>
