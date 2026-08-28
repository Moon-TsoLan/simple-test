import { createRouter, createWebHashHistory } from 'vue-router'

export default createRouter({
  history: createWebHashHistory(),
  routes: [
    { path: '/', redirect: '/status' },
    { path: '/import', component: () => import('./views/ImportView.vue'), meta: { title: '数据导入' } },
    { path: '/task1', component: () => import('./views/Task1View.vue'), meta: { title: '标的物检索' } },
    { path: '/task2', component: () => import('./views/Task2View.vue'), meta: { title: '关系场景' } },
    { path: '/graph', component: () => import('./views/GraphView.vue'), meta: { title: '关系图谱' } },
    { path: '/status', component: () => import('./views/StatusView.vue'), meta: { title: '系统状态' } },
  ],
})
