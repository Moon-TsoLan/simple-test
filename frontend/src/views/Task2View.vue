<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import { api, formatMoney, queryString } from '../api'
import { formatDateTime, shortTitle } from '../format'
import EmptyState from '../components/EmptyState.vue'
import RelationChart from '../components/RelationChart.vue'
import type { Dictionary, Organization } from '../types'

const scenarios = [
  { id: 1, title: '采购单位 → 中标供应商', help: '查看合作次数、中标金额与最近合作日期' },
  { id: 2, title: '采购单位 → 高频投标组合', help: '查看投标频次 TOP 与共同投标组合' },
  { id: 3, title: '中标供应商 → 共同竞标主体', help: '查看同包件出现的竞争主体与频次' },
  { id: 4, title: '多供应商 → 共同采购单位', help: '求两个及以上中标供应商的采购单位交集' },
  { id: 5, title: '多供应商 → 共同参与项目', help: '求两个及以上供应商的共同竞标项目' },
]
const active = ref(1)
const organizations = ref<Organization[]>([])
const selectedUnit = ref('')
const selectedSupplier = ref('')
const selectedSuppliers = ref<string[]>([])
const rows = ref<Dictionary[]>([])
const pairRows = ref<Dictionary[]>([])
const loading = ref(false)
const ran = ref(false)
const error = ref('')
const current = computed(() => scenarios.find(value => value.id === active.value)!)
const units = computed(() => organizations.value.filter(value => value.org_type === '采购单位'))
const winners = computed(() => organizations.value.filter(value => value.org_type === '中标供应商'))
const suppliers = computed(() => organizations.value.filter(value => value.org_type !== '采购单位' && value.org_type !== '代理机构'))
<<<<<<< Updated upstream
const columns = computed(() => rows.value.length ? Object.keys(rows.value[0]) : [])
const chartLabels = computed(() => rows.value.slice(0, 10).map(value => String(value.supplier_name || value.bidder_name || value.cobidder_name || value.unit_name || value.title || '结果')))
=======
const unitOptions = computed(() => units.value.map(org => ({ value: org.org_id, label: org.name, hint: org.org_type })))
const winnerOptions = computed(() => winners.value.map(org => ({ value: org.org_id, label: org.name, hint: org.org_type })))
const supplierOptions = computed(() => suppliers.value.map(org => ({ value: org.org_id, label: org.name, hint: org.org_type })))
const hiddenColumns = new Set(['supplier_id', 'bidder_id', 'unit_id', 'project_id', 'org_id', 'cobidder_id', 'bidder_a_id', 'bidder_b_id'])
const columns = computed(() => rows.value.length
  ? Object.keys(rows.value[0]).filter(key => !hiddenColumns.has(key) && !key.endsWith('_id'))
  : [])
const chartLabels = computed(() => rows.value.slice(0, 10).map(value => shortTitle(String(value.supplier_name || value.bidder_name || value.cobidder_name || value.unit_name || value.title || '结果'))))
>>>>>>> Stashed changes
const chartValues = computed(() => rows.value.slice(0, 10).map(value => Number(value.win_count || value.bid_count || value.project_count || value.matched_suppliers || 0)))

function setScenario(id: number) {
  active.value = id
  rows.value = []
  pairRows.value = []
  error.value = ''
  ran.value = false
}

async function run() {
  loading.value = true; error.value = ''; rows.value = []; pairRows.value = []; ran.value = false
  try {
    if (active.value === 1) {
      if (!selectedUnit.value) throw new Error('请选择采购单位')
      rows.value = await api<Dictionary[]>(`/api/task2/units/${selectedUnit.value}/win-suppliers`)
    } else if (active.value === 2) {
      if (!selectedUnit.value) throw new Error('请选择采购单位')
      rows.value = await api<Dictionary[]>(`/api/task2/units/${selectedUnit.value}/top-bidders?top=10`)
      pairRows.value = await api<Dictionary[]>(`/api/task2/units/${selectedUnit.value}/co-bid-pairs`)
    } else if (active.value === 3) {
      if (!selectedSupplier.value) throw new Error('请选择中标供应商')
      rows.value = await api<Dictionary[]>(`/api/task2/suppliers/${selectedSupplier.value}/co-bidders?top=10`)
    } else {
      if (selectedSuppliers.value.length < 2) throw new Error('请至少选择两个供应商')
      const endpoint = active.value === 4 ? 'common-units' : 'joint-projects'
      rows.value = await api<Dictionary[]>(`/api/task2/suppliers/${endpoint}${queryString({ ids: selectedSuppliers.value.join(',') })}`)
    }
    ran.value = true
  } catch (value) { error.value = value instanceof Error ? value.message : '查询失败' }
  finally { loading.value = false }
}

function label(key: string) {
  const labels: Record<string, string> = {
    supplier_name: '供应商', bidder_name: '投标主体', cobidder_name: '共同竞标主体', unit_name: '采购单位',
    title: '项目', notice_id: '公告编号', package_no: '包件', win_count: '中标次数', bid_count: '投标次数',
    project_count: '项目数', total_amount_yuan: '中标金额（元）', total_win_amount_yuan: '中标金额（元）',
    participant_amount_yuan: '参与报价（元）', last_date: '最近日期', results: '结果', matched_suppliers: '匹配供应商数',
  }
  return labels[key] || key
}

function display(column: string, value: unknown) {
  if (value == null || value === '') return '—'
  if (column.endsWith('_yuan') || column.includes('amount')) return formatMoney(value)
  if (column.endsWith('_date') || column === 'last_date') return formatDateTime(value)
  if (column === 'title') return shortTitle(String(value))
  return String(value)
}

onMounted(async () => { organizations.value = await api<Organization[]>('/api/task2/organizations?limit=5000') })
</script>

<template>
  <section class="scenario-layout">
    <aside class="panel scenario-nav">
      <span class="eyebrow">FIVE SCENARIOS</span>
      <button v-for="scenario in scenarios" :key="scenario.id" :class="{ active: active === scenario.id }" @click="setScenario(scenario.id)">
        <b>0{{ scenario.id }}</b>
        <span><strong>{{ scenario.title }}</strong><small>{{ scenario.help }}</small></span>
      </button>
    </aside>
    <div class="scenario-main">
      <article class="panel scenario-query">
        <span class="eyebrow">SCENARIO 0{{ active }}</span>
        <h2>{{ current.title }}</h2>
        <p>{{ current.help }}。金额口径统一为中标或成交金额。</p>
        <div class="query-row">
<<<<<<< Updated upstream
          <select v-if="active <= 2" v-model="selectedUnit"><option value="">选择采购单位</option><option v-for="org in units" :key="org.org_id" :value="org.org_id">{{ org.name }}</option></select>
          <select v-else-if="active === 3" v-model="selectedSupplier"><option value="">选择供应商</option><option v-for="org in suppliers" :key="org.org_id" :value="org.org_id">{{ org.name }}</option></select>
          <select v-else v-model="selectedSuppliers" multiple size="5"><option v-for="org in suppliers" :key="org.org_id" :value="org.org_id">{{ org.name }}</option></select>
          <button class="button primary" :disabled="loading" @click="run">{{ loading ? '查询中…' : '运行分析' }}</button>
        </div><small v-if="active >= 4" class="field-note">按住 Ctrl 可多选供应商。</small><p v-if="error" class="error-text">{{ error }}</p>
      </article>
      <template v-if="rows.length">
        <article class="panel chart-panel"><RelationChart :labels="chartLabels" :values="chartValues" :title="current.title" /></article>
        <article class="panel table-panel"><div class="table-scroll"><table><thead><tr><th v-for="column in columns" :key="column">{{ label(column) }}</th></tr></thead><tbody><tr v-for="(row, index) in rows" :key="index"><td v-for="column in columns" :key="column">{{ row[column] ?? '—' }}</td></tr></tbody></table></div></article>
        <article v-if="pairRows.length" class="panel table-panel"><div class="panel-heading"><h3>共同投标组合</h3><span>{{ pairRows.length }} 组</span></div><div class="table-scroll"><table><thead><tr><th>主体 A</th><th>主体 B</th><th>共同项目数</th></tr></thead><tbody><tr v-for="(row, index) in pairRows" :key="index"><td>{{ row.bidder_a_name }}</td><td>{{ row.bidder_b_name }}</td><td>{{ row.project_count }}</td></tr></tbody></table></div></article>
=======
          <SelectField v-if="active <= 2" v-model="selectedUnit" :options="unitOptions" placeholder="选择采购单位" aria-label="选择采购单位" />
          <SelectField v-else-if="active === 3" v-model="selectedSupplier" :options="winnerOptions" placeholder="选择中标供应商" aria-label="选择中标供应商" />
          <SelectField v-else v-model="selectedSuppliers" :options="supplierOptions" multiple placeholder="选择两个及以上供应商" aria-label="选择供应商" />
          <button class="button primary" :disabled="loading" @click="run">{{ loading ? '查询中…' : '运行分析' }}</button>
        </div>
        <small v-if="active >= 4" class="field-note">已选 {{ selectedSuppliers.length }} 个供应商，至少选择两个；在下拉列表中可多选。</small>
        <p v-if="error" class="error-text">{{ error }}</p>
      </article>
      <template v-if="rows.length">
        <article class="panel chart-panel"><RelationChart :labels="chartLabels" :values="chartValues" :title="current.title" /></article>
        <article class="panel table-panel">
          <div class="table-scroll scenario-table-scroll">
            <table class="data-table scenario-table">
              <thead><tr><th v-for="column in columns" :key="column">{{ label(column) }}</th></tr></thead>
              <tbody>
                <tr v-for="(row, index) in rows" :key="index">
                  <td v-for="column in columns" :key="column" :title="display(column, row[column])">{{ display(column, row[column]) }}</td>
                </tr>
              </tbody>
            </table>
          </div>
        </article>
        <article v-if="pairRows.length" class="panel table-panel">
          <div class="panel-heading scenario-table-heading"><h3>共同投标组合</h3><span>{{ pairRows.length }} 组</span></div>
          <div class="table-scroll scenario-table-scroll">
            <table class="data-table scenario-table">
              <thead><tr><th>主体 A</th><th>主体 B</th><th>共同项目数</th></tr></thead>
              <tbody>
                <tr v-for="(row, index) in pairRows" :key="index">
                  <td :title="String(row.bidder_a_name || '')">{{ row.bidder_a_name }}</td>
                  <td :title="String(row.bidder_b_name || '')">{{ row.bidder_b_name }}</td>
                  <td>{{ row.project_count }}</td>
                </tr>
              </tbody>
            </table>
          </div>
        </article>
>>>>>>> Stashed changes
      </template>
      <EmptyState
        v-else-if="loading"
        title="正在查询"
        description="结果来自 SQLite 预计算表或受控交集查询。"
      />
      <EmptyState
        v-else-if="ran"
        title="没有匹配结果"
        description="当前主体组合下没有记录。可以换一个采购单位或供应商再试。"
      />
      <EmptyState
        v-else-if="!error"
        :title="organizations.length ? '选择条件后运行分析' : '暂无任务二关系数据'"
        :description="organizations.length ? '结果会同时呈现为统计表和关系图；所有统计查询均来自 SQLite 预计算或受控交集查询。' : '请到数据导入页选择任务二，上传 HTML 与同名 ZIP，或导入已校验 JSON / JSONL。不会用合成数据冒充实际结果。'"
      />
    </div>
  </section>
</template>
