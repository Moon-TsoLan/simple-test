<script setup lang="ts">
import { onMounted, reactive, ref } from 'vue'
import { api, formatMoney, queryString } from '../api'
import EmptyState from '../components/EmptyState.vue'
import type { Task1Item } from '../types'

const filters = reactive({ q: '', notice_id: '', product: '', brand: '', category: '', source_file: '' })
const items = ref<Task1Item[]>([])
const total = ref(0)
const page = ref(1)
const pageSize = 20
const loading = ref(false)
const error = ref('')
const detail = ref<Task1Item | null>(null)

<<<<<<< Updated upstream
=======
const pageCount = computed(() => Math.max(1, Math.ceil(total.value / pageSize)))
const rangeStart = computed(() => (total.value ? (page.value - 1) * pageSize + 1 : 0))
const rangeEnd = computed(() => Math.min(page.value * pageSize, total.value))
const padCount = computed(() => Math.max(0, pageSize - items.value.length))

function cellText(...parts: Array<string | number | null | undefined>) {
  return parts.map(part => (part == null || part === '' ? '' : String(part))).filter(Boolean).join(' / ')
}

>>>>>>> Stashed changes
async function search(targetPage = 1) {
  loading.value = true; error.value = ''; page.value = targetPage
  try {
    const result = await api<{ total: number; items: Task1Item[] }>(`/api/task1/items${queryString({ ...filters, page: page.value, page_size: pageSize })}`)
    items.value = result.items; total.value = result.total
  } catch (value) { error.value = value instanceof Error ? value.message : '检索失败' }
  finally { loading.value = false }
}

async function openDetail(entityId: string) {
  detail.value = await api<Task1Item>(`/api/task1/items/${entityId}`)
}

function exportUrl(kind: 'csv' | 'xlsx') {
  return `/api/task1/export.${kind}${queryString(filters)}`
}

onMounted(() => search())
</script>


<template>
  <section>
    <form class="panel filter-panel" @submit.prevent="search(1)">
      <div class="search-main"><label>全字段搜索<input v-model="filters.q" placeholder="产品、品牌、型号、公告标题…" /></label></div>
      <div class="filter-grid">
        <label>公告编号<input v-model="filters.notice_id" placeholder="notice_id" /></label>
        <label>产品/服务<input v-model="filters.product" placeholder="例如：台式计算机" /></label>
        <label>品牌/供应商<input v-model="filters.brand" placeholder="例如：联想" /></label>
        <label>品目<input v-model="filters.category" placeholder="名称或代码" /></label>
        <label>来源文件<input v-model="filters.source_file" placeholder="例如：报价表.xlsx" /></label>
        <button class="button primary" type="submit">检索</button>
      </div>
    </form>
    <div class="result-toolbar"><p><strong>{{ total }}</strong> 条实体结果 <span v-if="loading">· 正在刷新</span></p><div><a class="button ghost" :href="exportUrl('csv')">导出 CSV</a><a class="button ghost" :href="exportUrl('xlsx')">导出 XLSX</a></div></div>
    <p v-if="error" class="error-text">{{ error }}</p>
<<<<<<< Updated upstream
    <article v-if="items.length" class="panel table-panel">
      <div class="table-scroll"><table><thead><tr><th>公告 / 序号</th><th>产品或服务</th><th>品牌 / 型号</th><th>数量</th><th>单价 / 总价</th><th>证据来源</th></tr></thead>
        <tbody><tr v-for="item in items" :key="item.entity_id" @click="openDetail(item.entity_id)">
          <td><strong>{{ item.notice_id }}</strong><small>#{{ item.item_no }}</small></td>
          <td><strong>{{ item.product_service_name || '—' }}</strong><small>{{ item.category_name || item.category_code || '品目未给出' }}</small></td>
          <td>{{ item.brand_supplier || '—' }}<small>{{ item.spec_model || '型号未给出' }}</small></td>
          <td>{{ item.quantity ?? '—' }} {{ item.quantity_unit || '' }}</td>
          <td>{{ formatMoney(item.unit_price) }}<small>合计 {{ formatMoney(item.total_price) }}</small></td>
          <td>{{ item.source_file || '—' }}<small>{{ item.source_block_id || '无 Block 引用' }}</small></td>
        </tr></tbody></table></div>
      <div class="pagination"><button :disabled="page === 1" @click="search(page - 1)">上一页</button><span>第 {{ page }} / {{ Math.max(1, Math.ceil(total / pageSize)) }} 页</span><button :disabled="page * pageSize >= total" @click="search(page + 1)">下一页</button></div>
=======
    <article v-if="items.length || loading" class="panel table-panel table-sheet">
      <div class="table-scroll">
        <table class="data-table task1-table">
          <colgroup>
            <col class="col-notice" />
            <col class="col-product" />
            <col class="col-brand" />
            <col class="col-qty" />
            <col class="col-price" />
            <col class="col-source" />
          </colgroup>
          <thead>
            <tr>
              <th>公告 / 序号</th>
              <th>产品或服务</th>
              <th>品牌 / 型号</th>
              <th>数量</th>
              <th>单价 / 总价</th>
              <th>证据来源</th>
            </tr>
          </thead>
          <tbody>
            <tr
              v-for="item in items"
              :key="item.entity_id"
              :class="{ selected: detail?.entity_id === item.entity_id }"
              tabindex="0"
              @click="openDetail(item.entity_id)"
              @keydown.enter.prevent="openDetail(item.entity_id)"
            >
              <td>
                <div class="cell-stack" :title="cellText(item.notice_id, `#${item.item_no}`)">
                  <strong>{{ item.notice_id }}</strong>
                  <small>#{{ item.item_no }}</small>
                </div>
              </td>
              <td>
                <div class="cell-stack" :title="cellText(item.product_service_name, item.category_name || item.category_code)">
                  <strong>{{ item.product_service_name || '—' }}</strong>
                  <small>{{ item.category_name || item.category_code || '品目未给出' }}</small>
                </div>
              </td>
              <td>
                <div class="cell-stack" :title="cellText(item.brand_supplier, item.spec_model)">
                  <strong>{{ item.brand_supplier || '—' }}</strong>
                  <small>{{ item.spec_model || '型号未给出' }}</small>
                </div>
              </td>
              <td>
                <div class="cell-stack" :title="cellText(item.quantity, item.quantity_unit)">
                  <strong>{{ item.quantity ?? '—' }}</strong>
                  <small>{{ item.quantity_unit || '单位未给出' }}</small>
                </div>
              </td>
              <td>
                <div class="cell-stack" :title="`${formatMoney(item.unit_price)} / 合计 ${formatMoney(item.total_price)}`">
                  <strong>{{ formatMoney(item.unit_price) }}</strong>
                  <small>合计 {{ formatMoney(item.total_price) }}</small>
                </div>
              </td>
              <td>
                <div class="cell-stack" :title="cellText(item.source_file, item.source_block_id)">
                  <strong>{{ item.source_file || '—' }}</strong>
                  <small>{{ item.source_block_id || '无 Block 引用' }}</small>
                </div>
              </td>
            </tr>
            <tr v-for="index in padCount" :key="`pad-${index}`" class="is-pad" aria-hidden="true">
              <td></td><td></td><td></td><td></td><td></td><td></td>
            </tr>
          </tbody>
        </table>
      </div>
      <div class="pagination">
        <button type="button" :disabled="page === 1 || loading" @click="search(page - 1)">上一页</button>
        <span>第 {{ page }} / {{ pageCount }} 页 · 每页 {{ pageSize }} 条</span>
        <button type="button" :disabled="page >= pageCount || loading" @click="search(page + 1)">下一页</button>
      </div>
>>>>>>> Stashed changes
    </article>
    <EmptyState v-else-if="!loading" title="还没有匹配的实体" description="可以清空筛选条件重新检索。若数据库为空，请到数据导入页上传 HTML 与同名 ZIP，或直接导入已校验的 JSON / JSONL。" action="前往数据导入" @action="$router.push('/import')" />

    <div v-if="detail" class="drawer-backdrop" @click.self="detail = null">
<<<<<<< Updated upstream
      <aside class="drawer"><button class="drawer-close" aria-label="关闭详情" @click="detail = null">×</button><span class="eyebrow">EVIDENCE DETAIL</span><h2>{{ detail.product_service_name || '未命名实体' }}</h2><p class="drawer-title">{{ detail.title }}</p>
        <dl class="detail-grid"><div><dt>品目</dt><dd>{{ detail.category_name || '—' }} {{ detail.category_code || '' }}</dd></div><div><dt>品牌 / 供应商</dt><dd>{{ detail.brand_supplier || '—' }}</dd></div><div><dt>规格型号</dt><dd>{{ detail.spec_model || '—' }}</dd></div><div><dt>金额</dt><dd>{{ formatMoney(detail.unit_price) }} × {{ detail.quantity ?? '—' }} {{ detail.quantity_unit || '' }} = {{ formatMoney(detail.total_price) }}</dd></div></dl>
        <h3>证据定位</h3><div class="evidence-box"><strong>{{ detail.source_file || '公告正文' }}</strong><code>{{ detail.source_block_id }}{{ detail.source_block_row ? ` · 第 ${detail.source_block_row} 行` : '' }}</code><p>{{ detail.evidence_excerpt || '当前结果保留了 Block 与行号，可回到统一 Block 原文复核；该条暂未生成文本摘录。' }}</p></div>
=======
      <aside class="drawer">
        <button class="drawer-close" aria-label="关闭详情" @click="detail = null">×</button>
        <span class="eyebrow">EVIDENCE DETAIL</span>
        <h2>{{ detail.product_service_name || '未命名实体' }}</h2>
        <p class="drawer-title">{{ detail.title }}</p>
        <dl class="detail-grid">
          <div><dt>公告 / 序号</dt><dd>{{ detail.notice_id }} · #{{ detail.item_no }}</dd></div>
          <div><dt>品目</dt><dd>{{ detail.category_name || '—' }} {{ detail.category_code || '' }}</dd></div>
          <div><dt>品牌 / 供应商</dt><dd>{{ detail.brand_supplier || '—' }}</dd></div>
          <div><dt>规格型号</dt><dd>{{ detail.spec_model || '—' }}</dd></div>
          <div><dt>金额</dt><dd>{{ formatMoney(detail.unit_price) }} × {{ detail.quantity ?? '—' }} {{ detail.quantity_unit || '' }} = {{ formatMoney(detail.total_price) }}</dd></div>
        </dl>
        <h3>证据定位</h3>
        <div class="evidence-box">
          <strong>{{ detail.source_file || '公告正文' }}</strong>
          <code>{{ detail.source_block_id }}{{ detail.source_block_row ? ` · 第 ${detail.source_block_row} 行` : '' }}</code>
          <p>{{ detail.evidence_excerpt || '当前结果保留了 Block 与行号，可回到统一 Block 原文复核；该条暂未生成文本摘录。' }}</p>
        </div>
>>>>>>> Stashed changes
      </aside>
    </div>
  </section>
</template>
