<script setup lang="ts">
import { modules } from './router'
</script>
<template><header><RouterLink to="/">文件管理系统 / 开发骨架</RouterLink><span>Vue + FastAPI + PostgreSQL + MinIO</span></header>
<div class="layout"><nav><RouterLink to="/">工程状态</RouterLink><RouterLink v-for="module in modules" :key="module.path" :to="'/' + module.path">{{ module.title }}</RouterLink></nav><main><RouterView /></main></div>
</template>

