<script setup lang="ts">
import { ref } from 'vue'
import { api } from '../api'
import type { Job } from '../types'

const kind = ref<'task1' | 'task2'>('task1')
const files = ref<File[]>([])
const job = ref<Job | null>(null)
const error = ref('')
const uploading = ref(false)

function selectFiles(event: Event) {
  files.value = Array.from((event.target as HTMLInputElement).files || [])
}

async function refreshJob() {
  if (!job.value) return
  job.value = await api<Job>(`/api/jobs/${job.value.job_id}`)
}

async function upload() {
  if (!files.value.length) { error.value = '请先选择文件'; return }
  uploading.value = true; error.value = ''
  const form = new FormData()
  form.append('kind', kind.value)
  files.value.forEach(file => form.append('files', file))
  try {
    job.value = await api<Job>('/api/jobs/upload', { method: 'POST', body: form })
    await refreshJob()
  } catch (value) {
    error.value = value instanceof Error ? value.message : '上传失败'
  } finally { uploading.value = false }
}
</script>

<template>
  <section class="page-grid import-layout">
    <article class="panel hero-panel">
      <span class="eyebrow">PIPELINE INTAKE</span>
      <h2>把公告送入同一条处理链</h2>
      <p>任务一接收 HTML 与同名附件 ZIP；任务二接收公告 HTML 或已校验的关系 JSON。文件会先暂存并校验，模型未就绪时不会伪装成抽取成功。</p>
      <div class="step-line"><span>01 上传</span><i></i><span>02 校验</span><i></i><span>03 等待流水线</span></div>
    </article>
    <article class="panel upload-card">
      <div class="segmented">
        <button :class="{ active: kind === 'task1' }" @click="kind = 'task1'">任务一</button>
        <button :class="{ active: kind === 'task2' }" @click="kind = 'task2'">任务二</button>
      </div>
      <label class="drop-zone">
        <input type="file" multiple accept=".html,.htm,.zip,.json,.jsonl" @change="selectFiles" />
        <strong>{{ files.length ? `已选择 ${files.length} 个文件` : '选择或拖入公告文件' }}</strong>
        <small>HTML / ZIP / JSON / JSONL · 单文件不超过 200 MB</small>
      </label>
      <ul v-if="files.length" class="file-list"><li v-for="file in files" :key="file.name"><span>{{ file.name }}</span><small>{{ (file.size / 1024).toFixed(1) }} KB</small></li></ul>
      <p v-if="error" class="error-text">{{ error }}</p>
      <button class="button primary full" :disabled="uploading" @click="upload">{{ uploading ? '正在接收…' : '创建处理任务' }}</button>
    </article>
    <article v-if="job" class="panel job-card span-2">
      <div class="panel-heading"><div><span class="eyebrow">JOB {{ job.job_id.slice(0, 8) }}</span><h3>任务状态</h3></div><span class="tag" :class="job.status">{{ job.status }}</span></div>
      <div class="progress"><span :style="{ width: `${job.progress * 100}%` }"></span></div>
      <p>{{ job.message }}</p>
      <div class="job-stats"><span>文件 {{ job.file_count }}</span><span>就绪 {{ job.success_count }}</span><span>异常 {{ job.failure_count }}</span><span>阶段 {{ job.stage }}</span></div>
    </article>
  </section>
</template>
