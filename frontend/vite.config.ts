import { defineConfig } from 'vitest/config'
import vue from '@vitejs/plugin-vue'
export default defineConfig({ plugins: [vue()], server: { proxy: { '/api': { target: 'https://localhost:8443', secure: false } } }, test: { environment: 'jsdom' } })

