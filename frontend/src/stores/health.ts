import { defineStore } from 'pinia'
import { request } from '../services/http'
import type { Health } from '../types/api'
export const useHealthStore = defineStore('health', {
  state: () => ({ status: '尚未检查', requestId: '', loading: false }),
  actions: {
    async check() {
      this.loading = true
      try { const result = await request<Health>('/health/live'); this.status = result.data.status; this.requestId = result.request_id }
      catch (error) { this.status = error instanceof Error ? error.message : '连接失败'; this.requestId = '' }
      finally { this.loading = false }
    }
  }
})

