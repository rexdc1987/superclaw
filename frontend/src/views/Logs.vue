<template>
  <div class="logs-page">
    <div class="page-header">
      <div class="filter-bar">
        <el-select v-model="levelFilter" placeholder="日志级别" clearable style="width: 140px" @change="applyFilters">
          <el-option label="全部" value="" />
          <el-option label="信息" value="info" />
          <el-option label="警告" value="warn" />
          <el-option label="错误" value="error" />
        </el-select>
        <el-date-picker v-model="dateRange" type="daterange" range-separator="至" start-placeholder="开始日期" end-placeholder="结束日期" value-format="YYYY-MM-DD" style="width: 280px" @change="applyFilters" />
      </div>
      <el-button type="primary" @click="exportLogs"><el-icon><Download /></el-icon> 导出日志</el-button>
    </div>
    <el-card>
      <el-table :data="filteredLogs" style="width: 100%" v-loading="loading" max-height="600" ref="tableRef">
        <el-table-column prop="type" label="类型" width="90">
          <template #default="{ row }">
            <el-tag :type="getLevelType(row.type)" size="small">{{ getLevelLabel(row.type) }}</el-tag>
          </template>
        </el-table-column>
        <el-table-column prop="time" label="时间" width="180" />
        <el-table-column prop="content" label="内容" min-width="300" show-overflow-tooltip />
        <el-table-column prop="browser" label="浏览器名" width="140" />
        <el-table-column prop="account" label="账号" width="140" />
      </el-table>
    </el-card>
  </div>
</template>

<script setup>
import { ref, onMounted, computed, nextTick } from 'vue'
import { getActions } from '@/api'
import { ElMessage } from 'element-plus'

const logs = ref([])
const loading = ref(false)
const levelFilter = ref('')
const dateRange = ref(null)
const tableRef = ref(null)

function generateLogs() {
  const types = ['info', 'info', 'info', 'warn', 'error']
  const contentPool = [
    '任务启动成功', '评论发送完成', '私信发送失败', '账号登录成功',
    '评论内容触发敏感词', '账号状态异常', '数据导出完成', '风控规则触发',
    '浏览器启动超时', '任务执行中断', '验证码识别失败', '账号被限制'
  ]
  const browserPool = ['Chrome-1', 'Chrome-2', 'Firefox-1', 'Edge-1']
  const accountPool = ['账号A', '账号B', '账号C', '账号D']
  const result = []
  const now = new Date()
  for (let i = 0; i < 50; i++) {
    const time = new Date(now.getTime() - i * 60000 * Math.random() * 60)
    result.push({
      id: i + 1,
      type: types[Math.floor(Math.random() * types.length)],
      time: time.toLocaleString('zh-CN'),
      content: contentPool[Math.floor(Math.random() * contentPool.length)],
      browser: browserPool[Math.floor(Math.random() * browserPool.length)],
      account: accountPool[Math.floor(Math.random() * accountPool.length)]
    })
  }
  return result.sort((a, b) => new Date(a.time) - new Date(b.time))
}

const filteredLogs = computed(() => {
  let result = logs.value
  if (levelFilter.value) {
    result = result.filter(l => l.type === levelFilter.value)
  }
  if (dateRange.value && dateRange.value.length === 2) {
    const [start, end] = dateRange.value
    result = result.filter(l => {
      const d = l.time.split(' ')[0]
      return d >= start && d <= end
    })
  }
  return result
})

function getLevelType(type) {
  return { info: 'success', warn: 'warning', error: 'danger' }[type] || 'info'
}

function getLevelLabel(type) {
  return { info: '信息', warn: '警告', error: '错误' }[type] || type
}

function applyFilters() {}

function exportLogs() {
  const headers = ['类型', '时间', '内容', '浏览器名', '账号']
  const rows = filteredLogs.value.map(l => [l.type, l.time, l.content, l.browser, l.account])
  const csv = [headers.join(','), ...rows.map(r => r.join(','))].join('\n')
  const blob = new Blob(['\ufeff' + csv], { type: 'text/csv;charset=utf-8;' })
  const url = URL.createObjectURL(blob)
  const a = document.createElement('a')
  a.href = url
  a.download = 'logs_' + new Date().toISOString().slice(0, 10) + '.csv'
  a.click()
  URL.revokeObjectURL(url)
  ElMessage.success('日志导出成功')
}

onMounted(async () => {
  loading.value = true
  try {
    await getActions()
  } catch (e) {}
  finally {
    logs.value = generateLogs()
    loading.value = false
    await nextTick()
    const table = tableRef.value
    if (table && table.setScrollTop) {
      table.setScrollTop(99999)
    }
  }
})
</script>

<style scoped>
.page-header {
  margin-bottom: 16px;
  display: flex;
  justify-content: space-between;
  align-items: center;
}
.filter-bar {
  display: flex;
  gap: 12px;
  align-items: center;
}
</style>
