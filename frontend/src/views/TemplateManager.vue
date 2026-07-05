<template>
  <div class="template-manager">
    <div class="page-header">
      <div>
        <h3>红果评论模板</h3>
        <p>维护可复用评论内容，供红果任务按模板或混合模式抽取。</p>
      </div>
      <el-button type="primary" @click="openAddDialog">
        <el-icon><Plus /></el-icon>
        添加模板
      </el-button>
    </div>

    <el-card>
      <el-table :data="templates" v-loading="loading" style="width: 100%">
        <el-table-column prop="id" label="ID" width="70" />
        <el-table-column prop="name" label="名称" width="160" show-overflow-tooltip />
        <el-table-column prop="content" label="内容" min-width="260" show-overflow-tooltip />
        <el-table-column prop="category" label="分类" width="130" />
        <el-table-column prop="use_count" label="使用次数" width="110" />
        <el-table-column prop="created_at" label="创建时间" width="180">
          <template #default="{ row }">{{ formatTime(row.created_at) }}</template>
        </el-table-column>
        <el-table-column label="操作" width="110" fixed="right">
          <template #default="{ row }">
            <el-button size="small" type="danger" @click="handleDelete(row.id)">删除</el-button>
          </template>
        </el-table-column>
      </el-table>
    </el-card>

    <el-dialog v-model="showAdd" title="添加评论模板" width="560px">
      <el-form :model="newTemplate" label-width="80px">
        <el-form-item label="名称">
          <el-input v-model="newTemplate.name" placeholder="例如：爽文通用评论" />
        </el-form-item>
        <el-form-item label="内容" required>
          <el-input
            v-model="newTemplate.content"
            type="textarea"
            :rows="5"
            placeholder="输入一条自然、短句式的评论内容"
          />
        </el-form-item>
        <el-form-item label="分类">
          <el-input v-model="newTemplate.category" placeholder="例如：重生、甜宠、复仇" />
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="showAdd = false">取消</el-button>
        <el-button type="primary" :loading="submitting" @click="handleAdd">确定</el-button>
      </template>
    </el-dialog>
  </div>
</template>

<script setup>
import { reactive, ref, onMounted } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import { getTemplates, createTemplate, deleteTemplate } from '../api/hongguo'

const templates = ref([])
const loading = ref(false)
const submitting = ref(false)
const showAdd = ref(false)
const newTemplate = reactive({ name: '', content: '', category: '' })

async function loadTemplates() {
  loading.value = true
  try {
    const res = await getTemplates()
    templates.value = Array.isArray(res) ? res : (res.items || res.data || [])
  } finally {
    loading.value = false
  }
}

function openAddDialog() {
  newTemplate.name = ''
  newTemplate.content = ''
  newTemplate.category = ''
  showAdd.value = true
}

async function handleAdd() {
  if (!newTemplate.content.trim()) {
    ElMessage.warning('请输入模板内容')
    return
  }

  submitting.value = true
  try {
    await createTemplate({
      name: newTemplate.name.trim() || null,
      content: newTemplate.content.trim(),
      category: newTemplate.category.trim() || null,
    })
    showAdd.value = false
    ElMessage.success('添加成功')
    loadTemplates()
  } finally {
    submitting.value = false
  }
}

async function handleDelete(id) {
  await ElMessageBox.confirm('确定删除这个评论模板吗？', '删除确认', {
    type: 'warning',
    confirmButtonText: '删除',
    cancelButtonText: '取消',
  })
  await deleteTemplate(id)
  ElMessage.success('删除成功')
  loadTemplates()
}

function formatTime(value) {
  if (!value) return '-'
  const date = new Date(value)
  return Number.isNaN(date.getTime()) ? value : date.toLocaleString('zh-CN')
}

onMounted(loadTemplates)
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
</style>
