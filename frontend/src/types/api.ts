/** Shared wire contracts. ISO UTC timestamps; UUID strings; sizes are bytes. */
export type UUID = string
export type UTC = string
export interface Envelope<T> { data: T; request_id: UUID }
export interface ApiError { error: { code: string; message: string; details?: Record<string, unknown> }; request_id: UUID }
export interface Page<T> { items: T[]; total: number; page: number; page_size: number }
export interface Health { status: 'live' | 'ready' }
export type UploadStatus = 'created' | 'uploading' | 'uploaded' | 'committed' | 'failed' | 'expired'
/** Business DTOs are added against doc/前后端接口定义.md by B/C, not invented by the UI. */
