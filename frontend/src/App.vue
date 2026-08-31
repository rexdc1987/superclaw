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
        <button class="user-info" type="button" title="修改密码" @click="passwordDialogVisible = true">
          <el-icon><User /></el-icon>
          <span>{{ userStore.userInfo.username || '管理员' }}</span>
        </button>
        <el-tooltip content="退出登录" placement="top">
          <el-button text @click="handleLogout" style="color: #f38ba8;" aria-label="退出登录">
            <el-icon><SwitchButton /></el-icon>
          </el-button>
        </el-tooltip>
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

  <el-dialog v-model="passwordDialogVisible" title="修改密码" width="440px" :close-on-click-modal="false">
    <el-form label-width="86px">
      <el-form-item label="原密码">
        <el-input v-model="passwordForm.old_password" type="password" show-password />
      </el-form-item>
      <el-form-item label="新密码">
        <el-input v-model="passwordForm.new_password" type="password" show-password />
      </el-form-item>
      <el-form-item label="确认密码">
        <el-input v-model="passwordForm.confirm_password" type="password" show-password />
      </el-form-item>
    </el-form>
    <template #footer>
      <el-button @click="passwordDialogVisible = false">取消</el-button>
      <el-button type="primary" :loading="changingPassword" @click="handleChangePassword">保存</el-button>
    </template>
  </el-dialog>
</template>

<script setup>
import { computed, onMounted, reactive, ref } from 'vue'
import { ElMessage } from 'element-plus'
import { useRoute, useRouter } from 'vue-router'
import { useUserStore } from '@/stores/user'
import { changePassword } from '@/api'

const route = useRoute()
const router = useRouter()
const userStore = useUserStore()
const passwordDialogVisible = ref(false)
const changingPassword = ref(false)
const passwordForm = reactive({ old_password: '', new_password: '', confirm_password: '' })

const allMenuItems = [
  { path: '/hongguo', title: '红果短剧', icon: 'VideoPlay' },
  { path: '/hongguo/multi', title: '红果多开', icon: 'Operation' },
  { path: '/hongguo/templates', title: '红果模板', icon: 'Document' },
  { path: '/hongguo/settings', title: 'AI配置', icon: 'Setting', adminOnly: true },
  { path: '/users', title: '账号管理', icon: 'UserFilled', adminOnly: true },
]
const menuItems = computed(() => allMenuItems.filter((item) => !item.adminOnly || userStore.userInfo.role === 'admin'))

onMounted(() => {
  document.documentElement.classList.add('dark')
})

function handleLogout() {
  userStore.logout()
  router.push('/login')
}

async function handleChangePassword() {
  if (!passwordForm.old_password || passwordForm.new_password.length < 8) {
    ElMessage.warning('请输入原密码，新密码至少 8 位')
    return
  }
  if (passwordForm.new_password !== passwordForm.confirm_password) {
    ElMessage.warning('两次输入的新密码不一致')
    return
  }
  changingPassword.value = true
  try {
    const result = await changePassword({
      old_password: passwordForm.old_password,
      new_password: passwordForm.new_password,
    })
    userStore.setToken(result.access_token)
    userStore.setUserInfo(result.user)
    Object.assign(passwordForm, { old_password: '', new_password: '', confirm_password: '' })
    passwordDialogVisible.value = false
    ElMessage.success('密码已修改，其他登录会话已失效')
  } finally {
    changingPassword.value = false
  }
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
.user-info { display: flex; align-items: center; gap: 8px; min-width: 0; padding: 4px 0; border: 0; background: transparent; color: var(--text-secondary); font-size: 14px; cursor: pointer; }
.main-content { flex: 1; display: flex; flex-direction: column; overflow: hidden; background: var(--bg-primary); }
.content-header { height: var(--header-height); padding: 0 24px; display: flex; align-items: center; justify-content: space-between; border-bottom: 1px solid var(--border-color); background: var(--bg-card); }
.content-header h2 { font-size: 18px; font-weight: 600; color: var(--text-primary); }
.content-body { flex: 1; padding: 24px; overflow-y: auto; }
@media (max-width: 768px) { .sidebar { width: 64px; min-width: 64px; } .logo-text, .sidebar .el-menu-item span, .sidebar .user-info span { display: none; } }
</style>
