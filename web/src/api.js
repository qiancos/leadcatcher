const TOKEN_KEY = 'leadcatcher_token'

export const tokenStore = {
  get: () => localStorage.getItem(TOKEN_KEY) || '',
  set: (value) => localStorage.setItem(TOKEN_KEY, value),
  clear: () => localStorage.removeItem(TOKEN_KEY)
}

export class ApiError extends Error {
  constructor(message, status, code) {
    super(message)
    this.name = 'ApiError'
    this.status = status
    this.code = code
  }
}

async function request(path, { method = 'GET', body, params } = {}) {
  const url = new URL(path, window.location.origin)
  if (params) {
    Object.entries(params).forEach(([key, value]) => {
      if (value !== undefined && value !== null && value !== '') {
        url.searchParams.set(key, value)
      }
    })
  }

  const headers = { 'Content-Type': 'application/json' }
  const token = tokenStore.get()
  if (token) headers['X-Admin-Token'] = token

  const response = await fetch(url, {
    method,
    headers,
    body: body === undefined ? undefined : JSON.stringify(body)
  })

  const raw = await response.text()
  let data = null
  try {
    data = raw ? JSON.parse(raw) : null
  } catch {
    data = raw
  }

  if (response.status === 401) {
    tokenStore.clear()
    throw new ApiError('访问口令错误或已失效', 401, 'UNAUTHORIZED')
  }

  if (!response.ok) {
    const detail = data && data.detail
    const message =
      typeof detail === 'string' ? detail : (detail && detail.message) || `请求失败（${response.status}）`
    throw new ApiError(message, response.status, detail && detail.code)
  }

  return data
}

export const api = {
  config: () => request('/api/config'),
  health: () => request('/api/health'),

  parse: (text, force = false) => request('/api/leads/parse', { method: 'POST', body: { text, force } }),
  list: (params) => request('/api/leads', { params }),
  get: (id) => request(`/api/leads/${id}`),
  update: (id, payload) => request(`/api/leads/${id}`, { method: 'PATCH', body: payload }),
  remove: (id) => request(`/api/leads/${id}`, { method: 'DELETE' }),
  restore: (id) => request(`/api/leads/${id}/restore`, { method: 'POST' }),
  retry: (id) => request(`/api/leads/${id}/retry`, { method: 'POST' }),
  verify: (id, result) => request(`/api/leads/${id}/verify`, { method: 'POST', body: { result } }),

  submitFeedback: (payload) => request('/api/feedbacks', { method: 'POST', body: payload }),
  feedbacks: (status) => request('/api/feedbacks', { params: { status } }),
  closeFeedback: (id) => request(`/api/feedbacks/${id}/close`, { method: 'PATCH' }),

  stats: (days) => request('/api/stats', { params: { days } }),
  exportCsv: () => `${window.location.origin}/api/export${tokenStore.get() ? `?token=${tokenStore.get()}` : ''}`
}

// ---- 展示层的小工具（口径仍在后端，这里只做格式化）----

export const INTENTS = ['高', '中', '低', '无效']
export const INTENT_COLORS = { 高: 'danger', 中: 'warning', 低: 'info', 无效: 'info' }
export const FOLLOW_LABEL = { pending: '待跟进', followed: '已跟进', invalid: '已放弃' }
export const FOLLOW_COLORS = { pending: 'warning', followed: 'success', invalid: 'info' }

export function formatTime(iso) {
  if (!iso) return '—'
  const date = new Date(iso)
  if (Number.isNaN(date.getTime())) return iso
  const pad = (n) => String(n).padStart(2, '0')
  return `${pad(date.getMonth() + 1)}-${pad(date.getDate())} ${pad(date.getHours())}:${pad(date.getMinutes())}`
}
