<template>
  <div class="accounts-page">
    <div class="page-header">
      <div class="header-left">
        <el-button type="primary" @click="showDialog()">
          <el-icon><Plus /></el-icon> 新增账号
        </el-button>
        <el-button @click="showGroupDialog = true">
          <el-icon><FolderOpened /></el-icon> 管理分组
        </el-button>
        <el-button @click="loadHealthReport">
          <el-icon><FirstAidKit /></el-icon> 健康报告
        </el-button>
      </div>
      <div class="header-right">
        <el-select
          v-model="selectedGroup"
          placeholder="按分组筛选"
          clearable
          style="width: 160px"
          @change="filterByGroup"
        >
          <el-option label="全部" value="" />
          <el-option
            v-for="g in groups"
            :key="g.id"
            :label="g.name"
            :value="g.id"
          />
        </el-select>
      </div>
    </div>

    <div class="batch-bar" v-if="selectedAccounts.length > 0">
      <span class="batch-count">已选择 {{ selectedAccounts.length }} 项</span>
      <el-button type="danger" size="small" @click="handleBatchDelete">
        <el-icon><Delete /></el-icon> 批量删除
      </el-button>
      <el-dropdown @command="handleBatchStatus" trigger="click">
        <el-button size="small" type="warning">
          批量状态 <el-icon class="el-icon--right"><ArrowDown /></el-icon>
        </el-button>
        <template #dropdown>
          <el-dropdown-menu>
            <el-dropdown-item command="available">设为可用</el-dropdown-item>
            <el-dropdown-item command="busy">设为忙碌</el-dropdown-item>
            <el-dropdown-item command="error">设为错误</el-dropdown-item>
          </el-dropdown-menu>
        </template>
      </el-dropdown>
    </div>

    <el-card>
      <el-table
        :data="filteredAccounts"
        style="width: 100%"
        v-loading="loading"
        @selection-change="handleSelectionChange"
      >
        <el-table-column type="selection" width="50" />
        <el-table-column prop="id" label="ID" width="60" />
        <el-table-column prop="display_name" label="账号名" min-width="120">
          <template #default="{ row }">
            <div class="account-name">
              <span class="name">{{ row.display_name || row.username }}</span>
              <span class="username" v-if="row.display_name">@{{ row.username }}</span>
            </div>
          </template>
        </el-table-column>
        <el-table-column prop="platform" label="平台" width="100">
          <template #default="{ row }">
            <el-tag size="small">{{ platformLabels[row.platform] || row.platform }}</el-tag>
          </template>
        </el-table-column>
        <el-table-column prop="login_status" label="登录状态" width="120">
          <template #default="{ row }">
            <el-tag :type="getLoginStatusType(row)" size="small">
              {{ getLoginStatusText(row) }}
            </el-tag>
          </template>
        </el-table-column>
        <el-table-column prop="last_login_at" label="最后登录" width="120">
          <template #default="{ row }">
            <span class="text-muted">{{ formatLastLogin(row.last_login_at) }}</span>
          </template>
        </el-table-column>
        <el-table-column prop="group_name" label="分组" width="100">
          <template #default="{ row }">
            <el-tag type="info" size="small" v-if="row.group_name">{{ row.group_name }}</el-tag>
            <span v-else class="text-muted">-</span>
          </template>
        </el-table-column>
        <el-table-column prop="status" label="状态" width="100">
          <template #default="{ row }">
            <el-tag :type="getStatusTagType(row.status)" size="small">
              {{ statusLabels[row.status] || row.status }}
            </el-tag>
          </template>
        </el-table-column>
        <el-table-column prop="daily_comment_count" label="今日评论" width="100" />
        <el-table-column prop="daily_dm_count" label="今日私信" width="100" />
        <el-table-column label="操作" width="280" fixed="right">
          <template #default="{ row }">
            <div class="action-buttons">
              <el-button link type="primary" size="small" @click="handleCheckLogin(row)" :loading="row._checking">
                <el-icon><Refresh /></el-icon> 检测登录
              </el-button>
              <el-button link type="success" size="small" @click="handleStartLogin(row)" :loading="row._logging">
                <el-icon><Iphone /></el-icon> 扫码登录
              </el-button>
              <el-button link type="primary" @click="showDialog(row)">编辑</el-button>
              <el-popconfirm title="确定删除该账号?" @confirm="handleDelete(row.id)">
                <template #reference>
                  <el-button link type="danger">删除</el-button>
                </template>
              </el-popconfirm>
            </div>
          </template>
        </el-table-column>
      </el-table>
    </el-card>

    <!-- Create/Edit Account Dialog -->
    <el-dialog
      v-model="dialogVisible"
      :title="editingId ? '编辑账号' : '新增账号'"
      width="500px"
      destroy-on-close
    >
      <el-form :model="form" label-width="80px">
        <el-form-item label="平台">
          <el-select v-model="form.platform" style="width: 100%">
            <el-option label="抖音" value="douyin" />
            <el-option label="小红书" value="xiaohongshu" />
            <el-option label="快手" value="kuaishou" />
            <el-option label="B站" value="bilibili" />
            <el-option label="闲鱼" value="xianyu" />
            <el-option label="拼多多" value="pinduoduo" />
          </el-select>
        </el-form-item>
        <el-form-item label="用户名">
          <el-input v-model="form.username" placeholder="请输入用户名" />
        </el-form-item>
        <el-form-item label="昵称">
          <el-input v-model="form.display_name" placeholder="请输入昵称" />
        </el-form-item>
        <el-form-item label="分组">
          <el-select v-model="form.group_id" style="width: 100%" clearable placeholder="选择分组">
            <el-option
              v-for="g in groups"
              :key="g.id"
              :label="g.name"
              :value="g.id"
            />
          </el-select>
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="dialogVisible = false">取消</el-button>
        <el-button type="primary" @click="handleSubmit" :loading="submitLoading">确定</el-button>
      </template>
    </el-dialog>

    <!-- QR Code Login Dialog -->
    <el-dialog
      v-model="loginDialogVisible"
      title="扫码登录"
      width="480px"
      destroy-on-close
    >
      <div class="login-dialog-content">
        <div class="login-step" v-if="loginStep === 1">
          <el-icon :size="48" color="#409EFF"><Iphone /></el-icon>
          <h3>准备打开浏览器</h3>
          <p>点击下方按钮，将打开{{ platformLabels[loginAccount?.platform] || '平台' }}登录页面</p>
          <p>请使用手机扫码完成登录</p>
          <el-button type="primary" @click="openLoginBrowser" :loading="loginLoading">
            打开登录页面
          </el-button>
        </div>
        <div class="login-step" v-else-if="loginStep === 2">
          <el-icon :size="48" color="#E6A23C"><Loading /></el-icon>
          <h3>等待扫码登录...</h3>
          <p>请在浏览器中完成扫码登录</p>
          <p class="login-tip">登录成功后将自动关闭此对话框</p>
          <el-progress :percentage="loginProgress" :format="formatProgress" />
          <p class="login-timeout">剩余时间: {{ loginTimeout }}秒</p>
        </div>
        <div class="login-step" v-else-if="loginStep === 3">
          <el-icon :size="48" color="#67C23A"><CircleCheck /></el-icon>
          <h3>登录成功！</h3>
          <p>账号已成功登录</p>
        </div>
        <div class="login-step error" v-else-if="loginStep === 4">
          <el-icon :size="48" color="#F56C6C"><CircleClose /></el-icon>
          <h3>登录超时</h3>
          <p>请重新尝试登录</p>
        </div>
      </div>
      <template #footer>
        <el-button @click="loginDialogVisible = false">关闭</el-button>
      </template>
    </el-dialog>

    <!-- Group Management Dialog -->
    <el-dialog
      v-model="showGroupDialog"
      title="管理分组"
      width="500px"
      destroy-on-close
    >
      <div class="group-management">
        <div class="group-create">
          <el-input
            v-model="newGroupName"
            placeholder="输入新分组名称"
            style="flex: 1"
            @keyup.enter="handleCreateGroup"
          />
          <el-button type="primary" @click="handleCreateGroup" :disabled="!newGroupName.trim()">
            创建
          </el-button>
        </div>
        <el-table :data="groups" style="width: 100%; margin-top: 16px" size="small">
          <el-table-column prop="id" label="ID" width="60" />
          <el-table-column prop="name" label="分组名称" />
          <el-table-column prop="account_count" label="账号数" width="80" />
          <el-table-column label="操作" width="80">
            <template #default="{ row }">
              <el-popconfirm title="确定删除该分组?" @confirm="handleDeleteGroup(row.id)">
                <template #reference>
                  <el-button link type="danger" size="small">删除</el-button>
                </template>
              </el-popconfirm>
            </template>
          </el-table-column>
        </el-table>
      </div>
    </el-dialog>

    <!-- Health Report Dialog -->
    <el-dialog
      v-model="showHealthDialog"
      title="账号健康报告"
      width="600px"
      destroy-on-close
    >
      <div class="health-report" v-loading="healthLoading">
        <el-row :gutter="16" class="health-stats">
          <el-col :span="8">
            <div class="health-stat-card">
              <div class="health-value">{{ healthReport.total || 0 }}</div>
              <div class="health-label">总账号数</div>
            </div>
          </el-col>
          <el-col :span="8">
            <div class="health-stat-card available">
              <div class="health-value">{{ healthReport.available || 0 }}</div>
              <div class="health-label">可用账号</div>
            </div>
          </el-col>
          <el-col :span="8">
            <div class="health-stat-card error">
              <div class="health-value">{{ healthReport.error || 0 }}</div>
              <div class="health-label">异常账号</div>
            </div>
          </el-col>
        </el-row>
        <div class="health-detail" v-if="healthReport.daily_stats">
          <h4>近7日统计</h4>
          <el-table :data="healthReport.daily_stats" size="small" style="width: 100%">
            <el-table-column prop="date" label="日期" />
            <el-table-column prop="active_count" label="活跃数" />
            <el-table-column prop="error_count" label="异常数" />
            <el-table-column prop="comment_count" label="评论数" />
            <el-table-column prop="dm_count" label="私信数" />
          </el-table>
        </div>
        <el-empty v-if="!healthReport.total && !healthLoading" description="暂无健康数据" />
      </div>
    </el-dialog>
  </div>
</template>

<script setup>
import { ref, computed, onMounted, reactive } from 'vue'
import {
  getAccounts, createAccount, updateAccount, deleteAccount,
  batchDeleteAccounts, batchUpdateAccountStatus,
  getAccountGroups, createAccountGroup, deleteAccountGroup,
  getAccountHealthReport
} from '@/api'
import { ElMessage, ElMessageBox } from 'element-plus'
import {
  Plus, FolderOpened, FirstAidKit, Delete, ArrowDown,
  Refresh, Iphone, Loading, CircleCheck, CircleClose
} from '@element-plus/icons-vue'

const accounts = ref([])
const groups = ref([])
const loading = ref(false)
const submitLoading = ref(false)
const dialogVisible = ref(false)
const editingId = ref(null)
const selectedGroup = ref('')
const selectedAccounts = ref([])

// Group management
const showGroupDialog = ref(false)
const newGroupName = ref('')

// Health report
const showHealthDialog = ref(false)
const healthLoading = ref(false)
const healthReport = ref({})

// Login dialog
const loginDialogVisible = ref(false)
const loginAccount = ref(null)
const loginStep = ref(1) // 1: ready, 2: waiting, 3: success, 4: timeout
const loginLoading = ref(false)
const loginProgress = ref(0)
const loginTimeout = ref(300)
const loginPollTimer = ref(null)
const loginCountdownTimer = ref(null)

const form = ref({ platform: 'douyin', username: '', display_name: '', group_id: null })

const platformLabels = {
  douyin: '抖音',
  xiaohongshu: '小红书',
  kuaishou: '快手',
  bilibili: 'B站',
  xianyu: '闲鱼',
  pinduoduo: '拼多多'
}

const statusLabels = {
  available: '可用',
  busy: '忙碌',
  error: '错误',
  banned: '封禁'
}

function getStatusTagType(status) {
  const map = { available: 'success', busy: 'warning', error: 'danger', banned: 'danger' }
  return map[status] || 'info'
}

// Login status helpers
function getLoginStatusType(row) {
  if (!row.last_login_at) return 'danger'
  const days = Math.floor((Date.now() - new Date(row.last_login_at).getTime()) / (1000 * 60 * 60 * 24))
  if (days >= 7) return 'danger'
  if (days >= 4) return 'warning'
  return 'success'
}

function getLoginStatusText(row) {
  if (!row.last_login_at) return '未登录'
  const days = Math.floor((Date.now() - new Date(row.last_login_at).getTime()) / (1000 * 60 * 60 * 24))
  if (days >= 7) return '已过期'
  if (days >= 4) return '即将过期'
  return '已登录'
}

function formatLastLogin(time) {
  if (!time) return '从未登录'
  const diff = Date.now() - new Date(time).getTime()
  const days = Math.floor(diff / (1000 * 60 * 60 * 24))
  if (days > 0) return `${days}天前`
  const hours = Math.floor(diff / (1000 * 60 * 60))
  if (hours > 0) return `${hours}小时前`
  const minutes = Math.floor(diff / (1000 * 60))
  return minutes > 0 ? `${minutes}分钟前` : '刚刚'
}

const filteredAccounts = computed(() => {
  if (!selectedGroup.value) return accounts.value
  return accounts.value.filter(a => a.group_id === selectedGroup.value)
})

function filterByGroup() {
  // Already handled by computed
}

function handleSelectionChange(selection) {
  selectedAccounts.value = selection
}

onMounted(() => {
  loadAccounts()
  loadGroups()
})

async function loadAccounts() {
  loading.value = true
  try {
    const data = await getAccounts()
    // Add reactive properties for loading states
    accounts.value = (data || []).map(a => ({
      ...a,
      _checking: false,
      _logging: false
    }))
  } catch (e) {
    console.error(e)
  } finally {
    loading.value = false
  }
}

async function loadGroups() {
  try {
    groups.value = await getAccountGroups()
  } catch (e) {
    console.error(e)
  }
}

function showDialog(row) {
  if (row) {
    editingId.value = row.id
    form.value = {
      platform: row.platform || 'douyin',
      username: row.username || '',
      display_name: row.display_name || '',
      group_id: row.group_id || null
    }
  } else {
    editingId.value = null
    form.value = { platform: 'douyin', username: '', display_name: '', group_id: null }
  }
  dialogVisible.value = true
}

async function handleSubmit() {
  submitLoading.value = true
  try {
    if (editingId.value) {
      await updateAccount(editingId.value, form.value)
      ElMessage.success('更新成功')
    } else {
      await createAccount(form.value)
      ElMessage.success('创建成功')
    }
    dialogVisible.value = false
    loadAccounts()
  } catch (e) {
    console.error(e)
  } finally {
    submitLoading.value = false
  }
}

async function handleDelete(id) {
  try {
    await deleteAccount(id)
    ElMessage.success('删除成功')
    loadAccounts()
  } catch (e) { console.error(e) }
}

async function handleBatchDelete() {
  const ids = selectedAccounts.value.map(a => a.id)
  if (ids.length === 0) return
  try {
    await ElMessageBox.confirm('确定删除选中的 ' + ids.length + ' 个账号?', '批量删除', {
      confirmButtonText: '确定',
      cancelButtonText: '取消',
      type: 'warning'
    })
    await batchDeleteAccounts(ids)
    ElMessage.success("成功删除 " + ids.length + " 个账号")
    loadAccounts()
  } catch (e) {
    if (e !== 'cancel') console.error(e)
  }
}

async function handleBatchStatus(status) {
  const ids = selectedAccounts.value.map(a => a.id)
  if (ids.length === 0) return
  try {
    await batchUpdateAccountStatus(ids, status)
    ElMessage.success("成功更新 " + ids.length + " 个账号状态")
    loadAccounts()
  } catch (e) { console.error(e) }
}

// Login related functions
async function handleCheckLogin(row) {
  row._checking = true
  try {
    const resp = await fetch(`/api/v1/accounts/${row.id}/check`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' }
    })
    const data = await resp.json()
    
    if (data.valid) {
      if (data.warning) {
        ElMessage.warning(data.warning)
      } else {
        ElMessage.success('登录状态正常')
      }
    } else {
      ElMessage.error(data.reason || '登录已过期，请重新登录')
      // Update local status
      row.login_status = 'expired'
    }
    loadAccounts()
  } catch (e) {
    ElMessage.error('检测失败: ' + e.message)
  } finally {
    row._checking = false
  }
}

async function handleStartLogin(row) {
  loginAccount.value = row
  loginStep.value = 1
  loginDialogVisible.value = true
}

async function openLoginBrowser() {
  loginLoading.value = true
  try {
    const resp = await fetch(`/api/v1/accounts/${loginAccount.value.id}/login`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' }
    })
    const data = await resp.json()
    
    if (data.login_url) {
      // Open login URL in new tab
      window.open(data.login_url, '_blank')
      
      // Start polling for login status
      loginStep.value = 2
      loginProgress.value = 0
      loginTimeout.value = 300
      startLoginPolling()
    }
  } catch (e) {
    ElMessage.error('启动登录失败: ' + e.message)
    loginStep.value = 4
  } finally {
    loginLoading.value = false
  }
}

function startLoginPolling() {
  // Clear any existing timers
  clearLoginTimers()
  
  // Poll every 2 seconds
  loginPollTimer.value = setInterval(async () => {
    try {
      const resp = await fetch(`/api/v1/accounts/${loginAccount.value.id}/login-status`)
      const data = await resp.json()
      
      if (data.status === 'logged_in') {
        // Login successful
        loginStep.value = 3
        loginProgress.value = 100
        clearLoginTimers()
        ElMessage.success('登录成功！')
        loadAccounts()
      }
    } catch (e) {
      console.error('Polling error:', e)
    }
  }, 2000)
  
  // Countdown timer
  loginCountdownTimer.value = setInterval(() => {
    loginTimeout.value--
    loginProgress.value = Math.min(95, Math.floor((300 - loginTimeout.value) / 3))
    
    if (loginTimeout.value <= 0) {
      // Timeout
      loginStep.value = 4
      clearLoginTimers()
      ElMessage.error('登录超时，请重新尝试')
    }
  }, 1000)
}

function clearLoginTimers() {
  if (loginPollTimer.value) {
    clearInterval(loginPollTimer.value)
    loginPollTimer.value = null
  }
  if (loginCountdownTimer.value) {
    clearInterval(loginCountdownTimer.value)
    loginCountdownTimer.value = null
  }
}

function formatProgress(percentage) {
  return percentage === 100 ? '完成' : `${percentage}%`
}

// Group management
async function handleCreateGroup() {
  const name = newGroupName.value.trim()
  if (!name) return
  try {
    await createAccountGroup({ name })
    ElMessage.success('分组创建成功')
    newGroupName.value = ''
    loadGroups()
  } catch (e) { console.error(e) }
}

async function handleDeleteGroup(id) {
  try {
    await deleteAccountGroup(id)
    ElMessage.success('分组删除成功')
    loadGroups()
  } catch (e) { console.error(e) }
}

// Health report
async function loadHealthReport() {
  showHealthDialog.value = true
  healthLoading.value = true
  try {
    healthReport.value = await getAccountHealthReport()
  } catch (e) {
    healthReport.value = {}
    console.error(e)
  } finally {
    healthLoading.value = false
  }
}
</script>

<style scoped>
.page-header {
  margin-bottom: 16px;
  display: flex;
  align-items: center;
  justify-content: space-between;
  flex-wrap: wrap;
  gap: 12px;
}
.header-left {
  display: flex;
  align-items: center;
  gap: 8px;
}
.header-right {
  display: flex;
  align-items: center;
  gap: 8px;
}
.batch-bar {
  margin-bottom: 12px;
  padding: 10px 16px;
  background: var(--bg-card);
  border: 1px solid var(--border-color);
  border-radius: 8px;
  display: flex;
  align-items: center;
  gap: 12px;
}
.batch-count {
  color: var(--text-secondary);
  font-size: 14px;
}
.text-muted {
  color: var(--text-muted);
  font-size: 13px;
}
.account-name {
  display: flex;
  flex-direction: column;
}
.account-name .name {
  font-weight: 500;
}
.account-name .username {
  font-size: 12px;
  color: var(--text-muted);
}
.action-buttons {
  display: flex;
  align-items: center;
  gap: 4px;
}
.group-management {
  display: flex;
  flex-direction: column;
}
.group-create {
  display: flex;
  gap: 8px;
}
.health-report {
  min-height: 200px;
}
.health-stats {
  margin-bottom: 20px;
}
.health-stat-card {
  text-align: center;
  padding: 16px;
  background: var(--bg-primary);
  border-radius: 8px;
  border: 1px solid var(--border-color);
}
.health-stat-card.available .health-value {
  color: var(--success);
}
.health-stat-card.error .health-value {
  color: var(--danger);
}
.health-value {
  font-size: 32px;
  font-weight: 700;
  color: var(--text-primary);
}
.health-label {
  font-size: 13px;
  color: var(--text-secondary);
  margin-top: 4px;
}
.health-detail {
  margin-top: 16px;
}
.health-detail h4 {
  color: var(--text-primary);
  margin-bottom: 12px;
  font-size: 15px;
}

/* Login dialog styles */
.login-dialog-content {
  text-align: center;
  padding: 20px;
}
.login-step {
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: 16px;
}
.login-step h3 {
  margin: 0;
  font-size: 18px;
}
.login-step p {
  margin: 0;
  color: var(--text-secondary);
}
.login-tip {
  font-size: 12px;
  color: var(--text-muted);
}
.login-timeout {
  font-size: 14px;
  color: var(--el-color-warning);
}
.login-step.error h3 {
  color: var(--el-color-danger);
}
</style>
