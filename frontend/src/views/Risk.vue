<template>
  <div class="risk-page">
    <el-tabs v-model="activeTab" @tab-change="loadData">
      <el-tab-pane label="风控规则" name="rules">
        <div class="tab-header">
          <el-button type="primary" @click="showRuleDialog()"><el-icon><Plus /></el-icon> 新增规则</el-button>
        </div>
        <el-card>
          <el-table :data="rules" style="width: 100%" v-loading="loading">
            <el-table-column prop="id" label="ID" width="60" />
            <el-table-column prop="name" label="规则名称" />
            <el-table-column prop="type" label="类型" width="120">
              <template #default="{ row }"><el-tag size="small">{{ row.type }}</el-tag></template>
            </el-table-column>
            <el-table-column prop="condition" label="条件" min-width="200" show-overflow-tooltip />
            <el-table-column prop="action" label="动作" width="120" />
            <el-table-column prop="enabled" label="状态" width="80">
              <template #default="{ row }">
                <el-tag :type="row.enabled ? 'success' : 'info'" size="small">{{ row.enabled ? '启用' : '禁用' }}</el-tag>
              </template>
            </el-table-column>
            <el-table-column label="操作" width="100">
              <template #default="{ row }">
                <el-popconfirm title="确定删除?" @confirm="deleteRule(row.id)">
                  <template #reference><el-button link type="danger">删除</el-button></template>
                </el-popconfirm>
              </template>
            </el-table-column>
          </el-table>
        </el-card>
      </el-tab-pane>

      <el-tab-pane label="敏感词" name="sensitive">
        <div class="tab-header">
          <el-button type="primary" @click="showWordDialog()"><el-icon><Plus /></el-icon> 新增敏感词</el-button>
          <el-button @click="checkWords"><el-icon><Search /></el-icon> 检查文本</el-button>
        </div>
        <el-card>
          <el-table :data="sensitiveWords" style="width: 100%" v-loading="loading">
            <el-table-column prop="id" label="ID" width="60" />
            <el-table-column prop="word" label="敏感词" />
            <el-table-column prop="category" label="分类" width="120">
              <template #default="{ row }"><el-tag size="small">{{ row.category || '通用' }}</el-tag></template>
            </el-table-column>
            <el-table-column prop="created_at" label="添加时间" width="180" />
            <el-table-column label="操作" width="100">
              <template #default="{ row }">
                <el-popconfirm title="确定删除?" @confirm="deleteWord(row.id)">
                  <template #reference><el-button link type="danger">删除</el-button></template>
                </el-popconfirm>
              </template>
            </el-table-column>
          </el-table>
        </el-card>
      </el-tab-pane>

      <el-tab-pane label="黑名单" name="blacklist">
        <div class="tab-header">
          <el-button type="primary" @click="showBlacklistDialog()"><el-icon><Plus /></el-icon> 新增黑名单</el-button>
          <el-button @click="checkBlacklist"><el-icon><Search /></el-icon> 检查账号</el-button>
        </div>
        <el-card>
          <el-table :data="blacklist" style="width: 100%" v-loading="loading">
            <el-table-column prop="id" label="ID" width="60" />
            <el-table-column prop="account" label="账号" />
            <el-table-column prop="reason" label="原因" min-width="200" show-overflow-tooltip />
            <el-table-column prop="created_at" label="添加时间" width="180" />
            <el-table-column label="操作" width="100">
              <template #default="{ row }">
                <el-popconfirm title="确定删除?" @confirm="deleteBlacklist(row.id)">
                  <template #reference><el-button link type="danger">删除</el-button></template>
                </el-popconfirm>
              </template>
            </el-table-column>
          </el-table>
        </el-card>
      </el-tab-pane>
    </el-tabs>

    <el-dialog v-model="ruleDialogVisible" title="新增风控规则" width="500px">
      <el-form :model="ruleForm" label-width="80px">
        <el-form-item label="规则名称"><el-input v-model="ruleForm.name" /></el-form-item>
        <el-form-item label="类型">
          <el-select v-model="ruleForm.type" style="width: 100%">
            <el-option label="频率限制" value="rate_limit" />
            <el-option label="内容过滤" value="content_filter" />
            <el-option label="行为检测" value="behavior" />
          </el-select>
        </el-form-item>
        <el-form-item label="条件"><el-input v-model="ruleForm.condition" type="textarea" /></el-form-item>
        <el-form-item label="动作">
          <el-select v-model="ruleForm.action" style="width: 100%">
            <el-option label="阻止" value="block" />
            <el-option label="告警" value="warn" />
            <el-option label="记录" value="log" />
          </el-select>
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="ruleDialogVisible = false">取消</el-button>
        <el-button type="primary" @click="submitRule">确定</el-button>
      </template>
    </el-dialog>

    <el-dialog v-model="wordDialogVisible" title="新增敏感词" width="500px">
      <el-form :model="wordForm" label-width="80px">
        <el-form-item label="敏感词"><el-input v-model="wordForm.word" /></el-form-item>
        <el-form-item label="分类"><el-input v-model="wordForm.category" /></el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="wordDialogVisible = false">取消</el-button>
        <el-button type="primary" @click="submitWord">确定</el-button>
      </template>
    </el-dialog>

    <el-dialog v-model="blacklistDialogVisible" title="新增黑名单" width="500px">
      <el-form :model="blacklistForm" label-width="80px">
        <el-form-item label="账号"><el-input v-model="blacklistForm.account" /></el-form-item>
        <el-form-item label="原因"><el-input v-model="blacklistForm.reason" type="textarea" /></el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="blacklistDialogVisible = false">取消</el-button>
        <el-button type="primary" @click="submitBlacklist">确定</el-button>
      </template>
    </el-dialog>

    <el-dialog v-model="checkDialogVisible" title="文本检查" width="500px">
      <el-input v-model="checkText" type="textarea" :rows="4" placeholder="输入要检查的文本" />
      <div v-if="checkResult.length" class="check-result">
        <el-tag v-for="w in checkResult" :key="w" type="danger" style="margin: 4px;">{{ w }}</el-tag>
      </div>
      <template #footer>
        <el-button @click="checkDialogVisible = false">关闭</el-button>
        <el-button type="primary" @click="runCheck">检查</el-button>
      </template>
    </el-dialog>
  </div>
</template>

<script setup>
import { ref, onMounted } from 'vue'
import api from '@/api'
import { ElMessage } from 'element-plus'

const activeTab = ref('rules')
const loading = ref(false)
const rules = ref([])
const sensitiveWords = ref([])
const blacklist = ref([])

const ruleDialogVisible = ref(false)
const wordDialogVisible = ref(false)
const blacklistDialogVisible = ref(false)
const checkDialogVisible = ref(false)

const ruleForm = ref({ name: '', type: 'rate_limit', condition: '', action: 'block' })
const wordForm = ref({ word: '', category: '' })
const blacklistForm = ref({ account: '', reason: '' })
const checkText = ref('')
const checkResult = ref([])

onMounted(() => loadData())

async function loadData() {
  loading.value = true
  try {
    if (activeTab.value === 'rules') {
      const res = await api.get('/risk/rules')
      rules.value = Array.isArray(res) ? res : (res.data || res.items || [])
    } else if (activeTab.value === 'sensitive') {
      const res = await api.get('/risk/sensitive-words')
      sensitiveWords.value = Array.isArray(res) ? res : (res.data || res.items || [])
    } else {
      const res = await api.get('/risk/blacklist')
      blacklist.value = Array.isArray(res) ? res : (res.data || res.items || [])
    }
  } catch (e) { console.error(e) }
  finally { loading.value = false }
}

function showRuleDialog() {
  ruleForm.value = { name: '', type: 'rate_limit', condition: '', action: 'block' }
  ruleDialogVisible.value = true
}

async function submitRule() {
  try {
    await api.post('/risk/rules', ruleForm.value)
    ElMessage.success('规则添加成功')
    ruleDialogVisible.value = false
    loadData()
  } catch (e) { console.error(e) }
}

async function deleteRule(id) {
  try {
    await api.delete('/risk/rules/' + id)
    ElMessage.success('删除成功')
    loadData()
  } catch (e) { console.error(e) }
}

function showWordDialog() {
  wordForm.value = { word: '', category: '' }
  wordDialogVisible.value = true
}

async function submitWord() {
  try {
    await api.post('/risk/sensitive-words', wordForm.value)
    ElMessage.success('敏感词添加成功')
    wordDialogVisible.value = false
    loadData()
  } catch (e) { console.error(e) }
}

async function deleteWord(id) {
  try {
    await api.delete('/risk/sensitive-words/' + id)
    ElMessage.success('删除成功')
    loadData()
  } catch (e) { console.error(e) }
}

function checkWords() {
  checkText.value = ''
  checkResult.value = []
  checkDialogVisible.value = true
}

async function runCheck() {
  try {
    const res = await api.post('/risk/sensitive-words/check', { text: checkText.value })
    checkResult.value = res.found || res.words || res.data || []
    if (checkResult.value.length === 0) ElMessage.success('未发现敏感词')
  } catch (e) { console.error(e) }
}

function showBlacklistDialog() {
  blacklistForm.value = { account: '', reason: '' }
  blacklistDialogVisible.value = true
}

async function submitBlacklist() {
  try {
    await api.post('/risk/blacklist', blacklistForm.value)
    ElMessage.success('黑名单添加成功')
    blacklistDialogVisible.value = false
    loadData()
  } catch (e) { console.error(e) }
}

async function deleteBlacklist(id) {
  try {
    await api.delete('/risk/blacklist/' + id)
    ElMessage.success('删除成功')
    loadData()
  } catch (e) { console.error(e) }
}

function checkBlacklist() {
  checkText.value = ''
  checkResult.value = []
  checkDialogVisible.value = true
}
</script>

<style scoped>
.tab-header {
  margin-bottom: 16px;
  display: flex;
  gap: 12px;
}
.check-result {
  margin-top: 16px;
  padding: 12px;
  background: var(--bg-input);
  border-radius: 8px;
}
</style>
