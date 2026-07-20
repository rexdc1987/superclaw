<template>
  <div class="hongguo-multi">
    <div class="page-header">
      <div>
        <h3>红果多开</h3>
        <p>检测当前开启的 MuMu 实例和红果账号，按实例批量创建并同时执行任务。</p>
      </div>
      <div class="header-actions">
        <el-button :loading="loadingDevices" @click="detectDevices">
          <el-icon><Connection /></el-icon>
          检测实例/登录
        </el-button>
        <el-button :loading="loadingRuns" @click="loadRuns">
          <el-icon><Refresh /></el-icon>
          刷新批次
        </el-button>
      </div>
    </div>

    <div class="summary-grid">
      <div class="summary-item">
        <span class="summary-label">在线实例</span>
        <strong>{{ deviceSummary.online }}</strong>
      </div>
      <div class="summary-item">
        <span class="summary-label">已登录</span>
        <strong>{{ deviceSummary.loggedIn }}</strong>
      </div>
      <div class="summary-item">
        <span class="summary-label">已选实例</span>
        <strong>{{ selectedDevices.length }}</strong>
      </div>
      <div class="summary-item">
        <span class="summary-label">当前批次</span>
        <strong>{{ activeRun?.run_id || '-' }}</strong>
      </div>
    </div>

    <div class="workbench">
      <el-card class="device-panel">
        <template #header>
          <div class="card-header">
            <span>实例与账号</span>
            <el-tag type="info">{{ devices.length }} 台</el-tag>
          </div>
        </template>
        <el-table
          ref="deviceTableRef"
          :data="devices"
          v-loading="loadingDevices"
          row-key="addr"
          height="360"
          @selection-change="selectedDevices = $event"
        >
          <el-table-column type="selection" width="44" :selectable="isDeviceSelectable" />
          <el-table-column label="实例" min-width="220" show-overflow-tooltip>
            <template #default="{ row }">
              <div class="device-title">{{ row.label || row.addr }}</div>
              <div class="device-sub">{{ row.worker_name ? row.worker_name + ' / ' : '' }}{{ row.addr }}</div>
            </template>
          </el-table-column>
          <el-table-column label="登录" width="100">
            <template #default="{ row }">
              <el-tag :type="loginTagType(row)">
                {{ loginTagText(row) }}
              </el-tag>
            </template>
          </el-table-column>
          <el-table-column label="账号" min-width="160" show-overflow-tooltip>
            <template #default="{ row }">{{ accountText(row) }}</template>
          </el-table-column>
          <el-table-column label="前台" min-width="150" show-overflow-tooltip>
            <template #default="{ row }">{{ row.device?.current_package || '-' }}</template>
          </el-table-column>
          <el-table-column label="ADB端口" min-width="130" show-overflow-tooltip>
            <template #default="{ row }">{{ adbPortText(row) }}</template>
          </el-table-column>
        </el-table>
      </el-card>

      <el-card class="rule-panel">
        <template #header>
          <div class="card-header">
            <span>执行规则</span>
            <el-tag>{{ form.playback_speed }}</el-tag>
          </div>
        </template>
        <el-form :model="form" label-width="112px">
          <el-form-item label="搜索剧名" required>
            <el-input v-model.trim="form.drama_name" placeholder="例如：一品布衣2" />
          </el-form-item>
          <el-form-item label="评论模式">
            <el-radio-group v-model="form.comment_mode">
              <el-radio value="specified">指定集数</el-radio>
              <el-radio value="random">随机集数</el-radio>
            </el-radio-group>
          </el-form-item>
          <template v-if="form.comment_mode === 'specified'">
            <el-form-item label="起始集数">
              <el-input-number v-model="form.start_episode" :min="1" />
            </el-form-item>
            <el-form-item label="集数间隔">
              <el-input-number v-model="form.episode_interval" :min="1" />
            </el-form-item>
            <el-form-item label="评论间隔">
              <el-input-number v-model="form.comment_interval_sec" :min="1" />
              <span class="field-hint">秒</span>
            </el-form-item>
          </template>
          <template v-else>
            <el-form-item label="评论次数">
              <el-input-number v-model="form.random_comment_count" :min="1" />
            </el-form-item>
            <el-form-item label="最小间隔">
              <el-input-number v-model="form.random_min_interval" :min="1" />
              <span class="field-hint">秒</span>
            </el-form-item>
            <el-form-item label="最大间隔">
              <el-input-number v-model="form.random_max_interval" :min="1" />
              <span class="field-hint">秒</span>
            </el-form-item>
          </template>
          <el-form-item label="内容来源">
            <el-radio-group v-model="form.content_source">
              <el-radio value="ai">AI 生成</el-radio>
              <el-radio value="template">模板抽取</el-radio>
              <el-radio value="mixed">混合</el-radio>
            </el-radio-group>
          </el-form-item>
          <el-form-item label="刷剧倍速">
            <el-select v-model="form.playback_speed" style="width: 160px">
              <el-option v-for="item in playbackSpeedOptions" :key="item.value" :label="item.label" :value="item.value" />
            </el-select>
          </el-form-item>
          <el-form-item label="评论模板">
            <el-input v-model="templateText" type="textarea" :rows="4" placeholder="每行一条评论模板" />
          </el-form-item>
          <el-form-item>
            <el-button type="primary" :loading="creating" @click="createRun">
              <el-icon><Plus /></el-icon>
              创建批次
            </el-button>
            <el-button type="success" :disabled="!activeRun" :loading="starting" @click="startRun">
              <el-icon><VideoPlay /></el-icon>
              启动批次
            </el-button>
            <el-button type="danger" :disabled="!activeRun" :loading="stopping" @click="stopRun">
              停止批次
            </el-button>
          </el-form-item>
        </el-form>
      </el-card>
    </div>

    <el-card class="run-panel">
      <template #header>
        <div class="card-header">
          <span>实例执行统计</span>
          <div class="run-actions">
            <el-select v-model="activeRunId" placeholder="选择批次" filterable clearable style="width: 280px" @change="loadRunDetail">
              <el-option v-for="run in runs" :key="run.run_id" :label="runLabel(run)" :value="run.run_id" />
            </el-select>
            <el-button :disabled="!activeRun" @click="reuseRuleFromActiveRun">复用规则</el-button>
            <el-button :disabled="!activeRun" :loading="rebuilding" type="primary" @click="rebuildRunFromActiveRun">按此批次重建</el-button>
            <el-button :disabled="!activeRunId" :loading="loadingRunDetail" @click="loadRunDetail(activeRunId)">刷新统计</el-button>
          </div>
        </div>
      </template>
      <div v-if="activeRun" class="run-summary">
        <el-tag>任务 {{ activeRun.task_count }}</el-tag>
        <el-tag type="primary">运行 {{ activeRun.running_count }}</el-tag>
        <el-tag type="success">完成 {{ activeRun.completed_count }}</el-tag>
        <el-tag type="danger">失败 {{ activeRun.failed_count }}</el-tag>
        <el-tag type="info">已发 {{ activeRun.comments_sent }}</el-tag>
        <el-tag type="success">已验证 {{ activeRun.comments_verified }}</el-tag>
      </div>
      <el-table :data="activeRun?.tasks || []" v-loading="loadingRunDetail" style="width: 100%">
        <el-table-column prop="id" label="任务" width="80" />
        <el-table-column label="实例" min-width="230" show-overflow-tooltip>
          <template #default="{ row }">
            <div class="device-title">{{ row.device_label || row.device_addr || '-' }}</div>
            <div class="device-sub">{{ row.worker_id ? row.worker_id + ' / ' : '' }}{{ row.device_addr || '-' }}</div>
          </template>
        </el-table-column>
        <el-table-column prop="drama_name" label="短剧" min-width="150" show-overflow-tooltip />
        <el-table-column label="状态" width="110">
          <template #default="{ row }">
            <el-tag :type="statusType(row.status)">{{ statusText(row.status) }}</el-tag>
          </template>
        </el-table-column>
        <el-table-column label="当前集" width="90">
          <template #default="{ row }">{{ row.current_episode || 0 }}</template>
        </el-table-column>
        <el-table-column label="总集数" width="90">
          <template #default="{ row }">{{ row.total_episodes || '-' }}</template>
        </el-table-column>
        <el-table-column label="计划评论" min-width="130" show-overflow-tooltip>
          <template #default="{ row }">{{ plannedCommentText(row) }}</template>
        </el-table-column>
        <el-table-column label="评论" width="120">
          <template #default="{ row }">{{ row.comments_sent || 0 }} / {{ row.comments_verified || 0 }}</template>
        </el-table-column>
        <el-table-column label="最近过程" min-width="220" show-overflow-tooltip>
          <template #default="{ row }">{{ latestLogText(row.id) }}</template>
        </el-table-column>
        <el-table-column prop="error_message" label="错误" min-width="180" show-overflow-tooltip />
        <el-table-column label="操作" width="150">
          <template #default="{ row }">
            <el-button size="small" :loading="loadingLogs && selectedLogTaskId === row.id" @click="loadTaskLogs(row.id)">日志</el-button>
            <el-button size="small" @click="router.push('/hongguo/task/' + row.id)">查看</el-button>
          </template>
        </el-table-column>
      </el-table>
      <div v-if="selectedLogTaskId" class="process-panel">
        <div class="process-header">
          <strong>任务 {{ selectedLogTaskId }} 执行过程</strong>
          <el-button text @click="selectedLogTaskId = null">收起</el-button>
        </div>
        <el-timeline>
          <el-timeline-item
            v-for="item in taskLogs[selectedLogTaskId] || []"
            :key="item.id"
            :type="logType(item.level)"
            :timestamp="formatTime(item.created_at)"
          >
            <span class="log-level">{{ item.level }}</span>
            <span>{{ item.message }}</span>
          </el-timeline-item>
        </el-timeline>
      </div>
    </el-card>
  </div>
</template>

<script setup>
import { computed, nextTick, onBeforeUnmount, onMounted, reactive, ref } from 'vue'
import { useRouter } from 'vue-router'
import { Connection, Plus, Refresh, VideoPlay } from '@element-plus/icons-vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import {
  createMultiTasks,
  getMultiDevices,
  getMultiRun,
  getMultiRuns,
  getLogs,
  startMultiRun,
  stopMultiRun,
} from '../api/hongguo'

const router = useRouter()
const deviceTableRef = ref(null)
const devices = ref([])
const selectedDevices = ref([])
const runs = ref([])
const activeRunId = ref('')
const activeRun = ref(null)
const loadingDevices = ref(false)
const loadingRuns = ref(false)
const loadingRunDetail = ref(false)
const creating = ref(false)
const starting = ref(false)
const stopping = ref(false)
const rebuilding = ref(false)
const loadingLogs = ref(false)
const templateText = ref('')
const selectedLogTaskId = ref(null)
const taskLogs = ref({})
let pollTimer = null

const form = reactive({
  drama_name: '',
  comment_mode: 'specified',
  start_episode: 1,
  episode_interval: 2,
  comment_interval_sec: 30,
  random_comment_count: 10,
  random_min_interval: 20,
  random_max_interval: 60,
  content_source: 'ai',
  playback_speed: '2.0x',
  templates: [],
})

const playbackSpeedOptions = [
  { label: '0.75x', value: '0.75x' },
  { label: '1.0x', value: '1.0x' },
  { label: '1.25x', value: '1.25x' },
  { label: '1.5x', value: '1.5x' },
  { label: '2.0x', value: '2.0x' },
  { label: '3.0x', value: '3.0x' },
]

const deviceSummary = computed(() => ({
  online: devices.value.filter((item) => item.online).length,
  loggedIn: devices.value.filter((item) => item.logged_in).length,
}))

function isDeviceSelectable(row) {
  return Boolean(row.online && row.logged_in && !row.leased_by_other)
}

function loginTagType(row) {
  if (row.leased_by_other) return 'info'
  if (row.logged_in) return 'success'
  if (row.status === 'adb_not_ready' || row.status === 'login_check_timeout') return 'danger'
  return 'warning'
}

function loginTagText(row) {
  if (row.leased_by_other) return '占用中'
  if (row.logged_in) return '已登录'
  if (row.status === 'adb_not_ready') return 'ADB未就绪'
  if (row.status === 'login_check_timeout') return '检测超时'
  if (row.online) return '未登录'
  return '未就绪'
}

function adbPortText(row) {
  const ports = row.mumu_instance?.configured_adb_ports || []
  if (ports.length) return ports.join(', ')
  const addr = row.addr || row.mumu_instance?.addr || ''
  const port = String(addr).split(':').pop()
  return port && port !== addr ? port : '-'
}

function accountText(row) {
  const account = row.account || {}
  if (!row.logged_in && !account.logged_in) {
    return row.message || account.message || '请先登录红果账号'
  }
  const parts = []
  if (account.hongguo_id) parts.push(`红果号 ${account.hongguo_id}`)
  return parts.join(' / ') || account.message || row.message || '已登录'
}

async function detectDevices() {
  loadingDevices.value = true
  try {
    const result = await getMultiDevices()
    devices.value = result.devices || []
    selectedDevices.value = []
    await nextTick()
    devices.value.forEach((item) => {
      if (isDeviceSelectable(item)) deviceTableRef.value?.toggleRowSelection(item, true)
    })
    ElMessage.success(`检测完成：在线 ${result.online_count || 0} 台，已登录 ${result.logged_in_count || 0} 台`)
    const ignoredDevices = result.ignored_devices || []
    if (ignoredDevices.length) {
      const lines = ignoredDevices.map((item) => `${item.label || item.addr}：${item.ignore_reason || '非 MuMu 实例，已忽略'}`)
      await ElMessageBox.alert(lines.join('\n'), '已忽略非 MuMu ADB 设备', {
        type: 'info',
        confirmButtonText: '知道了',
      })
    }
    const needLogin = devices.value.filter((item) => item.online && !item.logged_in)
    if (needLogin.length) {
      const lines = needLogin.map((item) => `${item.label || item.addr}：${item.message || item.account?.message || '请先登录红果账号'}`)
      await ElMessageBox.alert(lines.join('\n'), '以下实例需要登录', {
        type: 'warning',
        confirmButtonText: '知道了',
      })
    }
  } finally {
    loadingDevices.value = false
  }
}

async function createRun() {
  if (!form.drama_name.trim()) {
    ElMessage.warning('请输入短剧名称')
    return
  }
  if (!selectedDevices.value.length) {
    ElMessage.warning('请选择已登录实例')
    return
  }
  if (form.comment_mode === 'random' && form.random_min_interval > form.random_max_interval) {
    ElMessage.warning('最大间隔必须大于等于最小间隔')
    return
  }
  creating.value = true
  try {
    const payload = {
      ...form,
      drama_name: form.drama_name.trim(),
      templates: templateText.value.split('\n').map((item) => item.trim()).filter(Boolean),
      devices: selectedDevices.value.map((item) => ({
        addr: item.addr,
        label: item.label || item.addr,
        worker_id: item.worker_id || null,
      })),
    }
    const result = await createMultiTasks(payload)
    activeRunId.value = result.run_id
    activeRun.value = { run_id: result.run_id, tasks: result.tasks || [] }
    ElMessage.success(`批次已创建：${result.run_id}`)
    await loadRuns()
    await loadRunDetail(result.run_id)
  } finally {
    creating.value = false
  }
}

async function startRun() {
  if (!activeRunId.value) return
  await ElMessageBox.confirm('确认同时启动当前批次的所有实例任务吗？', '启动确认', {
    type: 'warning',
    confirmButtonText: '启动',
    cancelButtonText: '取消',
  })
  starting.value = true
  startPolling()
  try {
    const result = await startMultiRun(activeRunId.value)
    activeRun.value = result
    if (result.success) {
      ElMessage.success(`已启动 ${result.started_count || 0} 个实例任务`)
    } else {
      ElMessage.warning(`部分启动失败，已启动 ${result.started_count || 0} 个`)
    }
    await refreshVisibleLogs()
  } catch (error) {
    const timedOut = error?.code === 'ECONNABORTED' || String(error?.message || '').includes('timeout')
    if (timedOut) {
      ElMessage.warning('启动请求仍在后台执行，已继续刷新批次状态和日志')
      await loadRuns()
      await loadRunDetail(activeRunId.value)
      startPolling()
      return
    }
    throw error
  } finally {
    starting.value = false
  }
}

async function stopRun() {
  if (!activeRunId.value) return
  await ElMessageBox.confirm('确认停止当前批次所有实例任务吗？', '停止确认', {
    type: 'warning',
    confirmButtonText: '停止',
    cancelButtonText: '取消',
  })
  stopping.value = true
  try {
    const result = await stopMultiRun(activeRunId.value)
    activeRun.value = result
    ElMessage.success('批次已停止')
  } finally {
    stopping.value = false
  }
}

async function loadRuns() {
  loadingRuns.value = true
  try {
    const result = await getMultiRuns()
    runs.value = result.runs || []
    if (!activeRunId.value && runs.value.length) {
      activeRunId.value = runs.value[0].run_id
      await loadRunDetail(activeRunId.value)
    }
  } finally {
    loadingRuns.value = false
  }
}

async function loadRunDetail(runId = activeRunId.value) {
  if (!runId) {
    activeRun.value = null
    return
  }
  loadingRunDetail.value = true
  try {
    activeRun.value = await getMultiRun(runId)
    activeRunId.value = runId
    await refreshVisibleLogs()
  } finally {
    loadingRunDetail.value = false
  }
}

function ruleFromTask(task) {
  return {
    drama_name: task?.drama_name || '',
    comment_mode: task?.comment_mode || 'specified',
    start_episode: task?.start_episode || 1,
    episode_interval: task?.episode_interval || 2,
    comment_interval_sec: task?.comment_interval_sec || 30,
    random_comment_count: task?.random_comment_count || 10,
    random_min_interval: task?.random_min_interval || 20,
    random_max_interval: task?.random_max_interval || 60,
    content_source: task?.content_source || 'ai',
    playback_speed: task?.playback_speed || '2.0x',
    templates: task?.templates || [],
  }
}

function reuseRuleFromActiveRun() {
  const task = activeRun.value?.tasks?.[0]
  if (!task) {
    ElMessage.warning('当前批次没有可复用的规则')
    return
  }
  Object.assign(form, ruleFromTask(task))
  templateText.value = (task.templates || []).join('\n')
  ElMessage.success('已复用当前批次规则')
}

async function rebuildRunFromActiveRun() {
  const tasks = activeRun.value?.tasks || []
  if (!tasks.length) {
    ElMessage.warning('当前批次没有可重建的任务')
    return
  }
  rebuilding.value = true
  try {
    const rule = ruleFromTask(tasks[0])
    const payload = {
      ...rule,
      devices: tasks
        .filter((item) => item.device_addr)
        .map((item) => ({
          addr: item.device_addr,
          label: item.device_label || item.device_addr,
          worker_id: item.worker_id || null,
        })),
    }
    if (!payload.devices.length) {
      ElMessage.warning('当前批次没有可复用的设备')
      return
    }
    const result = await createMultiTasks(payload)
    activeRunId.value = result.run_id
    activeRun.value = { run_id: result.run_id, tasks: result.tasks || [] }
    ElMessage.success(`已按原规则重建批次：${result.run_id}`)
    await loadRuns()
    await loadRunDetail(result.run_id)
  } finally {
    rebuilding.value = false
  }
}

async function loadTaskLogs(taskId) {
  if (!taskId) return
  selectedLogTaskId.value = taskId
  loadingLogs.value = true
  try {
    const result = await getLogs(taskId, { limit: 80, current_run_only: true })
    taskLogs.value = { ...taskLogs.value, [taskId]: Array.isArray(result) ? result : (result.value || []) }
  } finally {
    loadingLogs.value = false
  }
}

async function refreshVisibleLogs() {
  const tasks = activeRun.value?.tasks || []
  const targets = tasks.slice(0, 6)
  await Promise.all(targets.map(async (task) => {
    try {
      const result = await getLogs(task.id, { limit: 8, current_run_only: true })
      taskLogs.value = { ...taskLogs.value, [task.id]: Array.isArray(result) ? result : (result.value || []) }
    } catch (error) {
      // Ignore per-task log refresh failures; the main run state is still useful.
    }
  }))
}

function startPolling() {
  stopPolling()
  pollTimer = window.setInterval(async () => {
    if (!activeRunId.value) return
    await loadRunDetail(activeRunId.value)
    const running = (activeRun.value?.tasks || []).some((item) => item.status === 'running')
    if (!running) stopPolling()
  }, 5000)
}

function stopPolling() {
  if (pollTimer) window.clearInterval(pollTimer)
  pollTimer = null
}

function runLabel(run) {
  return `${run.run_id}｜${run.task_count}台｜运行${run.running_count}｜完成${run.completed_count}｜失败${run.failed_count}`
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

function plannedCommentText(row) {
  const plan = row.execution_plan || {}
  const episodes = Array.isArray(plan.comment_episodes) ? plan.comment_episodes : []
  if (episodes.length) {
    const preview = episodes.slice(0, 8).join(', ')
    return episodes.length > 8 ? `${preview} ... 共${episodes.length}集` : preview
  }
  if (row.comment_mode === 'random') return `随机 ${row.random_comment_count || 0} 次`
  return `从${row.start_episode || 1}起，每${row.episode_interval || 1}集`
}

function latestLogText(taskId) {
  const logs = taskLogs.value[taskId] || []
  return logs[0]?.message || '暂无日志'
}

function logType(level) {
  return {
    error: 'danger',
    warn: 'warning',
    info: 'primary',
  }[level] || 'info'
}

function formatTime(value) {
  if (!value) return '-'
  const date = new Date(value)
  return Number.isNaN(date.getTime()) ? value : date.toLocaleString('zh-CN')
}

onMounted(() => {
  loadRuns()
})

onBeforeUnmount(stopPolling)
</script>

<style scoped>
.page-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 16px;
  margin-bottom: 16px;
}
.page-header h3 {
  margin: 0;
  color: var(--text-primary);
  font-size: 18px;
}
.page-header p {
  margin: 6px 0 0;
  color: var(--text-secondary);
  font-size: 13px;
}
.header-actions,
.run-actions {
  display: flex;
  align-items: center;
  gap: 10px;
}
.summary-grid {
  display: grid;
  grid-template-columns: repeat(4, minmax(140px, 1fr));
  gap: 12px;
  margin-bottom: 16px;
}
.summary-item {
  min-height: 72px;
  padding: 14px 16px;
  border: 1px solid var(--border-color);
  border-radius: 8px;
  background: var(--bg-secondary);
}
.summary-label {
  display: block;
  margin-bottom: 8px;
  color: var(--text-secondary);
  font-size: 13px;
}
.summary-item strong {
  color: var(--text-primary);
  font-size: 20px;
}
.workbench {
  display: grid;
  grid-template-columns: minmax(0, 1.15fr) minmax(360px, 0.85fr);
  gap: 16px;
  margin-bottom: 16px;
}
.card-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
}
.device-title {
  color: var(--text-primary);
  font-weight: 600;
}
.device-sub {
  margin-top: 2px;
  color: var(--text-secondary);
  font-size: 12px;
}
.field-hint {
  margin-left: 8px;
  color: var(--text-secondary);
  font-size: 13px;
}
.run-panel {
  margin-bottom: 20px;
}
.run-summary {
  display: flex;
  flex-wrap: wrap;
  gap: 8px;
  margin-bottom: 12px;
}
.process-panel {
  margin-top: 14px;
  padding: 14px 16px;
  border: 1px solid var(--border-color);
  border-radius: 8px;
  background: var(--bg-secondary);
}
.process-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  margin-bottom: 12px;
  color: var(--text-primary);
}
.log-level {
  display: inline-block;
  min-width: 46px;
  margin-right: 8px;
  color: var(--text-secondary);
  text-transform: uppercase;
}
@media (max-width: 1180px) {
  .workbench,
  .summary-grid {
    grid-template-columns: 1fr;
  }
}
@media (max-width: 760px) {
  .page-header,
  .header-actions,
  .card-header,
  .run-actions {
    align-items: stretch;
    flex-direction: column;
  }
}
</style>
