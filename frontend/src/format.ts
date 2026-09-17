export function formatDateTime(value: unknown): string {
  if (value == null || value === '') return '—'
  const text = String(value).trim()
  const match = text.match(/^(\d{4}-\d{2}-\d{2})(?:[ T](\d{2}:\d{2}))?/)
  if (!match) return text
  return match[2] ? `${match[1]} ${match[2]}` : match[1]
}

export function formatFileSize(bytes: number): string {
  if (!Number.isFinite(bytes) || bytes < 0) return '—'
  if (bytes < 1024) return `${bytes} B`
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`
  return `${(bytes / (1024 * 1024)).toFixed(1)} MB`
}

export function formatCount(value: unknown): string {
  const number = Number(value)
  return Number.isFinite(number) ? number.toLocaleString('zh-CN') : '—'
}

export function shortTitle(value: string): string {
  const raw = (value || '').trim()
  if (!/^https?:\/\//i.test(raw)) return raw
  return (raw.split('/').filter(Boolean).pop() || raw).replace(/\.html?$/i, '')
}

const JOB_KIND: Record<string, string> = { task1: '任务一', task2: '任务二' }
const JOB_STATUS: Record<string, string> = {
  queued: '排队中', running: '处理中', completed: '已完成', failed: '失败', staged: '已接收',
}
const JOB_STAGE: Record<string, string> = {
  upload: '接收文件', validate: '校验文件', parse: '解析 Blocks', select: '筛选证据',
  slotpack: '打包槽位', extract: '模型抽取', persist: '写入库', ingest: '导入结果',
  done: '完成', error: '异常', retry: '重试',
}

export function jobKindLabel(value: string): string { return JOB_KIND[value] || value }
export function jobStatusLabel(value: string): string { return JOB_STATUS[value] || value }
export function jobStageLabel(value: string): string { return JOB_STAGE[value] || value }
