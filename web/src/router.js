import { createRouter, createWebHistory } from 'vue-router'

import Board from './views/Board.vue'
import Input from './views/Input.vue'
import Dashboard from './views/Dashboard.vue'

const router = createRouter({
  history: createWebHistory(),
  routes: [
    { path: '/', name: 'board', component: Board, meta: { title: '线索看板' } },
    { path: '/input', name: 'input', component: Input, meta: { title: '线索录入' } },
    { path: '/stats', name: 'stats', component: Dashboard, meta: { title: '数据大盘' } },
    { path: '/:pathMatch(.*)*', redirect: '/' }
  ]
})

router.afterEach((to) => {
  document.title = `${to.meta.title || '线索捕手'} · LeadCatcher`
})

export default router
