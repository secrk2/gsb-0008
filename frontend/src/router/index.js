import { createRouter, createWebHistory } from 'vue-router'
import { useAuthStore } from '@/stores/auth'

const router = createRouter({
  history: createWebHistory(),
  routes: [
    { path: '/login', name: 'login', component: () => import('@/views/LoginView.vue') },
    {
      path: '/',
      component: () => import('@/layouts/AppLayout.vue'),
      children: [
        { path: '', redirect: '/dashboard' },
        {
          path: 'dashboard',
          name: 'dashboard',
          component: () => import('@/views/DashboardView.vue'),
          meta: { title: '入组作战台', icon: 'DataAnalysis' },
        },
        {
          path: 'subjects',
          name: 'subjects',
          component: () => import('@/views/SubjectListView.vue'),
          meta: { title: '受试者', icon: 'User' },
        },
        {
          path: 'subjects/:id',
          name: 'subject-detail',
          component: () => import('@/views/SubjectDetailView.vue'),
          meta: { title: '受试者链路', hidden: true },
        },
      ],
    },
    { path: '/:pathMatch(.*)*', redirect: '/dashboard' },
  ],
})

router.beforeEach((to) => {
  const auth = useAuthStore()
  if (to.name !== 'login' && !auth.isLoggedIn) {
    return { name: 'login', query: { redirect: to.fullPath } }
  }
  if (to.name === 'login' && auth.isLoggedIn) return { name: 'dashboard' }
})

export default router
