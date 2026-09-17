<script setup lang="ts">
<<<<<<< Updated upstream
import { computed, onMounted, ref } from 'vue'
import { api, queryString } from '../api'
=======
import { computed, onMounted, ref, watch } from 'vue'
import { api, formatMoney, queryString } from '../api'
import { shortTitle } from '../format'
>>>>>>> Stashed changes
import EmptyState from '../components/EmptyState.vue'
import RelationChart from '../components/RelationChart.vue'
import type { GraphData, Project } from '../types'

type GraphNode = GraphData['nodes'][number]
type GraphEdge = GraphData['edges'][number]

const PARTICIPANT_LIMIT_PER_PACKAGE = 8
const projects = ref<Project[]>([])
const selected = ref('')
const graph = ref<GraphData>({ nodes: [], edges: [] })
const loading = ref(false)
const expanded = ref(false)

const nodeVisuals: Record<string, { color: string; symbol: string; labelInside?: boolean }> = {
  项目: { color: '#17233d', symbol: 'roundRect', labelInside: true },
  包件: { color: '#ff6a4d', symbol: 'diamond', labelInside: true },
  采购单位: { color: '#247c70', symbol: 'roundRect', labelInside: true },
  代理机构: { color: '#8a62ad', symbol: 'rect', labelInside: true },
  中标供应商: { color: '#e8a72c', symbol: 'circle' },
  投标参与方: { color: '#7a879d', symbol: 'circle' },
  产品: { color: '#3d78c5', symbol: 'rect', labelInside: true },
  产品供应商: { color: '#ca5c8d', symbol: 'circle' },
  聚合节点: { color: '#b7bdc9', symbol: 'roundRect', labelInside: true },
}
const legendOrder = ['项目', '包件', '采购单位', '代理机构', '中标供应商', '投标参与方', '产品', '产品供应商', '聚合节点']
<<<<<<< Updated upstream
=======
// 始终展示的关键层级；其余节点在"关键标签"模式下只在悬停或聚焦时显示名称
const keyLabelTypes = new Set(['项目', '包件', '采购单位', '代理机构', '中标供应商', '聚合节点'])

const projectOptions = computed(() => projects.value.map(project => ({
  value: project.project_id,
  label: shortTitle(project.title || project.notice_id),
  hint: [project.publish_date, project.notice_id].filter(Boolean).join(' · '),
})))

function visualOf(type: string) {
  return nodeVisuals[type] || fallbackVisual
}
>>>>>>> Stashed changes

function edgePriority(edge: GraphEdge, nodeById: Map<string, GraphNode>) {
  const rank = typeof edge.rank === 'number' ? edge.rank : Number.MAX_SAFE_INTEGER
  const score = typeof edge.score === 'number' ? edge.score : -1
  const name = nodeById.get(edge.source)?.name || ''
  return { rank, score, name }
}

function compareParticipantEdges(left: GraphEdge, right: GraphEdge, nodeById: Map<string, GraphNode>) {
  const a = edgePriority(left, nodeById)
  const b = edgePriority(right, nodeById)
  return a.rank - b.rank || b.score - a.score || a.name.localeCompare(b.name, 'zh-CN')
}

function collapseDenseParticipants(data: GraphData) {
  const nodeById = new Map(data.nodes.map(node => [node.id, node]))
  const participantIds = new Set(data.nodes.filter(node => node.type === '投标参与方').map(node => node.id))
  const packageIds = data.nodes.filter(node => node.type === '包件').map(node => node.id)
  const keptParticipantIds = new Set<string>()

  for (const packageId of packageIds) {
    const participantEdges = data.edges
      .filter(edge => edge.target === packageId && participantIds.has(edge.source))
      .sort((left, right) => compareParticipantEdges(left, right, nodeById))
    for (const edge of participantEdges.slice(0, PARTICIPANT_LIMIT_PER_PACKAGE)) keptParticipantIds.add(edge.source)
  }

  const hiddenParticipantIds = new Set([...participantIds].filter(id => !keptParticipantIds.has(id)))
  if (!hiddenParticipantIds.size) return { nodes: data.nodes, edges: data.edges, hiddenParticipantCount: 0 }

  const visibleNodes = data.nodes.filter(node => node.type !== '投标参与方' || keptParticipantIds.has(node.id))
  const visibleIds = new Set(visibleNodes.map(node => node.id))
  const visibleEdges = data.edges.filter(edge => visibleIds.has(edge.source) && visibleIds.has(edge.target))

  for (const packageId of packageIds) {
    const hiddenForPackage = new Set(
      data.edges
        .filter(edge => edge.target === packageId && hiddenParticipantIds.has(edge.source))
        .map(edge => edge.source),
    )
    if (!hiddenForPackage.size) continue
    const aggregateId = `aggregate:${packageId}`
    visibleNodes.push({ id: aggregateId, name: `其余 ${hiddenForPackage.size} 个投标参与方`, type: '聚合节点' })
    visibleEdges.push({ source: aggregateId, target: packageId, type: '收起的参与方' })
  }
  return { nodes: visibleNodes, edges: visibleEdges, hiddenParticipantCount: hiddenParticipantIds.size }
}

const collapsedProjection = computed(() => collapseDenseParticipants(graph.value))
const isDense = computed(() => collapsedProjection.value.hiddenParticipantCount > 0)
const projection = computed(() => expanded.value
  ? { nodes: graph.value.nodes, edges: graph.value.edges, hiddenParticipantCount: 0 }
  : collapsedProjection.value)

function shortName(value: string, limit: number) {
  const compact = value.replace(/\s+/g, ' ').trim()
  return compact.length > limit ? `${compact.slice(0, limit)}…` : compact
}

function symbolSize(node: GraphNode, degree: number): number | [number, number] {
  const growth = Math.min(18, Math.sqrt(Math.max(1, degree)) * 4)
  const nameLength = node.name.replace(/\s+/g, '').length
  if (node.type === '项目') return [Math.min(210, 126 + Math.min(18, nameLength) * 4), 54 + Math.min(8, growth / 3)]
  if (node.type === '采购单位') return [Math.min(166, 88 + Math.min(13, nameLength) * 4), 42]
  if (node.type === '代理机构') return [Math.min(158, 82 + Math.min(13, nameLength) * 4), 38]
  if (node.type === '产品') return [Math.min(146, 78 + Math.min(12, nameLength) * 4), 38]
  if (node.type === '聚合节点') return [126, 38]
  if (node.type === '包件') return 48 + growth
  if (node.type === '中标供应商') return 42 + growth
  if (node.type === '产品供应商') return 34 + growth
  return 26 + Math.min(10, growth)
}

const chartGraph = computed(() => {
  const degree = new Map<string, number>()
  for (const edge of projection.value.edges) {
    degree.set(edge.source, (degree.get(edge.source) || 0) + 1)
    degree.set(edge.target, (degree.get(edge.target) || 0) + 1)
  }
  return {
    nodes: projection.value.nodes.map(node => {
      const visual = nodeVisuals[node.type] || nodeVisuals['投标参与方']
      const inside = Boolean(visual.labelInside)
      return {
        ...node,
        symbol: visual.symbol,
        symbolSize: symbolSize(node, degree.get(node.id) || 0),
        itemStyle: {
          color: visual.color,
          borderColor: '#fbfaf6',
          borderWidth: node.type === '中标供应商' ? 3 : 2,
          shadowBlur: node.type === '项目' ? 14 : 5,
          shadowColor: '#17233d24',
        },
        label: {
          show: true,
          position: inside ? 'inside' : 'right',
          formatter: shortName(node.name, inside ? 12 : 14),
          color: inside ? '#fff' : '#17233d',
          fontSize: node.type === '项目' ? 12 : 10,
          fontWeight: node.type === '项目' || node.type === '中标供应商' ? 700 : 500,
        },
      }
    }),
    links: projection.value.edges.map(edge => {
      const isWinner = edge.type === '中标' || edge.type === '成交'
      const isAggregate = edge.type === '收起的参与方'
      return {
        ...edge,
        lineStyle: {
          color: isWinner ? '#d99418' : isAggregate ? '#aeb5c2' : '#99a3b6',
          width: isWinner ? 2.6 : 1.2,
          type: isAggregate ? 'dashed' : 'solid',
          opacity: isAggregate ? 0.72 : 0.88,
          curveness: 0.06,
        },
      }
    }),
  }
})

const legendTypes = computed(() => {
  const present = new Set(projection.value.nodes.map(node => node.type))
  return legendOrder.filter(type => present.has(type))
})

async function loadGraph() {
<<<<<<< Updated upstream
  if (!selected.value) return
=======
  if (!selected.value) { graph.value = { nodes: [], edges: [] }; loading.value = false; return }
>>>>>>> Stashed changes
  loading.value = true
  graph.value = { nodes: [], edges: [] }
  expanded.value = false
  try {
    graph.value = await api<GraphData>(`/api/task2/graph/subgraph${queryString({ project_id: selected.value })}`)
  } finally {
    loading.value = false
  }
}
<<<<<<< Updated upstream
onMounted(async () => { projects.value = await api<Project[]>('/api/task2/projects?limit=200') })
=======

const currentProject = computed(() => projects.value.find(project => project.project_id === selected.value) || null)

onMounted(async () => { projects.value = await api<Project[]>('/api/task2/projects?limit=5000') })
>>>>>>> Stashed changes
</script>

<template>
  <section>
    <article class="panel graph-toolbar">
      <div><span class="eyebrow">PROJECT SUBGRAPH</span><h2>项目关系子图</h2><p>从项目出发查看采购单位、包件、竞标主体与产品之间的两跳关系。</p></div>
      <div class="query-row"><select v-model="selected"><option value="">选择项目</option><option v-for="project in projects" :key="project.project_id" :value="project.project_id">{{ project.title }}</option></select><button class="button primary" :disabled="!selected || loading" @click="loadGraph">{{ loading ? '加载中…' : '加载图谱' }}</button></div>
    </article>
    <article v-if="graph.nodes.length" class="panel graph-canvas">
      <div class="graph-summary">
        <div><strong>{{ projection.nodes.length }}</strong><span> / {{ graph.nodes.length }} 个节点</span><small v-if="isDense && !expanded">已按包件收起 {{ collapsedProjection.hiddenParticipantCount }} 个普通投标参与方</small><small v-else>节点大小随连接数变化，边标签在悬停时显示</small></div>
        <button v-if="isDense" class="button ghost" @click="expanded = !expanded">{{ expanded ? '收起密集节点' : `展开全部 ${graph.nodes.length} 个节点` }}</button>
      </div>
      <RelationChart :labels="[]" :values="[]" :graph="chartGraph" />
      <div class="graph-help">拖拽节点调整位置，滚轮缩放画布；将鼠标移到节点或连线上查看完整信息。</div>
      <div class="legend"><span v-for="type in legendTypes" :key="type"><i :data-shape="nodeVisuals[type].symbol" :style="{ background: nodeVisuals[type].color }"></i>{{ type }}</span></div>
    </article>
<<<<<<< Updated upstream
    <EmptyState v-else :title="projects.length ? '请选择一个项目' : '暂无可展示的项目关系'" :description="projects.length ? '图谱按项目即时从 SQLite 权威关系表投影，不依赖外部图数据库即可运行。' : '导入并结构化任务二数据后，这里将展示项目—组织—包件—产品关系。'" />
=======

    <EmptyState
      v-else-if="loading"
      title="正在加载图谱"
      description="图由 SQLite 权威关系表即时投影，节点较多时可能需要一两秒。"
    />
    <EmptyState
      v-else-if="selected"
      title="该项目没有可展示的关系"
      description="当前项目尚未抽出包件或主体关系。可以换一个项目，或到数据导入页补跑任务二。"
    />
    <EmptyState
      v-else
      :title="projects.length ? '请选择一个项目' : '暂无可展示的项目关系'"
      :description="projects.length ? '图谱按项目即时从 SQLite 权威关系表投影，不依赖外部图数据库即可运行。下拉支持按标题或公告编号筛选。' : '导入并结构化任务二数据后，这里将展示项目—组织—包件—产品关系。'"
    />
>>>>>>> Stashed changes
  </section>
</template>
