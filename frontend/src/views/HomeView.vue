<script setup lang="ts">
import { onMounted } from 'vue'
import { useHealthStore } from '../stores/health'
import { modules } from '../router'
const health = useHealthStore()
onMounted(() => health.check())
</script>
<template><p class="eyebrow">DEVELOPMENT BASELINE</p><h1>骨架已就位，业务待实现。</h1><p>这里验证工程连接，不代表四天 MVP 已完成。未实现的业务 API 返回 404。</p>
<section><h2>真实 API 存活检查</h2><p role="status">{{ health.status }}</p><p v-if="health.requestId" class="mono">{{ health.requestId }}</p><button :disabled="health.loading" @click="health.check()">重新检查</button><p>就绪检查仅供内部探针使用，不向浏览器开放。</p></section>
<section><h2>模块与负责人</h2><table><thead><tr><th>模块</th><th>负责人</th><th>状态</th></tr></thead><tbody><tr v-for="module in modules" :key="module.path"><td>{{ module.title }}</td><td>{{ module.owner }}</td><td>待实现</td></tr><tr><td>HTTPS / Nginx</td><td>A 前端 / Nginx</td><td>骨架配置</td></tr><tr><td>后端集成</td><td>B PostgreSQL</td><td>骨架配置</td></tr><tr><td>部署 / 启动环境</td><td>C MinIO / 部署</td><td>骨架配置</td></tr></tbody></table></section>
</template>
