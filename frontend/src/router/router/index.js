import { createRouter, createWebHistory } from 'vue-router'

const routes = [
  {
    path: '/login',
    name: 'Login',
    component: () => import('@/views/Login.vue'),
    meta: { title: '登录', hideNav: true }
  },
  {
    path: '/',
    redirect: '/dashboard'
  },
  {
    path: '/dashboard',
    name: 'Dashboard',
    component: () => import('@/views/Dashboard.vue'),
    meta: { title: '仪表盘', icon: 'DataBoard' }
  },
  {
    path: '/accounts',
    name: 'Accounts',
    component: () => import('@/views/Accounts.vue'),
    meta: { title: '账号管理', icon: 'User' }
  },
  {
    path: '/tasks',
    name: 'Tasks',
    component: () => import('@/views/Tasks.vue'),
    meta: { title: '任务中心', icon: 'List' }
  },
  {
    path: '/leads',
    name: 'Leads',
    component: () => import('@/views/Leads.vue'),
    meta: { title: '线索管理', icon: 'DataAnalysis' }
  },
  {
    path: '/playbooks',
    name: 'Playbooks',
    component: () => import('@/views/Playbooks.vue'),
    meta: { title: '打法模板', icon: 'Notebook' }
  },
  {
    path: '/keywords',
    name: 'Keywords',
    component: () => import('@/views/Keywords.vue'),
    meta: { title: '关键词管理', icon: 'Search' }
  },
  {
    path: '/logs',
    name: 'Logs',
    component: () => import('@/views/Logs.vue'),
    meta: { title: '运行日志', icon: 'Document' }
  },
  {
    path: '/review',
    name: 'Review',
    component: () => import('@/views/Review.vue'),
    meta: { title: '审核队列', icon: 'ChatDotRound' }
  },
  {
    path: '/risk',
    name: 'Risk',
    component: () => import('@/views/Risk.vue'),
    meta: { title: '风控中心', icon: 'Shield' }
  },
  {
    path: '/users',
    name: 'Users',
    component: () => import('@/views/Users.vue'),
    meta: { title: '用户管理', icon: 'UserFilled' }
  },
  {
    path: '/douyin-comment',
    name: 'DouyinComment',
    component: () => import('@/views/DouyinComment.vue'),
    meta: { title: '抖音评论', icon: 'ChatDotRound' }
  },
]

const router = createRouter({
  history: createWebHistory(),
  routes,
})

router.beforeEach((to, from, next) => {
  document.title = (to.meta.title || 'SuperClaw') + ' - SuperClaw'
  const token = localStorage.getItem('token')
  if (to.path !== '/login' && !token) {
    next('/login')
  } else {
    next()
  }
})

export default router