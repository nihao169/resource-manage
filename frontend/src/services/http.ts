import type { Envelope, ApiError } from '../types/api'
export class HttpError extends Error {
  constructor(public status: number, public payload: ApiError) { super(payload.error.message) }
}
export async function request<T>(path: string, init: RequestInit = {}, csrfToken?: string): Promise<Envelope<T>> {
  if (!path.startsWith('/') || path.startsWith('//')) throw new Error('API path must be relative')
  const method = (init.method ?? 'GET').toUpperCase()
  const headers = new Headers(init.headers)
  if (!['GET', 'HEAD', 'OPTIONS'].includes(method)) {
    if (!csrfToken) throw new Error('CSRF token required')
    headers.set('X-CSRF-Token', csrfToken)
  }
  const response = await fetch('/api' + path, { ...init, method, headers, credentials: 'same-origin' })
  const payload = await response.json().catch(() => ({
    error: { code: 'PROXY_ERROR', message: '代理返回非 JSON 响应' }, request_id: response.headers.get('X-Request-ID') ?? ''
  }))
  if (!response.ok) throw new HttpError(response.status, payload)
  return payload as Envelope<T>
}

