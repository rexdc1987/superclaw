<template>
  <div class="task-execute">
    <div class="page-header">
      <h3>任务执行监控</h3>
      <el-button @click="router.push('/hongguo')">返回列表</el-button>
    </div>

    <template v-if="task">
      <el-card>
        <el-descriptions :column="3" border>
          <el-descriptions-item label="短剧名称">{{ task.drama_name }}</el-descriptions-item>
          <el-descriptions-item label="状态">
            <el-tag :type="statusType(task.status)">{{ statusText(task.status) }}</el-tag>
          </el-descriptions-item>
          <el-descriptions-item label="进度">
            {{ task.current_episode || 0 }}/{{ task.total_episodes || 0 }} 集
            ({{ calcProgress(task) }}%)
          </el-descriptions-item>
          <el-descriptions-item label="已发送">{{ task.comments_sent || 0 }} 条</el-descriptions-item>
          <el-descriptions-item label="已验证">{{ task.comments_verified || 0 }} 条</el-descriptions-item>
          <el-descriptions-item label="播放倍速">{{ task.playback_speed || '1.0x' }}</el-descriptions-item>
          <el-descriptions-item label="创建时间">{{ formatTime(displayCreatedAt) }}</el-descriptions-item>
          <el-descriptions-item label="启动时间">{{ formatTime(displayStartedAt) }}</el-descriptions-item>
          <el-descriptions-item label="完成时间">{{ formatTime(displayCompletedAt) }}</el-descriptions-item>
          <el-descriptions-item label="刷新状态">
            <el-tag :type="autoRefreshing ? 'success' : 'info'">{{ autoRefreshing ? '自动刷新中' : '手动刷新' }}</el-tag>
          </el-descriptions-item>
          <el-descriptions-item v-if="task.error_message" label="错误信息" :span="3">
            <el-text type="danger">{{ task.error_message }}</el-text>
          </el-descriptions-item>
        </el-descriptions>

        <div class="plan-panel">
          <div class="plan-row">
            <span class="plan-label">评论规则</span>
            <span>{{ ruleSummary }}</span>
          </div>
          <div class="plan-row">
            <span class="plan-label">本次评论集数计划</span>
            <span>{{ commentPlanSummary }}</span>
          </div>
        </div>

        <div class="actions">
          <el-button type="primary" @click="handleStart" :disabled="!canStart || actionLoading">启动</el-button>
          <el-button type="warning" @click="handlePause" :disabled="!canPause || actionLoading">暂停</el-button>
          <el-button type="success" @click="handleResume" :disabled="!canResume || actionLoading">恢复</el-button>
          <el-button type="danger" @click="handleStop" :disabled="!canStop || actionLoading">停止</el-button>
          <el-button :icon="Refresh" circle :loading="loading" @click="loadData" />
        </div>
      </el-card>

      <el-card class="process-card">
        <div class="process-header">
          <span>执行过程</span>
          <span class="muted">{{ latestLogTime }}</span>
        </div>
        <div v-if="latestLog" class="latest-log" :class="'level-' + latestLog.level">
          <el-tag :type="latestLog.level === 'error' ? 'danger' : latestLog.level === 'warn' ? 'warning' : 'success'">
            {{ latestLog.level }}
          </el-tag>
          <span>{{ latestLog.message }}</span>
        </div>
        <el-empty v-else description="暂无执行日志" />
      </el-card>

      <div class="detail-grid">
        <el-card>
          <div class="section-header">
            <span>评论记录</span>
          </div>
          <el-table :data="records" v-loading="loading">
            <el-table-column prop="episode_number" label="集数" width="90" />
            <el-table-column prop="comment_text" label="评论内容" min-width="260" show-overflow-tooltip />
            <el-table-column label="图片" width="110">
              <template #default="{ row }">
                <el-image
                  v-if="recordScreenshot(row)"
                  :src="recordScreenshot(row)"
                  :preview-src-list="[recordScreenshot(row)]"
                  fit="cover"
                  class="record-shot"
                />
                <span v-else>-</span>
              </template>
            </el-table-column>
            <el-table-column prop="generated_by" label="来源" width="100" />
            <el-table-column prop="status" label="状态" width="110">
              <template #default="{ row }">
                <el-tag :type="recordStatusType(row.status)">{{ recordStatusText(row.status) }}</el-tag>
              </template>
            </el-table-column>
            <el-table-column prop="created_at" label="时间" width="180">
              <template #default="{ row }">{{ formatTime(row.created_at) }}</template>
            </el-table-column>
          </el-table>
        </el-card>

        <el-card>
          <div class="section-header">
            <span>执行日志</span>
            <span class="muted">{{ logs.length }} 条</span>
          </div>
          <div class="log-scroll">
            <el-table :data="logs" v-loading="loading">
              <el-table-column prop="level" label="级别" width="90">
                <template #default="{ row }">
                  <el-tag :type="row.level === 'error' ? 'danger' : row.level === 'warn' ? 'warning' : 'success'">
                    {{ row.level }}
                  </el-tag>
                </template>
              </el-table-column>
              <el-table-column prop="message" label="消息" min-width="280" show-overflow-tooltip />
              <el-table-column prop="created_at" label="时间" width="180">
                <template #default="{ row }">{{ formatTime(row.created_at) }}</template>
              </el-table-column>
            </el-table>
          </div>
        </el-card>
      </div>
    </template>

    <el-card v-else v-loading="loading">
      <el-empty description="正在加载任务..." />
    </el-card>
  </div>
</template>

<script setup>
import { computed, ref, onMounted, onUnmounted, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { Refresh } from '@element-plus/icons-vue'
import { ElMessage } from 'element-plus'
import { getTask, startTask, pauseTask, resumeTask, stopTask, getRecords, getLogs } from '../api/hongguo'

const route = useRoute()
const router = useRouter()
const task = ref(null)
const records = ref([])
const logs = ref([])
const loading = ref(false)
const actionLoading = ref(false)
const refreshTimer = ref(null)

const normalizedStatus = computed(() => {
  const status = task.value?.status
  return status || 'pending'
})

const canStart = computed(() => ['pending', 'failed', 'stopped', 'waiting_login', 'completed'].includes(normalizedStatus.value))
const canPause = computed(() => normalizedStatus.value === 'running')
const canResume = computed(() => normalizedStatus.value === 'paused')
const canStop = computed(() => ['running', 'paused', 'waiting_login'].includes(normalizedStatus.value))
const autoRefreshing = computed(() => ['running', 'paused', 'waiting_login'].includes(normalizedStatus.value))
const latestLog = computed(() => logs.value[0] || null)
const latestLogTime = computed(() => latestLog.value ? formatTime(latestLog.value.created_at) : '-')
const displayCreatedAt = computed(() => task.value?.created_at || '')
const displayStartedAt = computed(() => task.value?.started_at || '')
const displayCompletedAt = computed(() => task.value?.completed_at || '')
const executionPlan = computed(() => {
  const value = task.value?.execution_plan
  if (value && typeof value === 'object' && !Array.isArray(value)) return value
  return {}
})
const ruleSummary = computed(() => {
  const t = task.value || {}
  const rule = executionPlan.value.rule || {}
  const mode = rule.comment_mode || t.comment_mode
  const source = rule.content_source || t.content_source || 'ai'
  const speed = rule.playback_speed || t.playback_speed || '1.0x'
  if (mode === 'random') {
    const count = rule.random_comment_count ?? t.random_comment_count ?? '-'
    const min = rule.random_min_interval ?? t.random_min_interval ?? '-'
    const max = rule.random_max_interval ?? t.random_max_interval ?? '-'
    return `随机评论 ${count} 次，间隔 ${min}-${max} 秒，内容 ${source}，倍速 ${speed}`
  }
  const start = rule.start_episode ?? t.start_episode ?? 1
  const interval = rule.episode_interval ?? t.episode_interval ?? 1
  const delay = rule.comment_interval_sec ?? t.comment_interval_sec ?? 0
  return `从第 ${start} 集开始，每隔 ${interval} 集评论，固定等待 ${delay} 秒，内容 ${source}，倍速 ${speed}`
})
const commentPlanSummary = computed(() => {
  const episodes = executionPlan.value.comment_episodes
  if (!Array.isArray(episodes) || episodes.length === 0) return '-'
  return episodes.map((item) => `第${item}集`).join('、')
})

async function loadData() {
  loading.value = true
  try {
    const id = route.params.id
    task.value = await getTask(id)
    const recordsRes = await getRecords(id).catch(() => ({ items: [] }))
    records.value = (Array.isArray(recordsRes) ? recordsRes : (recordsRes.items || recordsRes.data || []))
      .slice()
      .sort((a, b) => {
        const timeA = new Date(a.created_at || 0).getTime()
        const timeB = new Date(b.created_at || 0).getTime()
        if (timeA !== timeB) return timeB - timeA
        return Number(b.id || 0) - Number(a.id || 0)
      })
    const logsRes = await getLogs(id).catch(() => ({ items: [] }))
    logs.value = Array.isArray(logsRes) ? logsRes : (logsRes.items || logsRes.data || [])
  } finally {
    loading.value = false
  }
}

async function runAction(action, successText) {
  actionLoading.value = true
  try {
    await action(route.params.id)
    ElMessage.success(successText)
    await loadData()
  } finally {
    actionLoading.value = false
  }
}

const handleStart = () => runAction(startTask, '任务已启动')
const handlePause = () => runAction(pauseTask, '任务已暂停')
const handleResume = () => runAction(resumeTask, '任务已恢复')
const handleStop = () => runAction(stopTask, '任务已停止')

function calcProgress(t) {
  if (typeof t.progress_percent === 'number') return Math.round(t.progress_percent)
  if (!t.total_episodes || t.total_episodes === 0) return 0
  return Math.round((t.current_episode / t.total_episodes) * 100)
}

function syncRefreshTimer() {
  if (refreshTimer.value) {
    clearInterval(refreshTimer.value)
    refreshTimer.value = null
  }
  if (autoRefreshing.value) {
    refreshTimer.value = setInterval(() => {
      loadData()
    }, 2000)
  }
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

function recordStatusType(status) {
  return {
    success: 'success',
    verified: 'success',
    sent: 'primary',
    sending: 'info',
    failed: 'danger',
    skipped: 'warning',
  }[status] || 'info'
}

function recordStatusText(status) {
  return {
    success: '成功',
    verified: '已验证',
    sent: '已发送',
    sending: '发送中',
    failed: '失败',
    skipped: '跳过',
  }[status] || status || '-'
}

function recordScreenshot(row) {
  return row.screenshot_verified_url || row.screenshot_sent_url || row.screenshot_input_url || ''
}

function formatTime(value) {
  if (!value) return '-'
  const date = new Date(value)
  return Number.isNaN(date.getTime())
    ? value
    : date.toLocaleString('zh-CN', { timeZone: 'Asia/Shanghai' })
}

onMounted(async () => {
  await loadData()
  syncRefreshTimer()
})

watch(autoRefreshing, syncRefreshTimer)

onUnmounted(() => {
  if (refreshTimer.value) clearInterval(refreshTimer.value)
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
.actions {
  margin-top: 18px;
  display: flex;
  gap: 10px;
}
.plan-panel {
  margin-top: 14px;
  display: grid;
  gap: 8px;
  padding: 10px 12px;
  border: 1px solid var(--border-color);
  border-radius: 6px;
  background: var(--bg-secondary);
}
.plan-row {
  display: grid;
  grid-template-columns: 130px minmax(0, 1fr);
  gap: 10px;
  line-height: 1.5;
}
.plan-label {
  color: var(--text-secondary);
  font-weight: 600;
}
.detail-tabs {
  margin-top: 18px;
}
.process-card {
  margin-top: 18px;
}
.section-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  margin-bottom: 12px;
  font-weight: 600;
}
.detail-grid {
  margin-top: 18px;
  display: grid;
  grid-template-columns: minmax(0, 1.2fr) minmax(320px, 0.8fr);
  gap: 18px;
  align-items: start;
}
.log-scroll {
  max-height: 420px;
  overflow: auto;
}
.muted {
  color: var(--text-secondary);
  font-size: 13px;
  font-weight: 400;
}
.latest-log {
  display: flex;
  align-items: center;
  gap: 10px;
  min-height: 36px;
  padding: 10px 12px;
  border: 1px solid var(--border-color);
  border-radius: 6px;
  background: var(--bg-secondary);
}
.latest-log span:last-child {
  line-height: 1.5;
}
.level-error {
  border-color: #f56c6c;
}
.record-shot {
  width: 72px;
  height: 48px;
  border-radius: 4px;
  overflow: hidden;
  cursor: zoom-in;
}
@media (max-width: 1100px) {
  .detail-grid {
    grid-template-columns: 1fr;
  }
}
</style>
