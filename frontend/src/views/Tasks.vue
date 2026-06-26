<template>
  <div class="tasks-page">
    <div class="page-header">
      <div class="header-left">
        <el-select v-model="statusFilter" placeholder="全部状态" clearable style="width: 120px" @change="loadTasks">
          <el-option label="全部" value="" />
          <el-option v-for="(label, key) in statusLabels" :key="key" :label="label" :value="key" />
        </el-select>
      </div>
      <el-button type="primary" @click="showDialog()">
        <el-icon><Plus /></el-icon> 创建任务
      </el-button>
    </div>

    <el-card>
      <el-table :data="tasks" style="width: 100%" v-loading="loading" @row-click="showDetail">
        <el-table-column prop="id" label="ID" width="60" />
        <el-table-column prop="name" label="名称" min-width="150" show-overflow-tooltip />
        <el-table-column prop="platform" label="平台" width="80">
          <template #default="{ row }">
            <el-tag size="small">{{ platformLabels[row.platform] || row.platform }}</el-tag>
          </template>
        </el-table-column>
        <el-table-column prop="status" label="状态" width="90">
          <template #default="{ row }">
            <el-tag :type="getStatusTagType(row.status)" size="small">
              {{ statusLabels[row.status] || row.status }}
            </el-tag>
          </template>
        </el-table-column>
        <el-table-column label="进度" width="120">
          <template #default="{ row }">
            <el-progress :percentage="getProgress(row)" :stroke-width="6" />
          </template>
        </el-table-column>
        <el-table-column prop="created_at" label="创建时间" width="150">
          <template #default="{ row }">
            {{ formatTime(row.created_at) }}
          </template>
        </el-table-column>
        <el-table-column label="操作" width="280" fixed="right">
          <template #default="{ row }">
            <div class="action-buttons">
              <!-- draft: 可启动、可编辑、可删除 -->
              <el-button v-if="row.status === 'draft'" type="primary" size="small" @click.stop="handleStart(row)">
                启动
              </el-button>
              <!-- pending: 可启动、可取消 -->
              <el-button v-if="row.status === 'pending'" type="success" size="small" @click.stop="handleStart(row)">
                开始
              </el-button>
              <!-- running: 可暂停、可取消 -->
              <el-button v-if="row.status === 'running'" type="warning" size="small" @click.stop="handlePause(row)">
                暂停
              </el-button>
              <el-button v-if="row.status === 'running'" type="danger" size="small" @click.stop="handleCancel(row)">
                取消
              </el-button>
              <!-- paused: 可继续、可取消 -->
              <el-button v-if="row.status === 'paused'" type="success" size="small" @click.stop="handleResume(row)">
                继续
              </el-button>
              <el-button v-if="row.status === 'paused'" type="danger" size="small" @click.stop="handleCancel(row)">
                取消
              </el-button>
              <!-- failed: 可重试 -->
              <el-button v-if="row.status === 'failed'" type="warning" size="small" @click.stop="handleStart(row)">
                重试
              </el-button>
              <!-- 非完成/取消状态可编辑 -->
              <el-button v-if="!['completed', 'cancelled'].includes(row.status)" type="primary" size="small" link @click.stop="showDialog(row)">
                编辑
              </el-button>
              <!-- 非运行状态可删除 -->
              <el-popconfirm v-if="row.status !== 'running'" title="确定删除该任务?" @confirm="handleDelete(row.id)">
                <template #reference>
                  <el-button type="danger" size="small" link @click.stop>删除</el-button>
                </template>
              </el-popconfirm>
            </div>
          </template>
        </el-table-column>
      </el-table>
    </el-card>

    <!-- 任务详情弹窗 -->
    <el-dialog v-model="detailVisible" title="任务详情" width="700px">
      <template v-if="currentTask">
        <el-descriptions :column="2" border>
          <el-descriptions-item label="任务ID">{{ currentTask.id }}</el-descriptions-item>
          <el-descriptions-item label="任务名称">{{ currentTask.name }}</el-descriptions-item>
          <el-descriptions-item label="平台">{{ platformLabels[currentTask.platform] }}</el-descriptions-item>
          <el-descriptions-item label="状态">
            <el-tag :type="getStatusTagType(currentTask.status)" size="small">
              {{ statusLabels[currentTask.status] || currentTask.status }}
            </el-tag>
          </el-descriptions-item>
          <el-descriptions-item label="进度">{{ getProgress(currentTask) }}%</el-descriptions-item>
          <el-descriptions-item label="优先级">{{ currentTask.priority ?? 0 }}</el-descriptions-item>
          <el-descriptions-item label="创建时间">{{ currentTask.created_at }}</el-descriptions-item>
          <el-descriptions-item label="启动时间">{{ currentTask.started_at || '-' }}</el-descriptions-item>
          <el-descriptions-item label="完成时间">{{ currentTask.completed_at || '-' }}</el-descriptions-item>
          <el-descriptions-item label="账号组">{{ currentTask.account_group_id || '-' }}</el-descriptions-item>
          <el-descriptions-item label="关键词组">{{ currentTask.keyword_group_id || '-' }}</el-descriptions-item>
        </el-descriptions>

        <template v-if="currentTask.search_config_json || currentTask.filter_config_json || currentTask.action_config_json">
          <el-divider content-position="left">任务配置</el-divider>
          <div v-if="currentTask.search_config_json && currentTask.search_config_json !== '{}'" class="config-section">
            <h4>搜索配置</h4>
            <pre>{{ formatJson(currentTask.search_config_json) }}</pre>
          </div>
          <div v-if="currentTask.filter_config_json && currentTask.filter_config_json !== '{}'" class="config-section">
            <h4>过滤配置</h4>
            <pre>{{ formatJson(currentTask.filter_config_json) }}</pre>
          </div>
          <div v-if="currentTask.action_config_json && currentTask.action_config_json !== '{}'" class="config-section">
            <h4>动作配置</h4>
            <pre>{{ formatJson(currentTask.action_config_json) }}</pre>
          </div>
        </template>
      </template>
    </el-dialog>

    <!-- 创建任务弹窗（新设计：账号+操作类型→跳转） -->
    <el-dialog
      v-model="dialogVisible"
      title="创建任务"
      width="560px"
      destroy-on-close
    >
      <el-form :model="createForm" label-width="100px">
        <!-- 第一步：选择账号 -->
        <el-form-item label="选择账号" required>
          <el-select
            v-model="createForm.accountId"
            placeholder="请选择已登录的账号"
            style="width: 100%"
            filterable
          >
            <el-option
              v-for="acc in accountList"
              :key="acc.id"
              :label="acc.name + ' - ' + (platformLabels[acc.platform] || acc.platform)"
              :value="acc.id"
            />
          </el-select>
        </el-form-item>

        <!-- 第二步：选择操作类型 -->
        <el-form-item label="操作类型" required>
          <el-checkbox-group v-model="createForm.actions">
            <el-checkbox label="comment">评论</el-checkbox>
            <el-checkbox label="like">点赞</el-checkbox>
            <el-checkbox label="favorite">收藏</el-checkbox>
            <el-checkbox label="follow">关注</el-checkbox>
          </el-checkbox-group>
        </el-form-item>
      </el-form>

      <template #footer>
        <el-button @click="dialogVisible = false">取消</el-button>
        <el-button type="primary" @click="handleCreateConfirm" :disabled="!createForm.accountId || !createForm.actions.length">
          确认创建
        </el-button>
      </template>
    </el-dialog>
  </div>
</template>

<script setup>
import { ref, onMounted } from 'vue'
import { useRouter } from 'vue-router'
import {
  getTasks, createTask, updateTask, deleteTask,
  startTask as apiStartTask, pauseTask as apiPauseTask,
  resumeTask as apiResumeTask, cancelTask as apiCancelTask,
  getAccounts
} from '@/api'
import { ElMessage, ElMessageBox } from 'element-plus'

const router = useRouter()
const tasks = ref([])
const loading = ref(false)
const submitLoading = ref(false)
const dialogVisible = ref(false)
const detailVisible = ref(false)
const editingId = ref(null)
const currentTask = ref(null)
const statusFilter = ref('')

// ---- 新建任务弹窗数据 ----
const accountList = ref([])
const createForm = ref({
  accountId: '',
  actions: []
})

const platformLabels = {
  douyin: '抖音',
  xiaohongshu: '小红书',
  kuaishou: '快手',
  bilibili: 'B站'
}

const statusLabels = {
  draft: '草稿',
  pending: '待执行',
  running: '运行中',
  paused: '已暂停',
  completed: '已完成',
  failed: '失败',
  cancelled: '已取消',
  reviewing: '审核中'
}

function getStatusTagType(status) {
  const map = {
    draft: 'info',
    pending: 'info',
    running: 'success',
    paused: 'warning',
    completed: '',
    failed: 'danger',
    cancelled: 'info',
    reviewing: 'warning'
  }
  return map[status] || 'info'
}

function getProgress(row) {
  return row.progress_total ? Math.round((row.progress_done || 0) / row.progress_total * 100) : 0
}

function formatTime(t) {
  if (!t) return '-'
  try {
    const d = new Date(t)
    const month = String(d.getMonth() + 1).padStart(2, '0')
    const day = String(d.getDate()).padStart(2, '0')
    const hour = String(d.getHours()).padStart(2, '0')
    const min = String(d.getMinutes()).padStart(2, '0')
    return `${month}-${day} ${hour}:${min}`
  } catch {
    return t
  }
}

function formatJson(jsonStr) {
  try {
    return JSON.stringify(JSON.parse(jsonStr), null, 2)
  } catch {
    return jsonStr
  }
}

onMounted(() => {
  loadTasks()
  loadAccountList()
})

async function loadAccountList() {
  try {
    const data = await getAccounts()
    if (Array.isArray(data)) {
      accountList.value = data.map(a => ({
        id: a.id || a.account_id,
        name: a.display_name || a.username || a.name,
        platform: a.platform || 'douyin'
      }))
    }
  } catch (e) {
    console.error('加载账号列表失败', e)
  }
}

async function loadTasks() {
  loading.value = true
  try {
    const params = {}
    if (statusFilter.value) params.status = statusFilter.value
    tasks.value = await getTasks(params)
  } catch (e) {
    console.error(e)
  } finally {
    loading.value = false
  }
}

function showDetail(row, column, event) {
  // 如果点击的是操作按钮，不弹详情
  if (event && event.target.closest('.action-buttons')) return
  currentTask.value = row
  detailVisible.value = true
}

function showDialog(row) {
  if (row) {
    editingId.value = row.id
  } else {
    editingId.value = null
    createForm.value = { accountId: '', actions: [] }
  }
  dialogVisible.value = true
}

function handleCreateConfirm() {
  if (!createForm.value.accountId) {
    ElMessage.warning('请选择账号')
    return
  }
  if (!createForm.value.actions.length) {
    ElMessage.warning('请选择至少一种操作类型')
    return
  }
  const actionsStr = createForm.value.actions.join(',')
  const accountId = createForm.value.accountId
  dialogVisible.value = false
  router.push({ path: '/douyin-comment', query: { account: accountId, actions: actionsStr } })
}

async function handleStart(row) {
  try {
    await apiStartTask(row.id)
    ElMessage.success('任务已启动')
    loadTasks()
  } catch (e) {
    ElMessage.error('启动失败')
  }
}

async function handlePause(row) {
  try {
    await apiPauseTask(row.id)
    ElMessage.success('任务已暂停')
    loadTasks()
  } catch (e) {
    ElMessage.error('暂停失败')
  }
}

async function handleResume(row) {
  try {
    await apiResumeTask(row.id)
    ElMessage.success('任务已继续')
    loadTasks()
  } catch (e) {
    ElMessage.error('继续失败')
  }
}

async function handleCancel(row) {
  try {
    await ElMessageBox.confirm('确定取消该任务？取消后无法恢复', '确认取消', {
      confirmButtonText: '确定',
      cancelButtonText: '取消',
      type: 'warning'
    })
    await apiCancelTask(row.id)
    ElMessage.success('任务已取消')
    loadTasks()
  } catch (e) {
    if (e !== 'cancel') ElMessage.error('取消失败')
  }
}

async function handleDelete(id) {
  try {
    await deleteTask(id)
    ElMessage.success('删除成功')
    loadTasks()
  } catch (e) {
    ElMessage.error('删除失败')
  }
}
</script>

<style scoped>
.page-header {
  margin-bottom: 16px;
  display: flex;
  align-items: center;
  justify-content: space-between;
}
.action-buttons {
  display: flex;
  align-items: center;
  gap: 4px;
  flex-wrap: wrap;
}
.config-section {
  margin-bottom: 12px;
}
.config-section h4 {
  margin: 0 0 8px 0;
  font-size: 14px;
  color: var(--el-text-color-primary);
}
.config-section pre {
  background: var(--el-fill-color-light);
  padding: 12px;
  border-radius: 4px;
  font-size: 12px;
  overflow-x: auto;
  margin: 0;
}
</style>
