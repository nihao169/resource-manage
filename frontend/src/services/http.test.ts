import { afterEach, expect, test, vi } from 'vitest'
import { request, HttpError } from './http'
afterEach(() => vi.unstubAllGlobals())
test('uses prefix and cookie credentials', async () => {
 const fetcher = vi.fn().mockResolvedValue(new Response(JSON.stringify({data:{status:'live'},request_id:'id'})))
 vi.stubGlobal('fetch', fetcher)
 await request('/health/live')
 expect(fetcher.mock.calls[0][0]).toBe('/api/health/live')
 expect(fetcher.mock.calls[0][1].credentials).toBe('same-origin')
})
test('rejects mutation without CSRF', async () => { await expect(request('/files', {method:'POST'})).rejects.toThrow('CSRF') })
test('preserves API errors', async () => {
 vi.stubGlobal('fetch', vi.fn().mockResolvedValue(new Response(JSON.stringify({error:{code:'NOT_FOUND',message:'not implemented'},request_id:'id'}),{status:404})))
 await expect(request('/files')).rejects.toBeInstanceOf(HttpError)
})

