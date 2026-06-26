<template>
  <div class="hongguo-list">
    <div class="page-header">
      <div>
        <h3>红果评论任务</h3>
        <p>管理红果短剧自动评论任务、执行状态和评论结果。</p>
      </div>
      <div class="header-actions">
        <el-button @click="router.push('/hongguo/settings')">
          <el-icon><Setting /></el-icon>
          API 配置
        </el-button>
        <el-button :loading="checkingLogin" @click="handleCheckLogin">
          <el-icon><Connection /></el-icon>
          设备/登录检测
        </el-button>
        <el-button type="primary" @click="router.push('/hongguo/create')">
          <el-icon><Plus /></el-icon>
          新建任务
        </el-button>
      </div>
    </div>

    <div class="device-toolbar">
      <div class="device-control">
        <span class="device-label">红果工作设备</span>
        <el-select
          v-model="selectedDeviceAddr"
          class="device-select"
          :loading="loadingDevices"
          filterable
          placeholder="选择模拟器"
          @change="handleSelectDevice"
        >
          <el-option
            v-for="item in deviceOptions"
            :key="item.addr"
            :label="deviceOptionLabel(item)"
            :value="item.addr"
          >
            <div class="device-option">
              <span>{{ deviceOptionLabel(item) }}</span>
            </div>
          </el-option>
        </el-select>
        <el-button :loading="loadingDevices" @click="refreshDevices">
          刷新设备
        </el-button>
      </div>
      <div class="device-hint">
        {{ selectedDeviceHint }}
      </div>
    </div>

    <el-alert
      v-if="loginStatus"
      class="status-alert"
      :type="loginStatus.logged_in ? 'success' : 'warning'"
      :closable="false"
      show-icon
    >
      <template #title>
        {{ loginStatus.logged_in ? '红果已登录' : '红果未确认登录' }}
      </template>
      <template #default>
        <div class="status-detail">
          <div class="status-message">
            {{ loginStatus.message || statusText(loginStatus.status) || '请确认模拟器和红果 App 状态。' }}
          </div>
          <div class="status-row">
            <span class="status-label">当前模拟器</span>
            <span class="status-value">{{ deviceSummary(loginStatus) }}</span>
          </div>
          <div class="status-row">
            <span class="status-label">前台应用</span>
            <span class="status-value">{{ foregroundSummary(loginStatus) }}</span>
          </div>
          <div class="status-row">
            <span class="status-label">红果账号</span>
            <span class="status-value">{{ accountSummary(loginStatus) }}</span>
          </div>
        </div>
      </template>
    </el-alert>

    <el-card>
      <el-table :data="tasks" v-loading="loading" style="width: 100%">
        <el-table-column prop="id" label="ID" width="70" />
        <el-table-column prop="drama_name" label="短剧名称" min-width="180" show-overflow-tooltip />
        <el-table-column prop="comment_mode" label="模式" width="110">
          <template #default="{ row }">
            <el-tag :type="row.comment_mode === 'random' ? 'warning' : 'success'">
              {{ modeText(row.comment_mode) }}
            </el-tag>
          </template>
        </el-table-column>
        <el-table-column prop="playback_speed" label="倍速" width="90">
          <template #default="{ row }">
            {{ row.playback_speed || '1.0x' }}
          </template>
        </el-table-column>
        <el-table-column prop="status" label="状态" width="120">
          <template #default="{ row }">
            <el-tag :type="statusType(row.status)">{{ statusText(row.status) }}</el-tag>
          </template>
        </el-table-column>
        <el-table-column label="进度" width="160">
          <template #default="{ row }">
            <el-progress :percentage="calcProgress(row)" :stroke-width="10" />
          </template>
        </el-table-column>
        <el-table-column prop="comments_sent" label="已发送" width="90" />
        <el-table-column prop="comments_verified" label="已验证" width="90" />
        <el-table-column prop="created_at" label="创建时间" width="180">
          <template #default="{ row }">{{ formatTime(row.created_at) }}</template>
        </el-table-column>
        <el-table-column label="操作" width="180" fixed="right">
          <template #default="{ row }">
            <el-button size="small" @click="router.push('/hongguo/create?id=' + row.id)">编辑</el-button>
            <el-button size="small" @click="router.push('/hongguo/task/' + row.id)">查看</el-button>
            <el-button size="small" type="danger" @click="handleDelete(row.id)">删除</el-button>
          </template>
        </el-table-column>
      </el-table>
    </el-card>
  </div>
</template>

<script setup>
import { computed, ref, onMounted } from 'vue'
import { useRouter } from 'vue-router'
import { Connection, Plus, Setting } from '@element-plus/icons-vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import {
  getTasks,
  deleteTask,
  checkLogin,
  getDevices,
  getHongguoSettings,
  updateHongguoSettings,
} from '../api/hongguo'

const router = useRouter()
const tasks = ref([])
const loading = ref(false)
const checkingLogin = ref(false)
const loginStatus = ref(null)
const loadingDevices = ref(false)
const selectedDeviceAddr = ref('')
const deviceOptions = ref([])
const configuredDeviceOnline = ref(true)

const selectedDeviceHint = computed(() => {
  const selected = deviceOptions.value.find((item) => item.addr === selectedDeviceAddr.value)
  if (!selectedDeviceAddr.value) return '未选择设备时会使用系统默认模拟器。'
  if (!configuredDeviceOnline.value) return `当前配置设备不在线：${selectedDeviceAddr.value}`
  if (!selected) return `当前配置：${selectedDeviceAddr.value}`
  const device = selected.device || {}
  const parts = []
  if (device.emulator) parts.push(device.emulator)
  if (device.model) parts.push(device.model)
  if (device.current_package) parts.push(device.current_package)
  return parts.length ? parts.join(' / ') : `当前配置：${selectedDeviceAddr.value}`
})

async function loadTasks() {
  loading.value = true
  try {
    const res = await getTasks()
    tasks.value = Array.isArray(res) ? res : (res.items || res.data || [])
  } finally {
    loading.value = false
  }
}

async function handleDelete(id) {
  await ElMessageBox.confirm('确定删除这个红果评论任务吗？', '删除确认', {
    type: 'warning',
    confirmButtonText: '删除',
    cancelButtonText: '取消',
  })
  await deleteTask(id)
  ElMessage.success('删除成功')
  loadTasks()
}

async function loadDeviceSettings() {
  const settings = await getHongguoSettings()
  selectedDeviceAddr.value = settings.device_addr || ''
  configuredDeviceOnline.value = true
  deviceOptions.value = selectedDeviceAddr.value
    ? [{
        addr: selectedDeviceAddr.value,
        serial: selectedDeviceAddr.value,
        online: true,
        selected: true,
        device: { emulator: '当前默认设备' },
      }]
    : []
}

async function refreshDevices() {
  loadingDevices.value = true
  try {
    const devicesResult = await getDevices()
    selectedDeviceAddr.value = devicesResult.selected_device_addr || selectedDeviceAddr.value
    configuredDeviceOnline.value = devicesResult.configured_device_online !== false
    const onlineDevices = (devicesResult.devices || []).filter((item) => item.online)
    deviceOptions.value = onlineDevices
  } finally {
    loadingDevices.value = false
  }
}

async function handleSelectDevice(value) {
  if (!value) return
  const saved = await updateHongguoSettings({ device_addr: value })
  selectedDeviceAddr.value = saved.device_addr || value
  configuredDeviceOnline.value = true
  loginStatus.value = null
  ElMessage.success(`已切换红果工作设备：${selectedDeviceAddr.value}`)
}

async function handleCheckLogin() {
  checkingLogin.value = true
  try {
    const result = await checkLogin()
    loginStatus.value = result
    if (result.logged_in) {
      ElMessage.success(result.message || '红果登录状态正常')
    } else {
      ElMessage.warning(result.message || '暂未确认红果登录状态')
    }
  } finally {
    checkingLogin.value = false
  }
}

function calcProgress(row) {
  if (typeof row.progress_percent === 'number') return Math.round(row.progress_percent)
  if (!row.total_episodes || row.total_episodes === 0) return 0
  return Math.round((row.current_episode / row.total_episodes) * 100)
}

function modeText(mode) {
  return { random: '随机', specified: '指定' }[mode] || mode || '-'
}

function statusType(status) {
  return {
    pending: 'info',
    waiting_login: 'warning',
    running: 'primary',
    paused: 'warning',
    completed: 'success',
    failed: 'danger',
    stopped: 'warning',
  }[status] || 'info'
}

function statusText(status) {
  return {
    pending: '待执行',
    waiting_login: '等待登录',
    running: '执行中',
    paused: '已暂停',
    completed: '已完成',
    failed: '失败',
    stopped: '已停止',
  }[status] || status || '-'
}

function deviceSummary(status) {
  const device = status?.device || {}
  const parts = []
  if (device.emulator) parts.push(device.emulator)
  if (device.serial) parts.push(device.serial)
  if (device.model) parts.push(device.model)
  if (device.resolution) parts.push(device.resolution)
  return parts.length ? parts.join(' / ') : '未识别到模拟器信息'
}

function foregroundSummary(status) {
  const device = status?.device || {}
  const parts = []
  if (device.current_package) parts.push(device.current_package)
  if (device.current_activity) parts.push(device.current_activity)
  return parts.length ? parts.join(' / ') : '未识别'
}

function accountSummary(status) {
  const account = status?.account || {}
  if (!status?.logged_in && !account.logged_in) return account.message || '未确认登录'
  const parts = []
  if (account.nickname) parts.push(account.nickname)
  if (account.hongguo_id) parts.push(`红果号 ${account.hongguo_id}`)
  return parts.length ? parts.join(' / ') : (account.message || '已登录，账号信息未识别')
}

function deviceOptionLabel(item) {
  const device = item?.device || {}
  const parts = []
  if (device.emulator) parts.push(device.emulator)
  parts.push(item.addr || item.serial)
  if (device.model) parts.push(device.model)
  return parts.filter(Boolean).join(' / ')
}

function formatTime(value) {
  if (!value) return '-'
  const date = new Date(value)
  return Number.isNaN(date.getTime()) ? value : date.toLocaleString('zh-CN')
}

onMounted(() => {
  loadTasks()
  loadDeviceSettings()
})
</script>

<style scoped>
.page-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  margin-bottom: 16px;
}
.page-header h3 {
  margin: 0;
  color: var(--text-primary);
  font-size: 18px;
}
.page-header p {
  margin-top: 6px;
  color: var(--text-secondary);
  font-size: 13px;
}
.header-actions {
  display: flex;
  gap: 10px;
  align-items: center;
}
.device-toolbar {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 16px;
  padding: 12px 14px;
  margin-bottom: 16px;
  border: 1px solid var(--border-color);
  border-radius: 8px;
  background: var(--bg-secondary);
}
.device-control {
  display: flex;
  align-items: center;
  gap: 10px;
  min-width: 0;
}
.device-label {
  flex: 0 0 auto;
  color: var(--text-secondary);
  font-size: 13px;
}
.device-select {
  width: min(520px, 52vw);
}
.device-option {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 10px;
}
.device-hint {
  min-width: 220px;
  color: var(--text-secondary);
  font-size: 13px;
  text-align: right;
  word-break: break-all;
}
.status-alert {
  margin-bottom: 16px;
}
.status-detail {
  display: grid;
  gap: 6px;
  line-height: 1.5;
}
.status-message {
  color: var(--text-primary);
}
.status-row {
  display: flex;
  gap: 10px;
  align-items: flex-start;
  font-size: 13px;
}
.status-label {
  flex: 0 0 72px;
  color: var(--text-secondary);
}
.status-value {
  min-width: 0;
  color: var(--text-primary);
  word-break: break-all;
}
@media (max-width: 900px) {
  .page-header,
  .device-toolbar,
  .device-control {
    align-items: stretch;
    flex-direction: column;
  }
  .header-actions {
    flex-wrap: wrap;
  }
  .device-select {
    width: 100%;
  }
  .device-hint {
    min-width: 0;
    text-align: left;
  }
}
</style>
