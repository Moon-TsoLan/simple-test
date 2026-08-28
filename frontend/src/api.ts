export class ApiError extends Error {
  constructor(public status: number, message: string) {
    super(message)
  }
}

export async function api<T>(path: string, options?: RequestInit): Promise<T> {
  const response = await fetch(path, options)
  if (!response.ok) {
    let message = `请求失败（${response.status}）`
    try {
      const value = await response.json()
      message = value.detail || message
    } catch { /* keep fallback */ }
    throw new ApiError(response.status, message)
  }
  return response.json() as Promise<T>
}

export function queryString(values: Record<string, string | number | undefined>): string {
  const params = new URLSearchParams()
  Object.entries(values).forEach(([key, value]) => {
    if (value !== undefined && String(value).trim()) params.set(key, String(value))
  })
  const query = params.toString()
  return query ? `?${query}` : ''
}

export function formatMoney(value: unknown): string {
  const number = Number(value)
  return Number.isFinite(number) ? new Intl.NumberFormat('zh-CN', { style: 'currency', currency: 'CNY' }).format(number) : '—'
}
