<template>
  <div class="hongguo-settings">
    <div class="page-header">
      <div>
        <h3>AI API 配置</h3>
        <p>系统全局 AI 配置，红果任务和后续 AI 功能都会复用这里的 OpenAI 兼容接口。</p>
      </div>
      <div class="header-actions">
        <el-button :loading="loading" :icon="Refresh" @click="loadSettings">刷新</el-button>
        <el-button @click="router.push('/hongguo')">返回任务</el-button>
      </div>
    </div>

    <div class="settings-grid">
      <el-card>
        <template #header>接口与模型</template>
        <el-form :model="form" label-width="130px" class="settings-form">
          <el-form-item label="启用 AI">
            <el-switch v-model="form.enabled" />
          </el-form-item>

          <el-form-item label="模型预设">
            <el-select v-model="selectedPreset" placeholder="选择预设或自定义" clearable @change="applyPreset">
              <el-option
                v-for="preset in modelPresets"
                :key="preset.label"
                :label="preset.label"
                :value="preset.label"
              />
            </el-select>
          </el-form-item>

          <el-form-item label="接口类型">
            <el-select v-model="form.provider">
              <el-option label="OpenAI 兼容" value="openai_compatible" />
            </el-select>
          </el-form-item>

          <el-form-item label="Base URL" required>
            <el-input v-model="form.base_url" placeholder="https://api.openai.com/v1" />
          </el-form-item>

          <el-form-item label="模型" required>
            <el-input v-model="form.model" placeholder="gpt-4.1-mini / mimo-v2.5" />
          </el-form-item>

          <el-form-item label="密钥环境变量">
            <el-input v-model="form.api_key_env" placeholder="OPENAI_API_KEY" />
          </el-form-item>

          <el-form-item label="API Key">
            <el-input
              v-model="form.api_key"
              type="password"
              show-password
              placeholder="填写后保存为当前配置，留空则继续使用已保存密钥或环境变量"
            />
            <div class="field-hint">
              当前状态：{{ form.api_key_configured ? '已配置' : '未配置' }}{{ apiKeySourceText }}
            </div>
          </el-form-item>

          <el-form-item label="评论范围">
            <el-input
              v-model="form.comment_scope"
              placeholder="例如：根据当前标题生成一个AI内容"
            />
            <div class="field-hint">用户没填评论内容时，会优先使用这里的默认范围。</div>
          </el-form-item>

          <el-form-item label="评论风格">
            <el-select v-model="form.comment_style">
              <el-option label="接地气短评" value="grounded" />
              <el-option label="轻吐槽" value="funny" />
              <el-option label="嗑剧情" value="plot" />
              <el-option label="追更型" value="update" />
              <el-option label="沉浸观众" value="immersive" />
            </el-select>
          </el-form-item>

          <el-form-item label="默认人设">
            <el-input
              v-model="form.default_persona"
              type="textarea"
              :rows="2"
              placeholder="例如：普通红果短剧观众，口语化，爱追反转，评论不要太像广告"
            />
          </el-form-item>

          <el-form-item label="账号人设">
            <div class="persona-list">
              <div v-for="(item, index) in form.account_personas" :key="index" class="persona-row">
                <el-input v-model="item.nickname" placeholder="昵称" />
                <el-input v-model="item.hongguo_id" placeholder="红果ID" />
                <el-select v-model="item.style" placeholder="风格">
                  <el-option label="接地气短评" value="grounded" />
                  <el-option label="轻吐槽" value="funny" />
                  <el-option label="嗑剧情" value="plot" />
                  <el-option label="追更型" value="update" />
                  <el-option label="沉浸观众" value="immersive" />
                </el-select>
                <el-input v-model="item.persona" placeholder="这个账号的人设" />
                <el-button @click="removePersona(index)">删除</el-button>
              </div>
              <el-button @click="addPersona">添加账号人设</el-button>
            </div>
            <div class="field-hint">任务启动时按当前红果账号昵称或红果ID匹配，匹配不到就用默认人设。</div>
          </el-form-item>

          <el-form-item label="超时">
            <el-input-number v-model="form.timeout" :min="5" :max="180" />
            <span class="unit">秒</span>
          </el-form-item>

          <el-form-item label="温度">
            <el-slider v-model="form.temperature" :min="0" :max="2" :step="0.1" class="slider" />
          </el-form-item>

          <el-form-item label="最大 Token">
            <el-input-number v-model="form.max_tokens" :min="32" :max="4096" />
          </el-form-item>

          <el-form-item label="失败降级">
            <el-switch v-model="form.fallback_to_local" />
          </el-form-item>

          <el-form-item>
            <el-button type="primary" :loading="saving" @click="saveSettings">保存并切换</el-button>
            <el-button :loading="testing" @click="testSettings">测试连接</el-button>
          </el-form-item>
        </el-form>
      </el-card>

      <el-card>
        <template #header>
          <div class="card-header">
            <span>Token 消耗</span>
            <el-button size="small" :loading="resetting" @click="resetUsage">清零</el-button>
          </div>
        </template>

        <div class="usage-cards">
          <div class="usage-item">
            <span>请求次数</span>
            <strong>{{ usage.totals.requests }}</strong>
          </div>
          <div class="usage-item">
            <span>输入 Token</span>
            <strong>{{ usage.totals.prompt_tokens }}</strong>
          </div>
          <div class="usage-item">
            <span>输出 Token</span>
            <strong>{{ usage.totals.completion_tokens }}</strong>
          </div>
          <div class="usage-item">
            <span>总 Token</span>
            <strong>{{ usage.totals.total_tokens }}</strong>
          </div>
        </div>

        <el-table :data="modelUsageRows" size="small" class="usage-table">
          <el-table-column prop="model" label="模型" min-width="140" show-overflow-tooltip />
          <el-table-column prop="requests" label="请求" width="70" />
          <el-table-column prop="prompt_tokens" label="输入" width="80" />
          <el-table-column prop="completion_tokens" label="输出" width="80" />
          <el-table-column prop="total_tokens" label="总计" width="90" />
        </el-table>
      </el-card>
    </div>

    <el-alert
      v-if="testResult"
      class="test-result"
      :type="testResult.success ? 'success' : 'error'"
      :closable="false"
      show-icon
    >
      <template #title>
        {{ testResult.success ? '测试成功' : '测试失败' }}
      </template>
      <template #default>
        <div>{{ testResult.success ? testResult.comment : testResult.message }}</div>
        <div v-if="testResult.usage" class="field-hint">
          本次消耗：{{ testResult.usage.total_tokens || 0 }} token
        </div>
      </template>
    </el-alert>
  </div>
</template>

<script setup>
import { computed, reactive, ref, onMounted } from 'vue'
import { useRouter } from 'vue-router'
import { Refresh } from '@element-plus/icons-vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import { getAISettings, updateAISettings, testAISettings, resetAIUsage } from '../api/hongguo'

const router = useRouter()
const loading = ref(false)
const saving = ref(false)
const testing = ref(false)
const resetting = ref(false)
const testResult = ref(null)
const selectedPreset = ref('')
const modelPresets = ref([])

const emptyUsage = () => ({
  totals: { requests: 0, prompt_tokens: 0, completion_tokens: 0, total_tokens: 0 },
  by_model: {},
  recent: [],
})

const usage = reactive(emptyUsage())

const form = reactive({
  enabled: true,
  provider: 'openai_compatible',
  api_key_env: 'OPENAI_API_KEY',
  api_key: '',
  api_key_configured: false,
  api_key_source: '',
  base_url: 'https://api.openai.com/v1',
  model: 'gpt-4.1-mini',
  timeout: 30,
  temperature: 0.8,
  max_tokens: 512,
  fallback_to_local: true,
  comment_scope: '根据当前标题生成一个AI内容',
  comment_style: 'grounded',
  default_persona: '普通红果短剧观众，口语化，像刷剧时顺手发一句真实感受',
  account_personas: [],
})

const modelUsageRows = computed(() => Object.values(usage.by_model || {}))
const apiKeySourceText = computed(() => {
  if (!form.api_key_configured) return ''
  if (form.api_key_source === 'saved') return '（使用已保存 API Key）'
  if (form.api_key_source === 'env') return `（使用环境变量 ${form.api_key_env}）`
  return ''
})

function assignUsage(data) {
  const next = data || emptyUsage()
  usage.totals = next.totals || emptyUsage().totals
  usage.by_model = next.by_model || {}
  usage.recent = next.recent || []
}

function assignSettings(data) {
  Object.assign(form, data || {})
  form.api_key = ''
  form.comment_scope = form.comment_scope || '根据当前标题生成一个AI内容'
  form.comment_style = form.comment_style || 'grounded'
  form.default_persona = form.default_persona || '普通红果短剧观众，口语化，像刷剧时顺手发一句真实感受'
  form.account_personas = Array.isArray(form.account_personas) ? form.account_personas : []
  modelPresets.value = data?.model_presets || modelPresets.value
  assignUsage(data?.usage)
  selectedPreset.value = findCurrentPreset()
}

function findCurrentPreset() {
  const match = modelPresets.value.find((preset) =>
    preset.provider === form.provider &&
    preset.base_url === form.base_url &&
    preset.model === form.model
  )
  return match?.label || ''
}

function applyPreset(label) {
  const preset = modelPresets.value.find((item) => item.label === label)
  if (!preset) return
  form.provider = preset.provider
  form.base_url = preset.base_url
  form.model = preset.model
  form.api_key_env = preset.api_key_env
}

function payload() {
  const data = { ...form }
  data.account_personas = (data.account_personas || [])
    .map((item) => ({
      nickname: (item.nickname || '').trim(),
      hongguo_id: (item.hongguo_id || '').trim(),
      persona: (item.persona || '').trim(),
      style: item.style || '',
    }))
    .filter((item) => item.nickname || item.hongguo_id || item.persona || item.style)
  delete data.api_key_configured
  delete data.model_presets
  delete data.usage
  if (!data.api_key) delete data.api_key
  return data
}

function addPersona() {
  form.account_personas.push({
    nickname: '',
    hongguo_id: '',
    persona: '',
    style: form.comment_style || 'grounded',
  })
}

function removePersona(index) {
  form.account_personas.splice(index, 1)
}

async function loadSettings() {
  loading.value = true
  try {
    assignSettings(await getAISettings())
  } finally {
    loading.value = false
  }
}

async function saveSettings() {
  saving.value = true
  try {
    assignSettings(await updateAISettings(payload()))
    ElMessage.success('配置已保存，后续生成会使用当前模型')
  } finally {
    saving.value = false
  }
}

async function testSettings() {
  testing.value = true
  testResult.value = null
  try {
    testResult.value = await testAISettings(payload())
    if (testResult.value?.stats) assignUsage(testResult.value.stats)
  } finally {
    testing.value = false
  }
}

async function resetUsage() {
  await ElMessageBox.confirm('确定清零红果 AI Token 统计吗？', '清零确认', {
    type: 'warning',
    confirmButtonText: '清零',
    cancelButtonText: '取消',
  })
  resetting.value = true
  try {
    assignUsage(await resetAIUsage())
    ElMessage.success('Token 统计已清零')
  } finally {
    resetting.value = false
  }
}

onMounted(loadSettings)
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
.header-actions,
.card-header {
  display: flex;
  align-items: center;
  gap: 10px;
}
.card-header {
  justify-content: space-between;
}
.settings-grid {
  display: grid;
  grid-template-columns: minmax(520px, 1fr) minmax(360px, 0.75fr);
  gap: 16px;
}
.settings-form {
  max-width: 760px;
}
.field-hint {
  margin-top: 6px;
  color: var(--text-secondary);
  font-size: 13px;
}
.unit {
  margin-left: 8px;
  color: var(--text-secondary);
}
.slider {
  width: 280px;
}
.persona-list {
  width: 100%;
}
.persona-row {
  display: grid;
  grid-template-columns: minmax(100px, 0.8fr) minmax(110px, 0.9fr) minmax(120px, 0.8fr) minmax(180px, 1.4fr) auto;
  gap: 8px;
  margin-bottom: 8px;
}
.usage-cards {
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  gap: 10px;
}
.usage-item {
  padding: 12px;
  border: 1px solid var(--border-color);
  border-radius: 8px;
  background: var(--bg-primary);
}
.usage-item span {
  display: block;
  color: var(--text-secondary);
  font-size: 12px;
}
.usage-item strong {
  display: block;
  margin-top: 6px;
  color: var(--text-primary);
  font-size: 20px;
}
.usage-table,
.test-result {
  margin-top: 16px;
}
@media (max-width: 1100px) {
  .settings-grid {
    grid-template-columns: 1fr;
  }
  .persona-row {
    grid-template-columns: 1fr;
  }
}
</style>
