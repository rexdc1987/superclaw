<template>
  <div class="leads-page">
    <div class="page-header">
      <el-input v-model="search" placeholder="搜索线索..." prefix-icon="Search" style="width: 300px" @input="loadLeads" />
      <el-button type="primary" @click="handleExport"><el-icon><Download /></el-icon> 导出</el-button>
    </div>
    <el-card>
      <el-table :data="leads" style="width: 100%" v-loading="loading">
        <el-table-column prop="id" label="ID" width="60" />
        <el-table-column prop="platform" label="平台" width="100"><template #default="{ row }"><el-tag size="small">{{ row.platform }}</el-tag></template></el-table-column>
        <el-table-column prop="user_nickname" label="用户昵称" />
        <el-table-column prop="score" label="评分" width="80"><template #default="{ row }"><el-tag :type="row.score >= 80 ? 'success' : row.score >= 50 ? 'warning' : 'danger'" size="small">{{ row.score }}</el-tag></template></el-table-column>
        <el-table-column prop="status" label="状态" width="100"><template #default="{ row }"><el-tag :type="row.status === 'contacted' ? 'success' : 'info'" size="small">{{ row.status }}</el-tag></template></el-table-column>
        <el-table-column prop="contact_count" label="联系次数" width="100" />
        <el-table-column prop="created_at" label="创建时间" width="180" />
        <el-table-column label="操作" width="150">
          <template #default="{ row }">
            <el-button link type="primary" @click="showDialog(row)">编辑</el-button>
            <el-popconfirm title="确定删除?" @confirm="handleDelete(row.id)"><template #reference><el-button link type="danger">删除</el-button></template></el-popconfirm>
          </template>
        </el-table-column>
      </el-table>
    </el-card>
    <el-dialog v-model="dialogVisible" title="编辑线索" width="500px">
      <el-form :model="form" label-width="80px">
        <el-form-item label="状态"><el-select v-model="form.status" style="width: 100%"><el-option label="新线索" value="new" /><el-option label="已联系" value="contacted" /><el-option label="已转化" value="converted" /><el-option label="无效" value="invalid" /></el-select></el-form-item>
        <el-form-item label="备注"><el-input v-model="form.notes" type="textarea" :rows="3" /></el-form-item>
      </el-form>
      <template #footer><el-button @click="dialogVisible = false">取消</el-button><el-button type="primary" @click="handleSubmit">确定</el-button></template>
    </el-dialog>
  </div>
</template>

<script setup>
import { ref, onMounted } from 'vue'
import { getLeads, updateLead, deleteLead, exportLeads } from '@/api'
import { ElMessage } from 'element-plus'

const leads = ref([])
const loading = ref(false)
const search = ref('')
const dialogVisible = ref(false)
const editingId = ref(null)
const form = ref({ status: '', notes: '' })

onMounted(() => loadLeads())
async function loadLeads() { loading.value = true; try { leads.value = await getLeads({ search: search.value }) } finally { loading.value = false } }
function showDialog(row) { editingId.value = row.id; form.value = { status: row.status, notes: row.notes }; dialogVisible.value = true }
async function handleSubmit() { try { await updateLead(editingId.value, form.value); ElMessage.success('更新成功'); dialogVisible.value = false; loadLeads() } catch (e) { console.error(e) } }
async function handleDelete(id) { try { await deleteLead(id); ElMessage.success('删除成功'); loadLeads() } catch (e) { console.error(e) } }
async function handleExport() { try { await exportLeads(); ElMessage.success('导出成功') } catch (e) { console.error(e) } }
</script>

<style scoped>.page-header { margin-bottom: 16px; display: flex; gap: 12px; }</style>
