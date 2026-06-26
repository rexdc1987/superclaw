<template>
  <div class="playbooks-page">
    <div class="page-header">
      <el-button type="primary" @click="showDialog()"><el-icon><Plus /></el-icon> 新增打法</el-button>
    </div>
    <el-row :gutter="20">
      <el-col :span="8" v-for="item in playbooks" :key="item.id">
        <el-card class="playbook-card" shadow="hover">
          <div class="playbook-header">
            <el-icon :size="32" color="#89b4fa"><Notebook /></el-icon>
            <div class="playbook-type">{{ item.playbook_type }}</div>
          </div>
          <h3>{{ item.name }}</h3>
          <p class="playbook-desc">{{ item.description }}</p>
          <div class="playbook-meta">
            <el-tag size="small">{{ item.platform }}</el-tag>
            <el-tag :type="item.is_active ? 'success' : 'info'" size="small">{{ item.is_active ? '启用' : '禁用' }}</el-tag>
          </div>
          <div class="playbook-actions">
            <el-button link type="primary" @click="showDialog(item)">编辑</el-button>
            <el-popconfirm title="确定删除?" @confirm="handleDelete(item.id)"><template #reference><el-button link type="danger">删除</el-button></template></el-popconfirm>
          </div>
        </el-card>
      </el-col>
    </el-row>
    <el-dialog v-model="dialogVisible" :title="editingId ? '编辑打法' : '新增打法'" width="500px">
      <el-form :model="form" label-width="80px">
        <el-form-item label="名称"><el-input v-model="form.name" /></el-form-item>
        <el-form-item label="类型"><el-select v-model="form.playbook_type" style="width: 100%"><el-option label="自动曝光" value="auto_exposure" /><el-option label="定向曝光" value="targeted_exposure" /><el-option label="链接曝光" value="link_exposure" /><el-option label="搜索账号" value="search_account" /><el-option label="留痕曝光" value="stealth_exposure" /></el-select></el-form-item>
        <el-form-item label="平台"><el-select v-model="form.platform" style="width: 100%"><el-option label="抖音" value="douyin" /><el-option label="小红书" value="xiaohongshu" /><el-option label="快手" value="kuaishou" /><el-option label="B站" value="bilibili" /></el-select></el-form-item>
        <el-form-item label="描述"><el-input v-model="form.description" type="textarea" :rows="3" /></el-form-item>
      </el-form>
      <template #footer><el-button @click="dialogVisible = false">取消</el-button><el-button type="primary" @click="handleSubmit">确定</el-button></template>
    </el-dialog>
  </div>
</template>

<script setup>
import { ref, onMounted } from 'vue'
import { getPlaybooks, createPlaybook, updatePlaybook, deletePlaybook } from '@/api'
import { ElMessage } from 'element-plus'

const playbooks = ref([])
const dialogVisible = ref(false)
const editingId = ref(null)
const form = ref({ name: '', playbook_type: 'auto_exposure', platform: 'douyin', description: '' })

onMounted(() => loadPlaybooks())
async function loadPlaybooks() { try { playbooks.value = await getPlaybooks() } catch (e) { console.error(e) } }
function showDialog(row) { if (row) { editingId.value = row.id; form.value = { name: row.name, playbook_type: row.playbook_type, platform: row.platform, description: row.description } } else { editingId.value = null; form.value = { name: '', playbook_type: 'auto_exposure', platform: 'douyin', description: '' } } dialogVisible.value = true }
async function handleSubmit() { try { if (editingId.value) { await updatePlaybook(editingId.value, form.value); ElMessage.success('更新成功') } else { await createPlaybook(form.value); ElMessage.success('创建成功') } dialogVisible.value = false; loadPlaybooks() } catch (e) { console.error(e) } }
async function handleDelete(id) { try { await deletePlaybook(id); ElMessage.success('删除成功'); loadPlaybooks() } catch (e) { console.error(e) } }
</script>

<style scoped>
.page-header { margin-bottom: 16px; }
.playbook-card { margin-bottom: 20px; }
.playbook-header { display: flex; align-items: center; gap: 12px; margin-bottom: 12px; }
.playbook-type { font-size: 12px; color: var(--text-secondary); }
.playbook-desc { color: var(--text-secondary); font-size: 14px; margin: 8px 0; min-height: 40px; }
.playbook-meta { display: flex; gap: 8px; margin-bottom: 12px; }
.playbook-actions { border-top: 1px solid var(--border-color); padding-top: 12px; }
</style>
