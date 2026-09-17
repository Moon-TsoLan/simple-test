<script setup lang="ts">
<<<<<<< Updated upstream
import { ref } from 'vue'
=======
import { computed, onMounted, onUnmounted, ref } from 'vue'
>>>>>>> Stashed changes
import { api } from '../api'
import { formatFileSize, jobKindLabel, jobStageLabel, jobStatusLabel } from '../format'
import type { Job, PlatformStatus } from '../types'

const kind = ref<'task1' | 'task2'>('task1')
const files = ref<File[]>([])
const job = ref<Job | null>(null)
const recent = ref<Job[]>([])
const error = ref('')
const uploading = ref(false)
<<<<<<< Updated upstream
=======
const dragging = ref(false)
let events: EventSource | null = null
let dragDepth = 0

const profiles = {
  task1: {
    eyebrow: 'TASK 1 · ENTITY EXTRACTION',
    title: '抽取标的物与金额证据',
    intro: '面向结果公告，从 HTML 与同名附件中抽取产品/服务名称、品目、品牌/制造商/产品供应商、规格型号、单价、数量、总价，并回指 Block 证据，供检索、详情与导出。',
    fields: ['产品/服务', '品目', '品牌供应商', '规格型号', '单价', '数量', '总价', 'Block 证据'],
    steps: [
      { no: '01', name: 'Parser 2.1', detail: '多格式解析为统一 Blocks' },
      { no: '02', name: 'Selector 1.3', detail: '本地筛选并分块送入模型' },
      { no: '03', name: 'Entity Agent', detail: '强表规则快路径 + 弱表/正文抽取' },
      { no: '04', name: '校验入库', detail: 'Schema、证据坐标与金额校验' },
    ],
    caption: '任务一入库后可在「标的物检索」中筛选、核对证据并导出。',
  },
  task2: {
    eyebrow: 'TASK 2 · RELATION EXTRACTION',
    title: '抽取主体关系与竞标结果',
    intro: '抽取采购单位、代理机构、包件、中标供应商、投标参与方，以及报价、得分、排名和审查结果，支撑五类业务分析与项目关系图。',
    fields: ['采购单位', '代理机构', '包件', '中标供应商', '投标参与方', '报价/得分', '排名', '审查结果'],
    steps: [
      { no: '01', name: 'Parser 2.1', detail: '同一批 Blocks，不重复解析' },
      { no: '02', name: 'SlotPacker', detail: '按空槽打包高召回证据' },
      { no: '03', name: 'Relation Agent', detail: '门闸、强表通道与一次修复' },
      { no: '04', name: '校验入库', detail: 'Pydantic 与 Block 坐标校验' },
    ],
    caption: '任务二入库后可在「关系场景」与「关系图谱」中按项目查看。',
  },
} as const

const profile = computed(() => profiles[kind.value])
const history = computed(() => recent.value.filter(item => item.job_id !== job.value?.job_id).slice(0, 6))
>>>>>>> Stashed changes

function selectFiles(event: Event) {
  files.value = Array.from((event.target as HTMLInputElement).files || [])
}

<<<<<<< Updated upstream
async function refreshJob() {
  if (!job.value) return
  job.value = await api<Job>(`/api/jobs/${job.value.job_id}`)
=======
function takeFiles(list: FileList | File[] | null | undefined) {
  const incoming = Array.from(list || []).filter(file => /\.(html|htm|zip|json|jsonl)$/i.test(file.name))
  if (incoming.length) files.value = incoming
}

function removeFile(index: number) {
  files.value = files.value.filter((_, current) => current !== index)
}

function onDragEnter(event: DragEvent) {
  event.preventDefault()
  dragDepth += 1
  dragging.value = true
}

function onDragOver(event: DragEvent) {
  event.preventDefault()
  dragging.value = true
}

function onDragLeave() {
  dragDepth = Math.max(0, dragDepth - 1)
  if (!dragDepth) dragging.value = false
}

function onDrop(event: DragEvent) {
  event.preventDefault()
  dragDepth = 0
  dragging.value = false
  takeFiles(event.dataTransfer?.files)
}

function stopEvents() {
  events?.close()
  events = null
}

function watchJob(jobId: string) {
  stopEvents()
  events = new EventSource(`/api/jobs/${jobId}/events`)
  events.onmessage = (message) => {
    job.value = JSON.parse(message.data) as Job
    if (job.value.status === 'completed' || job.value.status === 'failed') {
      stopEvents()
      void loadRecent()
    }
  }
  events.onerror = async () => {
    stopEvents()
    try { job.value = await api<Job>(`/api/jobs/${jobId}`) } catch { /* keep last snapshot */ }
  }
>>>>>>> Stashed changes
}

async function loadRecent() {
  try {
    const status = await api<PlatformStatus>('/api/status')
    recent.value = status.jobs
  } catch { /* 导入页没有近期任务也可以继续 */ }
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
<<<<<<< Updated upstream
=======

onMounted(loadRecent)
onUnmounted(stopEvents)
>>>>>>> Stashed changes
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
<<<<<<< Updated upstream
      <div class="segmented">
        <button :class="{ active: kind === 'task1' }" @click="kind = 'task1'">任务一</button>
        <button :class="{ active: kind === 'task2' }" @click="kind = 'task2'">任务二</button>
      </div>
      <label class="drop-zone">
=======
      <p class="task-caption"><strong>{{ kind === 'task1' ? '任务一' : '任务二' }}</strong> · {{ profile.caption }} JSON / JSONL 可直接导入已校验结果。</p>
      <label class="drop-zone" :class="{ 'is-drag': dragging }" @dragenter="onDragEnter" @dragover="onDragOver" @dragleave="onDragLeave" @drop="onDrop">
>>>>>>> Stashed changes
        <input type="file" multiple accept=".html,.htm,.zip,.json,.jsonl" @change="selectFiles" />
        <strong>{{ files.length ? `已选择 ${files.length} 个文件` : '选择或拖入公告文件' }}</strong>
        <small>HTML / ZIP / JSON / JSONL · 单文件不超过 200 MB</small>
      </label>
      <ul v-if="files.length" class="file-list">
        <li v-for="(file, index) in files" :key="`${file.name}-${index}`">
          <span :title="file.name">{{ file.name }}</span>
          <small>{{ formatFileSize(file.size) }}</small>
          <button type="button" class="file-remove" aria-label="移除文件" @click.prevent="removeFile(index)">×</button>
        </li>
      </ul>
      <p v-if="error" class="error-text">{{ error }}</p>
      <button class="button primary full" :disabled="uploading" @click="upload">{{ uploading ? '正在接收…' : '创建处理任务' }}</button>
    </article>
    <article v-if="job" class="panel job-card span-2">
      <div class="panel-heading">
        <div><span class="eyebrow">JOB {{ job.job_id.slice(0, 8) }}</span><h3>{{ jobKindLabel(job.kind) }}处理进度</h3></div>
        <span class="tag" :class="job.status">{{ jobStatusLabel(job.status) }}</span>
      </div>
      <div class="progress"><span :style="{ width: `${job.progress * 100}%` }"></span></div>
      <p>{{ job.message }}</p>
      <div class="job-stats">
        <span>文件 {{ job.file_count }}</span>
        <span>就绪 {{ job.success_count }}</span>
        <span>异常 {{ job.failure_count }}</span>
        <span>阶段 {{ jobStageLabel(job.stage) }}</span>
      </div>
    </article>
    <article v-if="history.length" class="panel span-2 job-history">
      <div class="panel-heading"><div><span class="eyebrow">RECENT JOBS</span><h3>最近处理任务</h3></div></div>
      <div class="table-scroll">
        <table class="data-table jobs-table">
          <colgroup>
            <col class="col-job" />
            <col class="col-kind" />
            <col class="col-status" />
            <col class="col-stage" />
            <col class="col-files" />
          </colgroup>
          <thead><tr><th>任务</th><th>类型</th><th>状态</th><th>阶段</th><th>文件</th></tr></thead>
          <tbody>
            <tr v-for="item in history" :key="item.job_id">
              <td><code :title="item.job_id">{{ item.job_id.slice(0, 10) }}</code></td>
              <td>{{ jobKindLabel(item.kind) }}</td>
              <td><span class="tag" :class="item.status">{{ jobStatusLabel(item.status) }}</span></td>
              <td :title="item.message || item.stage">{{ jobStageLabel(item.stage) }}</td>
              <td>{{ item.success_count }}/{{ item.file_count }}</td>
            </tr>
          </tbody>
        </table>
      </div>
    </article>
  </section>
</template>
