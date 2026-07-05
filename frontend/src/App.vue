<template>
  <div v-if="route.meta.hideNav">
    <router-view />
  </div>
  <div v-else class="app-layout">
    <aside class="sidebar">
      <div class="sidebar-header">
        <div class="logo">
          <el-icon :size="28" color="#89b4fa"><Cpu /></el-icon>
          <span class="logo-text">SuperClaw</span>
        </div>
      </div>

      <el-menu
        :default-active="route.path"
        :router="true"
        background-color="#11111b"
        text-color="#a6adc8"
        active-text-color="#89b4fa"
      >
        <el-menu-item v-for="item in menuItems" :key="item.path" :index="item.path">
          <el-icon><component :is="item.icon" /></el-icon>
          <template #title>{{ item.title }}</template>
        </el-menu-item>
      </el-menu>

      <div class="sidebar-footer">
        <div class="user-info">
          <el-icon><User /></el-icon>
          <span>{{ userStore.userInfo.username || '管理员' }}</span>
        </div>
        <el-button text @click="handleLogout" style="color: #f38ba8;">
          <el-icon><SwitchButton /></el-icon>
        </el-button>
      </div>
    </aside>

    <main class="main-content">
      <header class="content-header">
        <h2>{{ route.meta.title }}</h2>
      </header>
      <div class="content-body">
        <router-view v-slot="{ Component }">
          <transition name="fade" mode="out-in">
            <component :is="Component" />
          </transition>
        </router-view>
      </div>
    </main>
  </div>
</template>

<script setup>
import { onMounted } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { useUserStore } from '@/stores/user'

const route = useRoute()
const router = useRouter()
const userStore = useUserStore()

const menuItems = [
  { path: '/dashboard', title: '仪表盘', icon: 'DataBoard' },
  { path: '/accounts', title: '账号管理', icon: 'User' },
  { path: '/tasks', title: '任务中心', icon: 'List' },
  { path: '/leads', title: '线索管理', icon: 'DataAnalysis' },
  { path: '/playbooks', title: '打法模板', icon: 'Notebook' },
  { path: '/keywords', title: '关键词管理', icon: 'Search' },
  { path: '/logs', title: '运行日志', icon: 'Document' },
  { path: '/review', title: '审核队列', icon: 'ChatDotRound' },
  { path: '/douyin-comment', title: '抖音评论', icon: 'ChatDotRound' },
  { path: '/hongguo', title: '红果短剧', icon: 'VideoPlay' },
  { path: '/hongguo/templates', title: '红果模板', icon: 'Document' },
  { path: '/hongguo/settings', title: 'AI配置', icon: 'Setting' },
  { path: '/risk', title: '风控中心', icon: 'Shield' },
  { path: '/users', title: '用户管理', icon: 'UserFilled' },
]

onMounted(() => {
  document.documentElement.classList.add('dark')
})

function handleLogout() {
  userStore.logout()
  router.push('/login')
}
</script>

<style scoped>
.app-layout { display: flex; height: 100vh; overflow: hidden; }
.sidebar { width: var(--sidebar-width); min-width: var(--sidebar-width); background: var(--bg-sidebar); display: flex; flex-direction: column; border-right: 1px solid var(--border-color); overflow-y: auto; }
.sidebar-header { padding: 20px; border-bottom: 1px solid var(--border-color); }
.logo { display: flex; align-items: center; gap: 10px; }
.logo-text { font-size: 20px; font-weight: 700; color: var(--highlight); letter-spacing: 1px; }
.sidebar .el-menu { flex: 1; border: none; }
.sidebar-footer { padding: 16px 20px; border-top: 1px solid var(--border-color); display: flex; align-items: center; justify-content: space-between; }
.user-info { display: flex; align-items: center; gap: 8px; color: var(--text-secondary); font-size: 14px; }
.main-content { flex: 1; display: flex; flex-direction: column; overflow: hidden; background: var(--bg-primary); }
.content-header { height: var(--header-height); padding: 0 24px; display: flex; align-items: center; justify-content: space-between; border-bottom: 1px solid var(--border-color); background: var(--bg-card); }
.content-header h2 { font-size: 18px; font-weight: 600; color: var(--text-primary); }
.content-body { flex: 1; padding: 24px; overflow-y: auto; }
@media (max-width: 768px) { .sidebar { width: 64px; min-width: 64px; } .logo-text, .sidebar .el-menu-item span, .sidebar .user-info span { display: none; } }
</style>
