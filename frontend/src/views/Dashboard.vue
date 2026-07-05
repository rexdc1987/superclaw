<template>
  <div class="dashboard" v-loading="loading">
    <div class="dashboard-header">
      <h3>仪表盘概览</h3>
      <el-button :icon="Refresh" circle @click="loadDashboard" />
    </div>

    <el-row :gutter="20" class="stat-cards">
      <el-col :span="6">
        <el-card shadow="hover">
          <div class="stat-card">
            <div class="stat-icon" style="background: rgba(137,180,250,0.15)">
              <el-icon :size="28" color="#89b4fa"><User /></el-icon>
            </div>
            <div class="stat-info">
              <div class="stat-value">{{ stats.accounts }}</div>
              <div class="stat-label">账号总数</div>
            </div>
          </div>
        </el-card>
      </el-col>
      <el-col :span="6">
        <el-card shadow="hover">
          <div class="stat-card">
            <div class="stat-icon" style="background: rgba(166,227,161,0.15)">
              <el-icon :size="28" color="#a6e3a1"><List /></el-icon>
            </div>
            <div class="stat-info">
              <div class="stat-value">{{ stats.tasks }}</div>
              <div class="stat-label">任务总数</div>
            </div>
          </div>
        </el-card>
      </el-col>
      <el-col :span="6">
        <el-card shadow="hover">
          <div class="stat-card">
            <div class="stat-icon" style="background: rgba(249,226,175,0.15)">
              <el-icon :size="28" color="#f9e2af"><DataAnalysis /></el-icon>
            </div>
            <div class="stat-info">
              <div class="stat-value">{{ stats.leads }}</div>
              <div class="stat-label">线索总数</div>
            </div>
          </div>
        </el-card>
      </el-col>
      <el-col :span="6">
        <el-card shadow="hover">
          <div class="stat-card">
            <div class="stat-icon" style="background: rgba(243,139,168,0.15)">
              <el-icon :size="28" color="#f38ba8"><ChatDotRound /></el-icon>
            </div>
            <div class="stat-info">
              <div class="stat-value">{{ stats.pendingReview }}</div>
              <div class="stat-label">待审核数</div>
            </div>
          </div>
        </el-card>
      </el-col>
    </el-row>

    <el-row :gutter="20" style="margin-top: 20px">
      <el-col :span="16">
        <el-card>
          <template #header>
            <div class="card-header">
              <span>最近任务</span>
            </div>
          </template>
          <el-table :data="recentTasks" style="width: 100%">
            <el-table-column prop="name" label="任务名称" min-width="160" />
            <el-table-column prop="platform" label="平台" width="110">
              <template #default="{ row }">
                <el-tag size="small">{{ platformLabels[row.platform] || row.platform || '-' }}</el-tag>
              </template>
            </el-table-column>
            <el-table-column prop="status" label="状态" width="110">
              <template #default="{ row }">
                <el-tag :type="getStatusType(row.status)" size="small">
                  {{ statusLabels[row.status] || row.status || '-' }}
                </el-tag>
              </template>
            </el-table-column>
            <el-table-column prop="created_at" label="创建时间" width="180" />
            <el-table-column label="操作" width="120">
              <template #default="{ row }">
                <el-button link type="primary" @click="goToTaskDetail(row.id)">查看详情</el-button>
              </template>
            </el-table-column>
          </el-table>
        </el-card>
      </el-col>
      <el-col :span="8">
        <el-card>
          <template #header>平台分布</template>
          <div class="platform-list">
            <div v-for="item in platformStats" :key="item.platform" class="platform-item">
              <span class="platform-name">{{ item.platform }} ({{ item.count }})</span>
              <el-progress :percentage="item.percent" :stroke-width="10" :color="item.color" />
            </div>
            <el-empty v-if="platformStats.length === 0" description="暂无数据" :image-size="60" />
          </div>
        </el-card>
      </el-col>
    </el-row>
  </div>
</template>

<script setup>
import { ref, onMounted } from 'vue'
import { useRouter } from 'vue-router'
import { Refresh } from '@element-plus/icons-vue'
import { getAccounts, getTasks, getLeads, getActions } from '@/api'

const router = useRouter()
const loading = ref(false)
const stats = ref({ accounts: 0, tasks: 0, leads: 0, pendingReview: 0 })
const recentTasks = ref([])
const platformStats = ref([])

const platformColors = {
  douyin: '#f38ba8',
  xiaohongshu: '#f9e2af',
  kuaishou: '#a6e3a1',
  bilibili: '#89b4fa',
  xianyu: '#cba6f7',
  pinduoduo: '#fab387'
}

const platformLabels = {
  douyin: '抖音',
  xiaohongshu: '小红书',
  kuaishou: '快手',
  bilibili: 'B站',
  xianyu: '闲鱼',
  pinduoduo: '拼多多'
}

const statusLabels = {
  running: '执行中',
  completed: '已完成',
  failed: '失败',
  pending: '待执行',
  paused: '已暂停',
  cancelled: '已取消'
}

function getStatusType(status) {
  return {
    running: 'success',
    completed: 'primary',
    failed: 'danger',
    pending: 'info',
    paused: 'warning',
    cancelled: 'info'
  }[status] || 'info'
}

function goToTaskDetail(id) {
  router.push({ path: '/tasks', query: { detail: id } })
}

async function loadDashboard() {
  loading.value = true
  try {
    const [accounts, tasks, leads, actions] = await Promise.all([
      getAccounts().catch(() => []),
      getTasks().catch(() => []),
      getLeads().catch(() => []),
      getActions().catch(() => [])
    ])

    const accountsList = Array.isArray(accounts) ? accounts : []
    const tasksList = Array.isArray(tasks) ? tasks : []
    const leadsList = Array.isArray(leads) ? leads : []
    const actionsList = Array.isArray(actions) ? actions : []

    stats.value = {
      accounts: accountsList.length,
      tasks: tasksList.length,
      leads: leadsList.length,
      pendingReview: actionsList.filter(a => a.status === 'pending' || a.status === 'awaiting_review').length
    }

    recentTasks.value = tasksList.slice(0, 5)

    const platforms = {}
    accountsList.forEach(a => {
      if (a.platform) platforms[a.platform] = (platforms[a.platform] || 0) + 1
    })
    const total = accountsList.length || 1
    platformStats.value = Object.entries(platforms).map(([platform, count]) => ({
      platform: platformLabels[platform] || platform,
      count,
      percent: Math.round(count / total * 100),
      color: platformColors[platform] || '#89b4fa'
    }))
  } finally {
    loading.value = false
  }
}

onMounted(() => loadDashboard())
</script>

<style scoped>
.dashboard-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  margin-bottom: 20px;
}
.dashboard-header h3 {
  color: var(--text-primary);
  font-size: 18px;
  font-weight: 600;
}
.stat-card { display: flex; align-items: center; gap: 16px; }
.stat-icon { width: 56px; height: 56px; border-radius: 12px; display: flex; align-items: center; justify-content: center; }
.stat-value { font-size: 28px; font-weight: 700; color: var(--text-primary); }
.stat-label { font-size: 14px; color: var(--text-secondary); }
.platform-list { display: flex; flex-direction: column; gap: 16px; }
.platform-name { display: block; margin-bottom: 4px; color: var(--text-secondary); font-size: 13px; }
.card-header { display: flex; align-items: center; justify-content: space-between; }
</style>
