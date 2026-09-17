<script setup lang="ts">
import { onMounted, ref } from 'vue'
import { api } from '../api'
import { formatCount, formatDateTime, jobKindLabel, jobStageLabel, jobStatusLabel } from '../format'
import MetricCard from '../components/MetricCard.vue'
import type { PlatformStatus } from '../types'

const status = ref<PlatformStatus | null>(null)
const error = ref('')
const loading = ref(true)

async function load() {
  loading.value = true
  error.value = ''
  try { status.value = await api<PlatformStatus>('/api/status') }
  catch (value) { error.value = value instanceof Error ? value.message : '状态读取失败' }
  finally { loading.value = false }
}

onMounted(load)
</script>

<template>
  <section v-if="status" class="status-page">
    <div class="metrics">
      <MetricCard label="任务一实体" :value="formatCount(status.task1.entities)" :detail="`${formatCount(status.task1.notices)} 篇公告已入库`" tone="coral" />
      <MetricCard label="关系项目" :value="formatCount(status.task2.projects)" :detail="`${formatCount(status.task2.organizations)} 个主体`" tone="jade" />
      <MetricCard label="竞标记录" :value="formatCount(status.task2.bids)" :detail="`${formatCount(status.task2.packages)} 个包件`" />
      <MetricCard label="处理任务" :value="formatCount(status.jobs.length)" detail="最近 20 个本地任务" />
    </div>
    <div class="page-grid status-grid">
<<<<<<< Updated upstream
      <article class="panel system-card"><span class="eyebrow">SYSTEM READINESS</span><h2>功能链已就位，模型仍在准备</h2><p>解析、清洗、筛选、关系存储、检索导出和可视化可以独立运行。模型接入前，上传任务只会进入“等待流水线”状态。</p><div class="readiness-row"><span><i class="ok"></i>FastAPI / SQLite</span><span><i class="ok"></i>Vue / ECharts</span><span><i class="wait"></i>本地大模型</span></div></article>
      <article class="panel boundary-card"><span class="eyebrow">VALIDATION BOUNDARY</span><h3>当前可声明范围</h3><ul><li>合成数据与接口契约：可验证</li><li>空数据状态与错误边界：可验证</li><li>真实关系抽取准确率：待验证</li><li>P95 &lt; 1 秒：待真实规模压测</li></ul></article>
      <article class="panel span-2"><div class="panel-heading"><div><span class="eyebrow">RECENT JOBS</span><h3>最近处理任务</h3></div><button class="button ghost" @click="load">刷新</button></div><div v-if="status.jobs.length" class="table-scroll"><table><thead><tr><th>任务</th><th>类型</th><th>状态</th><th>阶段</th><th>文件</th><th>创建时间</th></tr></thead><tbody><tr v-for="job in status.jobs" :key="job.job_id"><td><code>{{ job.job_id.slice(0, 10) }}</code></td><td>{{ job.kind }}</td><td><span class="tag" :class="job.status">{{ job.status }}</span></td><td>{{ job.stage }}</td><td>{{ job.success_count }}/{{ job.file_count }}</td><td>{{ job.created_at }}</td></tr></tbody></table></div><p v-else class="muted">还没有处理任务。</p></article>
=======
      <article class="panel system-card">
        <span class="eyebrow">SYSTEM READINESS</span>
        <h2>{{ status.model.status === 'local' ? '上传流水线已接通本地模型' : (status.model.status === 'rules' ? '上传流水线走规则通道' : '功能链已就位') }}</h2>
        <p>{{ status.model.message }}。上传 HTML/ZIP 后会解析 Blocks、筛选或打包、调用 Agent 并写入当前展示库。</p>
        <div class="readiness-row">
          <span><i class="ok"></i>FastAPI / SQLite</span>
          <span><i class="ok"></i>Vue / ECharts</span>
          <span><i :class="status.model.status === 'not_configured' ? 'wait' : 'ok'"></i>本地大模型</span>
        </div>
      </article>
      <article class="panel boundary-card">
        <span class="eyebrow">VALIDATION BOUNDARY</span>
        <h3>当前可声明范围</h3>
        <ul>
          <li>任务一检索、证据回读与导出：可验证</li>
          <li>任务二五场景与项目图谱：可验证</li>
          <li>上传到抽取入库的工程闭环：可验证</li>
          <li>关系抽取字段级准确率：待验证</li>
        </ul>
      </article>
      <article class="panel span-2 job-history">
        <div class="panel-heading">
          <div><span class="eyebrow">RECENT JOBS</span><h3>最近处理任务</h3></div>
          <button class="button ghost" @click="load">刷新</button>
        </div>
        <div v-if="status.jobs.length" class="table-scroll">
          <table class="data-table jobs-table">
            <colgroup>
              <col class="col-job" />
              <col class="col-kind" />
              <col class="col-status" />
              <col class="col-stage" />
              <col class="col-files" />
              <col class="col-time" />
            </colgroup>
            <thead>
              <tr><th>任务</th><th>类型</th><th>状态</th><th>阶段</th><th>文件</th><th>创建时间</th></tr>
            </thead>
            <tbody>
              <tr v-for="job in status.jobs" :key="job.job_id">
                <td><code :title="job.job_id">{{ job.job_id.slice(0, 10) }}</code></td>
                <td>{{ jobKindLabel(job.kind) }}</td>
                <td><span class="tag" :class="job.status">{{ jobStatusLabel(job.status) }}</span></td>
                <td :title="job.message || job.stage">{{ jobStageLabel(job.stage) }}</td>
                <td>{{ job.success_count }}/{{ job.file_count }}</td>
                <td>{{ formatDateTime(job.created_at) }}</td>
              </tr>
            </tbody>
          </table>
        </div>
        <p v-else class="muted">还没有处理任务。</p>
      </article>
>>>>>>> Stashed changes
    </div>
  </section>
  <p v-else-if="error" class="error-text">{{ error }}</p>
  <p v-else-if="loading" class="muted status-loading">正在读取系统状态…</p>
</template>
