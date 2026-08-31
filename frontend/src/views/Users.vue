<template>
  <div class="users-page">
    <div class="page-header">
      <div>
        <h2><el-icon><UserFilled /></el-icon> 账号管理</h2>
        <span class="summary">共 {{ users.length }} 个公司账号</span>
      </div>
      <el-button type="primary" @click="showDialog()">
        <el-icon><Plus /></el-icon>
        新增账号
      </el-button>
    </div>

    <el-table :data="users" v-loading="loading" border class="users-table">
      <el-table-column prop="username" label="用户名" min-width="130" />
      <el-table-column prop="nickname" label="姓名" min-width="120">
        <template #default="{ row }">{{ row.nickname || '-' }}</template>
      </el-table-column>
      <el-table-column prop="position" label="职位" min-width="120">
        <template #default="{ row }">{{ row.position || '-' }}</template>
      </el-table-column>
      <el-table-column prop="role" label="角色" width="100">
        <template #default="{ row }">
          <el-tag :type="row.role === 'admin' ? 'danger' : 'info'" size="small">
            {{ row.role === 'admin' ? '管理员' : '员工' }}
          </el-tag>
        </template>
      </el-table-column>
      <el-table-column prop="status" label="状态" width="100">
        <template #default="{ row }">
          <el-tag :type="statusType(row)" size="small">{{ statusText(row) }}</el-tag>
        </template>
      </el-table-column>
      <el-table-column prop="expire_at" label="有效期" min-width="180">
        <template #default="{ row }">
          <div>{{ formatDate(row.expire_at) }}</div>
          <small v-if="row.status === 'active'" class="muted">剩余 {{ row.days_remaining }} 天</small>
        </template>
      </el-table-column>
      <el-table-column prop="last_login" label="最后登录" min-width="180">
        <template #default="{ row }">{{ row.last_login ? formatDate(row.last_login) : '尚未登录' }}</template>
      </el-table-column>
      <el-table-column label="操作" width="230" fixed="right">
        <template #default="{ row }">
          <el-button link type="primary" @click="showDialog(row)">编辑</el-button>
          <el-button
            link
            :type="row.status === 'active' ? 'warning' : 'success'"
            @click="toggleStatus(row)"
          >
            {{ row.status === 'active' ? '禁用' : '启用' }}
          </el-button>
          <el-button link type="danger" @click="handleDelete(row)">删除</el-button>
        </template>
      </el-table-column>
    </el-table>

    <el-dialog
      v-model="dialogVisible"
      :title="editingId ? '编辑账号' : '新增账号'"
      width="540px"
      :close-on-click-modal="false"
    >
      <el-form ref="formRef" :model="form" :rules="rules" label-width="92px">
        <el-form-item label="用户名" prop="username">
          <el-input v-model="form.username" :disabled="Boolean(editingId)" maxlength="64" />
        </el-form-item>
        <el-form-item label="姓名" prop="nickname">
          <el-input v-model="form.nickname" maxlength="64" />
        </el-form-item>
        <el-form-item label="手机号" prop="phone">
          <el-input v-model="form.phone" maxlength="20" />
        </el-form-item>
        <el-form-item label="职位" prop="position">
          <el-input v-model="form.position" maxlength="64" />
        </el-form-item>
        <el-form-item :label="editingId ? '重置密码' : '初始密码'" prop="password">
          <el-input
            v-model="form.password"
            type="password"
            show-password
            maxlength="256"
            :placeholder="editingId ? '不修改请留空' : '至少 8 位'"
          />
        </el-form-item>
        <el-form-item label="角色" prop="role">
          <el-segmented
            v-model="form.role"
            :options="[{ label: '员工', value: 'user' }, { label: '管理员', value: 'admin' }]"
          />
        </el-form-item>
        <el-form-item v-if="editingId" label="状态" prop="status">
          <el-switch v-model="form.status" active-value="active" inactive-value="disabled" active-text="启用" inactive-text="禁用" />
        </el-form-item>
        <el-form-item :label="editingId ? '续期天数' : '有效天数'" prop="usage_days">
          <el-input-number v-model="form.usage_days" :min="1" :max="36500" controls-position="right" />
          <span v-if="editingId" class="field-help">留空则保持原到期时间</span>
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="dialogVisible = false">取消</el-button>
        <el-button type="primary" :loading="saving" @click="handleSubmit">保存</el-button>
      </template>
    </el-dialog>
  </div>
</template>

<script setup>
import { onMounted, reactive, ref } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import { createUser, deleteUser, getUsers, updateUser } from '@/api'

const users = ref([])
const loading = ref(false)
const saving = ref(false)
const dialogVisible = ref(false)
const editingId = ref(null)
const formRef = ref(null)
const defaultForm = {
  username: '', nickname: '', phone: '', position: '', password: '',
  role: 'user', status: 'active', usage_days: 30,
}
const form = reactive({ ...defaultForm })
const rules = {
  username: [{ required: true, message: '请输入用户名', trigger: 'blur' }],
  password: [{ validator: validatePassword, trigger: 'blur' }],
  usage_days: [{ validator: validateUsageDays, trigger: 'change' }],
}

onMounted(loadUsers)

function validatePassword(_rule, value, callback) {
  if (!editingId.value && !value) return callback(new Error('请输入初始密码'))
  if (value && value.length < 8) return callback(new Error('密码至少 8 位'))
  callback()
}

function validateUsageDays(_rule, value, callback) {
  if (!editingId.value && !value) return callback(new Error('请设置有效天数'))
  callback()
}

async function loadUsers() {
  loading.value = true
  try {
    users.value = await getUsers()
  } finally {
    loading.value = false
  }
}

function showDialog(row) {
  editingId.value = row?.id || null
  Object.assign(form, defaultForm, row ? {
    username: row.username,
    nickname: row.nickname || '',
    phone: row.phone || '',
    position: row.position || '',
    password: '',
    role: row.role,
    status: row.status,
    usage_days: null,
  } : {})
  dialogVisible.value = true
  formRef.value?.clearValidate()
}

async function handleSubmit() {
  if (!await formRef.value.validate().catch(() => false)) return
  saving.value = true
  try {
    const payload = { ...form }
    if (editingId.value) {
      delete payload.username
      if (!payload.password) delete payload.password
      if (!payload.usage_days) delete payload.usage_days
      await updateUser(editingId.value, payload)
      ElMessage.success('账号已更新，权限变更立即生效')
    } else {
      delete payload.status
      await createUser(payload)
      ElMessage.success('账号已创建')
    }
    dialogVisible.value = false
    await loadUsers()
  } finally {
    saving.value = false
  }
}

async function toggleStatus(row) {
  const next = row.status === 'active' ? 'disabled' : 'active'
  await ElMessageBox.confirm(
    `确定${next === 'active' ? '启用' : '禁用'}账号“${row.username}”吗？`,
    '账号状态确认',
    { type: 'warning' },
  )
  await updateUser(row.id, { status: next })
  ElMessage.success(next === 'active' ? '账号已启用' : '账号已禁用')
  await loadUsers()
}

async function handleDelete(row) {
  await ElMessageBox.confirm(
    `确定删除账号“${row.username}”吗？该账号将无法再次登录。`,
    '删除账号',
    { type: 'warning', confirmButtonText: '删除', confirmButtonClass: 'el-button--danger' },
  )
  await deleteUser(row.id)
  ElMessage.success('账号已删除')
  await loadUsers()
}

function formatDate(value) {
  if (!value) return '永久'
  const text = String(value)
  const hasTimezone = /(?:Z|[+-]\d{2}:?\d{2})$/i.test(text)
  const normalized = hasTimezone ? text : `${text.replace(' ', 'T')}Z`
  return new Date(normalized).toLocaleString('zh-CN', { hour12: false })
}

function statusText(row) {
  if (row.status !== 'active') return '已禁用'
  return row.is_active ? '正常' : '已到期'
}

function statusType(row) {
  if (row.status !== 'active') return 'info'
  return row.is_active ? 'success' : 'danger'
}
</script>

<style scoped>
.users-page { min-width: 760px; }
.page-header { display: flex; justify-content: space-between; align-items: center; margin-bottom: 16px; }
.page-header h2 { display: flex; align-items: center; gap: 8px; margin: 0 0 4px; color: var(--text-primary); font-size: 18px; }
.summary, .muted, .field-help { color: var(--text-secondary); }
.field-help { margin-left: 10px; font-size: 12px; }
.users-table { width: 100%; }
</style>
