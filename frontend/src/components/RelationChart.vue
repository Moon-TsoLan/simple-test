<script setup lang="ts">
import { BarChart, GraphChart } from 'echarts/charts'
import { GridComponent, TitleComponent, TooltipComponent } from 'echarts/components'
import { init, use, type ECharts } from 'echarts/core'
import { CanvasRenderer } from 'echarts/renderers'
import { onBeforeUnmount, onMounted, ref, watch } from 'vue'

use([BarChart, GraphChart, GridComponent, TitleComponent, TooltipComponent, CanvasRenderer])

const props = defineProps<{
  labels: string[]
  values: number[]
  title?: string
  graph?: { nodes: Array<Record<string, unknown>>; links: Array<Record<string, unknown>> }
}>()
const host = ref<HTMLElement | null>(null)
let chart: ECharts | null = null

function escapeHtml(value: unknown) {
  return String(value ?? '')
    .replaceAll('&', '&amp;')
    .replaceAll('<', '&lt;')
    .replaceAll('>', '&gt;')
    .replaceAll('"', '&quot;')
    .replaceAll("'", '&#39;')
}

function graphTooltip(value: unknown) {
  const params = value as { dataType?: string; data?: Record<string, unknown> }
  const data = params.data || {}
  if (params.dataType === 'edge') {
    const details = [`<strong>${escapeHtml(data.type || '关系')}</strong>`]
    if (typeof data.amount_yuan === 'number') details.push(`金额：¥${data.amount_yuan.toLocaleString('zh-CN')}`)
    if (typeof data.quote_value === 'number') details.push(`报价：${data.quote_value.toLocaleString('zh-CN')} ${escapeHtml(data.quote_unit)}`)
    if (typeof data.score === 'number') details.push(`得分：${data.score}`)
    if (typeof data.rank === 'number') details.push(`排名：${data.rank}`)
    return details.join('<br>')
  }
  return `<strong>${escapeHtml(data.name)}</strong><br><span>${escapeHtml(data.type)}</span>`
}

function render() {
  if (!host.value) return
  chart ||= init(host.value)
  if (props.graph) {
    const nodeCount = props.graph.nodes.length
    const repulsion = nodeCount > 70 ? 820 : nodeCount > 35 ? 580 : nodeCount > 15 ? 430 : 330
    const edgeLength: [number, number] = nodeCount > 70 ? [72, 120] : nodeCount > 35 ? [86, 145] : [110, 190]
    chart.setOption({
      tooltip: { formatter: graphTooltip, confine: true },
      animationDurationUpdate: nodeCount > 70 ? 0 : 420,
      series: [{
        type: 'graph', layout: 'force', roam: true, draggable: true,
        data: props.graph.nodes, links: props.graph.links,
        label: { show: true, position: 'right', color: '#17233d', fontSize: 10 },
        edgeLabel: { show: false, formatter: '{c}', color: '#5e687a', fontSize: 9, backgroundColor: '#fbfaf6dd', padding: [3, 5], borderRadius: 4 },
        edgeSymbol: ['none', 'arrow'], edgeSymbolSize: [0, 6],
        force: { repulsion, edgeLength, gravity: nodeCount > 70 ? 0.16 : 0.1, layoutAnimation: nodeCount <= 70 },
        lineStyle: { color: '#99a3b6', curveness: 0.06, opacity: 0.88 },
        emphasis: {
          focus: 'adjacency', scale: 1.12,
          label: { show: true },
          edgeLabel: { show: true, formatter: (params: { data?: { type?: string } }) => params.data?.type || '' },
          lineStyle: { width: 3, opacity: 1 },
        },
      }],
    }, true)
  } else {
    chart.setOption({
      title: props.title ? { text: props.title, textStyle: { fontSize: 14, color: '#17233d' } } : undefined,
      grid: { left: 18, right: 24, top: props.title ? 48 : 20, bottom: 18, containLabel: true },
      tooltip: { trigger: 'axis', axisPointer: { type: 'shadow' } },
      xAxis: { type: 'value', splitLine: { lineStyle: { color: '#e7e4dc' } } },
      yAxis: { type: 'category', data: props.labels, axisLabel: { width: 150, overflow: 'truncate' } },
      series: [{ type: 'bar', data: props.values, barMaxWidth: 26, itemStyle: { color: '#ff6a4d', borderRadius: [0, 6, 6, 0] } }],
    }, true)
  }
}

function resize() { chart?.resize() }
onMounted(() => { render(); window.addEventListener('resize', resize) })
watch(() => [props.labels, props.values, props.graph], render, { deep: true })
onBeforeUnmount(() => { window.removeEventListener('resize', resize); chart?.dispose() })
</script>

<template><div ref="host" class="chart" role="img" :aria-label="title || '关系图'" /></template>
