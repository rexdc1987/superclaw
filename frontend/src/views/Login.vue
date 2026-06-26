<template>
  <div class="login-container">
    <div class="login-card">
      <div class="login-header">
        <el-icon :size="40" color="#89b4fa"><Cpu /></el-icon>
        <h1>SuperClaw</h1>
        <p>社媒评论线索运营系统</p>
      </div>

      <el-form :model="form" @submit.prevent="handleLogin" class="login-form">
        <el-form-item>
          <el-input v-model="form.username" placeholder="用户名" prefix-icon="User" size="large" />
        </el-form-item>
        <el-form-item>
          <el-input
            v-model="form.password"
            type="password"
            placeholder="密码"
            prefix-icon="Lock"
            size="large"
            show-password
          />
        </el-form-item>
        <el-button type="primary" size="large" :loading="loading" @click="handleLogin" style="width: 100%">
          登录
        </el-button>
      </el-form>
    </div>
  </div>
</template>

<script setup>
import { ref } from 'vue'
import { useRouter } from 'vue-router'
import { ElMessage } from 'element-plus'
import { useUserStore } from '@/stores/user'

const router = useRouter()
const userStore = useUserStore()
const loading = ref(false)
const form = ref({ username: '', password: '' })

async function handleLogin() {
  if (!form.value.username || !form.value.password) {
    ElMessage.warning('请输入用户名和密码')
    return
  }

  loading.value = true
  try {
    userStore.setToken('demo-token')
    userStore.setUserInfo({ username: form.value.username, role: 'admin' })
    ElMessage.success('登录成功')
    router.push('/dashboard')
  } catch (e) {
    ElMessage.error('登录失败')
  } finally {
    loading.value = false
  }
}
</script>

<style scoped>
.login-container {
  height: 100vh;
  display: flex;
  align-items: center;
  justify-content: center;
  background: linear-gradient(135deg, #181825 0%, #1e1e2e 100%);
}
.login-card {
  width: 400px;
  padding: 40px;
  background: var(--bg-card);
  border-radius: 12px;
  border: 1px solid var(--border-color);
}
.login-header {
  text-align: center;
  margin-bottom: 30px;
}
.login-header h1 {
  margin: 12px 0 4px;
  color: var(--highlight);
  font-size: 24px;
}
.login-header p {
  color: var(--text-secondary);
  font-size: 14px;
}
</style>
