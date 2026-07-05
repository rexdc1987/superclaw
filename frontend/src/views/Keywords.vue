<template>
  <div class="keywords-page">
    <div class="page-header">
      <el-button type="primary" @click="showGroupDialog()">
        <el-icon><Plus /></el-icon> 新增关键词组
      </el-button>
    </div>

    <el-card shadow="hover">
      <el-table :data="groups" v-loading="loading" stripe style="width: 100%">
        <el-table-column prop="name" label="组名称" min-width="150" />
        <el-table-column label="关键词数量" width="120" align="center">
          <template #default="{ row }">
            <el-tag type="info" size="small">{{ row.keyword_count ?? row.keywords_count ?? 0 }}</el-tag>
          </template>
        </el-table-column>
        <el-table-column prop="description" label="描述" min-width="200" show-overflow-tooltip />
        <el-table-column label="创建时间" width="180" align="center">
          <template #default="{ row }">
            {{ formatDate(row.created_at) }}
          </template>
        </el-table-column>
        <el-table-column label="操作" width="360" align="center" fixed="right">
          <template #default="{ row }">
            <el-button link type="primary" @click="showGroupDialog(row)">编辑</el-button>
            <el-button link type="success" @click="showImportDialog(row)">导入关键词</el-button>
            <el-button link type="warning" @click="showKeywordsDrawer(row)">查看关键词</el-button>
            <el-button link type="info" @click="handleGetNext(row)">获取下一个</el-button>
            <el-popconfirm title="确定删除该关键词组？" @confirm="handleDeleteGroup(row.id)">
              <template #reference>
                <el-button link type="danger">删除</el-button>
              </template>
            </el-popconfirm>
          </template>
        </el-table-column>
      </el-table>
    </el-card>

    <!-- 新增/编辑关键词组对话框 -->
    <el-dialog v-model="groupDialogVisible" :title="editingGroupId ? '编辑关键词组' : '新增关键词组'" width="500px">
      <el-form :model="groupForm" label-width="80px" ref="groupFormRef" :rules="groupRules">
        <el-form-item label="组名称" prop="name">
          <el-input v-model="groupForm.name" placeholder="请输入关键词组名称" />
        </el-form-item>
        <el-form-item label="描述">
          <el-input v-model="groupForm.description" type="textarea" :rows="4" placeholder="请输入描述（可选）" />
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="groupDialogVisible = false">取消</el-button>
        <el-button type="primary" @click="handleGroupSubmit" :loading="submitting">确定</el-button>
      </template>
    </el-dialog>

    <!-- 导入关键词对话框 -->
    <el-dialog v-model="importDialogVisible" title="导入关键词" width="520px">
      <p class="import-hint">每行一个关键词，将批量导入到「{{ importTargetGroup?.name }}」组中</p>
      <el-input
        v-model="importText"
        type="textarea"
        :rows="10"
        placeholder="请输入关键词，每行一个"
      />
      <div class="import-count" v-if="importText.trim()">
        共 <strong>{{ importLines }}</strong> 个关键词
      </div>
      <template #footer>
        <el-button @click="importDialogVisible = false">取消</el-button>
        <el-button type="primary" @click="handleImport" :loading="importing">导入</el-button>
      </template>
    </el-dialog>

    <!-- 查看关键词抽屉 -->
    <el-drawer v-model="keywordsDrawerVisible" :title="'关键词列表 - ' + drawerGroupName" size="500px">
      <div v-loading="keywordsLoading">
        <el-table :data="keywordsList" stripe style="width: 100%">
          <el-table-column prop="word" label="关键词" min-width="150" />
          <el-table-column label="使用次数" width="100" align="center">
            <template #default="{ row }">
              <el-tag size="small">{{ row.usage_count ?? 0 }}</el-tag>
            </template>
          </el-table-column>
          <el-table-column label="最后使用" width="170" align="center">
            <template #default="{ row }">
              {{ row.last_used_at ? formatDate(row.last_used_at) : '-' }}
            </template>
          </el-table-column>
        </el-table>
        <el-empty v-if="!keywordsLoading && keywordsList.length === 0" description="暂无关键词" />
      </div>
    </el-drawer>
  </div>
</template>

<script setup>
import { ref, computed, onMounted, nextTick } from 'vue'
import {
  getKeywordGroups,
  createKeywordGroup,
  updateKeywordGroup,
  deleteKeywordGroup,
  getGroupKeywords,
  importKeywords,
  getNextKeyword
} from '@/api'
import { ElMessage, ElMessageBox } from 'element-plus'

const loading = ref(false)
const submitting = ref(false)
const importing = ref(false)
const keywordsLoading = ref(false)

const groups = ref([])
const keywordsList = ref([])

const groupDialogVisible = ref(false)
const editingGroupId = ref(null)
const groupFormRef = ref(null)
const groupForm = ref({ name: '', description: '' })
const groupRules = { name: [{ required: true, message: '请输入关键词组名称', trigger: 'blur' }] }

const importDialogVisible = ref(false)
const importTargetGroup = ref(null)
const importText = ref('')

const keywordsDrawerVisible = ref(false)
const drawerGroupName = ref('')

const importLines = computed(() => {
  return importText.value.split('\n').filter(line => line.trim()).length
})

onMounted(() => loadGroups())

async function loadGroups() {
  loading.value = true
  try {
    const res = await getKeywordGroups()
    groups.value = Array.isArray(res) ? res : (res?.data || res?.items || [])
  } catch (e) {
    console.error(e)
  } finally {
    loading.value = false
  }
}

function formatDate(dateStr) {
  if (!dateStr) return '-'
  const d = new Date(dateStr)
  if (isNaN(d.getTime())) return dateStr
  const pad = n => String(n).padStart(2, '0')
  return d.getFullYear() + '-' + pad(d.getMonth() + 1) + '-' + pad(d.getDate()) + ' ' + pad(d.getHours()) + ':' + pad(d.getMinutes()) + ':' + pad(d.getSeconds())
}

function showGroupDialog(row) {
  if (row) {
    editingGroupId.value = row.id
    groupForm.value = { name: row.name, description: row.description || '' }
  } else {
    editingGroupId.value = null
    groupForm.value = { name: '', description: '' }
  }
  groupDialogVisible.value = true
  nextTick(() => groupFormRef.value?.clearValidate())
}

async function handleGroupSubmit() {
  try {
    await groupFormRef.value?.validate()
  } catch {
    return
  }
  submitting.value = true
  try {
    if (editingGroupId.value) {
      await updateKeywordGroup(editingGroupId.value, groupForm.value)
      ElMessage.success('更新成功')
    } else {
      await createKeywordGroup(groupForm.value)
      ElMessage.success('创建成功')
    }
    groupDialogVisible.value = false
    loadGroups()
  } catch (e) {
    console.error(e)
  } finally {
    submitting.value = false
  }
}

async function handleDeleteGroup(id) {
  try {
    await deleteKeywordGroup(id)
    ElMessage.success('删除成功')
    loadGroups()
  } catch (e) {
    console.error(e)
  }
}

function showImportDialog(row) {
  importTargetGroup.value = row
  importText.value = ''
  importDialogVisible.value = true
}

async function handleImport() {
  const lines = importText.value.split('\n').filter(line => line.trim())
  if (lines.length === 0) {
    ElMessage.warning('请输入至少一个关键词')
    return
  }
  importing.value = true
  try {
    await importKeywords(importTargetGroup.value.id, { keywords: lines })
    ElMessage.success('成功导入 ' + lines.length + ' 个关键词')
    importDialogVisible.value = false
    loadGroups()
  } catch (e) {
    console.error(e)
  } finally {
    importing.value = false
  }
}

async function showKeywordsDrawer(row) {
  drawerGroupName.value = row.name
  keywordsDrawerVisible.value = true
  keywordsLoading.value = true
  keywordsList.value = []
  try {
    const res = await getGroupKeywords(row.id)
    keywordsList.value = Array.isArray(res) ? res : (res?.data || res?.items || [])
  } catch (e) {
    console.error(e)
  } finally {
    keywordsLoading.value = false
  }
}

async function handleGetNext(row) {
  try {
    const res = await getNextKeyword(row.id)
    const word = res?.word || res?.keyword || res?.data?.word || (typeof res === 'string' ? res : null)
    if (word) {
      ElMessageBox.alert('下一个关键词：<strong>' + word + '</strong>', '获取成功', {
        dangerouslyUseHTMLString: true,
        confirmButtonText: '确定'
      })
    } else {
      ElMessage.info(res?.message || '暂无可用关键词')
    }
  } catch (e) {
    console.error(e)
  }
}
</script>

<style scoped>
.page-header {
  margin-bottom: 16px;
}
.import-hint {
  color: var(--text-secondary);
  font-size: 14px;
  margin-bottom: 12px;
}
.import-count {
  margin-top: 8px;
  font-size: 13px;
  color: var(--text-secondary);
}
.import-count strong {
  color: var(--highlight, #89b4fa);
}
</style>
