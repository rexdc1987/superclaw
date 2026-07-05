<template>
  <div class="review-page">
    <div class="page-header">
      <el-tabs v-model="activeTab" @tab-change="loadReviews">
        <el-tab-pane label="待审核" name="pending" />
        <el-tab-pane label="已通过" name="approved" />
        <el-tab-pane label="已拒绝" name="rejected" />
      </el-tabs>
      <el-button type="primary" @click="batchApprove" :disabled="!selectedRows.length">批量通过</el-button>
    </div>
    <el-card>
      <el-table :data="reviews" style="width: 100%" v-loading="loading" @selection-change="handleSelectionChange">
        <el-table-column type="selection" width="50" />
        <el-table-column prop="id" label="ID" width="60" />
        <el-table-column prop="content" label="内容" min-width="250" show-overflow-tooltip />
        <el-table-column prop="account" label="账号" width="120" />
        <el-table-column prop="target" label="目标" width="150" show-overflow-tooltip />
        <el-table-column prop="status" label="状态" width="100">
          <template #default="{ row }">
            <el-tag :type="getStatusType(row.status)" size="small">{{ getStatusLabel(row.status) }}</el-tag>
          </template>
        </el-table-column>
        <el-table-column prop="created_at" label="创建时间" width="180" />
        <el-table-column label="操作" width="180" v-if="activeTab === 'pending'">
          <template #default="{ row }">
            <el-button link type="success" @click="handleApprove(row.id)">通过</el-button>
            <el-button link type="danger" @click="handleReject(row.id)">拒绝</el-button>
            <el-button link type="primary" @click="previewContent(row)">预览</el-button>
          </template>
        </el-table-column>
      </el-table>
    </el-card>

    <el-dialog v-model="previewVisible" title="内容预览" width="500px">
      <div class="preview-content">
        <p><strong>账号：</strong>{{ previewItem.account }}</p>
        <p><strong>目标：</strong>{{ previewItem.target }}</p>
        <p><strong>内容：</strong></p>
        <div class="preview-text">{{ previewItem.content }}</div>
      </div>
      <template #footer>
        <el-button @click="previewVisible = false">关闭</el-button>
        <template v-if="activeTab === 'pending'">
          <el-button type="success" @click="handleApprove(previewItem.id); previewVisible = false">通过</el-button>
          <el-button type="danger" @click="handleReject(previewItem.id); previewVisible = false">拒绝</el-button>
        </template>
      </template>
    </el-dialog>
  </div>
</template>

<script setup>
import { ref, onMounted } from 'vue'
import api from '@/api'
import { ElMessage } from 'element-plus'

const reviews = ref([])
const loading = ref(false)
const activeTab = ref('pending')
const selectedRows = ref([])
const previewVisible = ref(false)
const previewItem = ref({})

onMounted(() => loadReviews())

async function loadReviews() {
  loading.value = true
  try {
    const res = await api.post('/actions/review/submit', { status: activeTab.value })
    reviews.value = Array.isArray(res) ? res : (res.data || [])
  } catch (e) {
    reviews.value = []
  } finally {
    loading.value = false
  }
}

function getStatusType(status) {
  return { pending: 'warning', approved: 'success', rejected: 'danger' }[status] || 'info'
}

function getStatusLabel(status) {
  return { pending: '待审核', approved: '已通过', rejected: '已拒绝' }[status] || status
}

function handleSelectionChange(rows) {
  selectedRows.value = rows
}

function previewContent(row) {
  previewItem.value = { ...row }
  previewVisible.value = true
}

async function handleApprove(id) {
  try {
    await api.post('/actions/review/approve', { id })
    ElMessage.success('已通过')
    loadReviews()
  } catch (e) { console.error(e) }
}

async function handleReject(id) {
  try {
    await api.post('/actions/review/reject', { id })
    ElMessage.success('已拒绝')
    loadReviews()
  } catch (e) { console.error(e) }
}

async function batchApprove() {
  try {
    for (const row of selectedRows.value) {
      await api.post('/actions/review/approve', { id: row.id })
    }
    ElMessage.success('已批量通过 ' + selectedRows.value.length + ' 条')
    loadReviews()
  } catch (e) { console.error(e) }
}
</script>

<style scoped>
.page-header {
  margin-bottom: 16px;
  display: flex;
  justify-content: space-between;
  align-items: flex-start;
}
.preview-content p {
  margin-bottom: 8px;
  color: var(--text-secondary);
}
.preview-text {
  background: var(--bg-input);
  padding: 12px;
  border-radius: 8px;
  color: var(--text-primary);
  line-height: 1.6;
  white-space: pre-wrap;
}
</style>
