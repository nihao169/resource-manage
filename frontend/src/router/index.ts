import { createRouter, createWebHistory } from 'vue-router'
import HomeView from '../views/HomeView.vue'
import PendingView from '../views/PendingView.vue'
export const modules = [
  { path: 'login', title: '登录与权限', owner: 'A 前端 / B PostgreSQL' },
  { path: 'files', title: '文件与元数据搜索', owner: 'A 前端 / B PostgreSQL' },
  { path: 'uploads', title: '上传与续传', owner: 'A 前端 / C MinIO / B 事务' },
  { path: 'versions', title: '历史版本', owner: 'A 前端 / B 与 C' },
  { path: 'trash', title: '回收站', owner: 'A 前端 / B 与 C' },
  { path: 'admin', title: '管理与审计', owner: 'A 前端 / B PostgreSQL' }
]
export default createRouter({ history: createWebHistory(), routes: [
  { path: '/', component: HomeView },
  ...modules.map(module => ({ path: '/' + module.path, component: PendingView, props: module }))
] })
