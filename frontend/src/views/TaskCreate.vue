<template>
  <div class="task-create">
    <div class="page-header">
      <h3>新建红果评论任务</h3>
      <el-button @click="router.push('/hongguo')">返回列表</el-button>
    </div>

    <el-card>
      <el-form :model="form" label-width="130px" style="max-width: 680px">
        <el-form-item label="搜索剧名" required>
          <el-input v-model="form.drama_name" placeholder="输入红果短剧名称或搜索关键词" />
        </el-form-item>

        <el-form-item label="评论模式">
          <el-radio-group v-model="form.comment_mode">
            <el-radio value="specified">指定集数</el-radio>
            <el-radio value="random">随机集数</el-radio>
          </el-radio-group>
        </el-form-item>

        <template v-if="form.comment_mode === 'specified'">
          <el-form-item label="起始集数">
            <el-input-number v-model="form.start_episode" :min="1" />
          </el-form-item>
          <el-form-item label="集数间隔">
            <el-input-number v-model="form.episode_interval" :min="1" />
            <span class="field-hint">每隔 N 集评论一次</span>
          </el-form-item>
          <el-form-item label="评论间隔">
            <el-input-number v-model="form.comment_interval_sec" :min="1" />
            <span class="field-hint">秒</span>
          </el-form-item>
        </template>

        <template v-else>
          <el-form-item label="评论次数">
            <el-input-number v-model="form.random_comment_count" :min="1" />
          </el-form-item>
          <el-form-item label="最小间隔">
            <el-input-number v-model="form.random_min_interval" :min="1" />
            <span class="field-hint">秒</span>
          </el-form-item>
          <el-form-item label="最大间隔">
            <el-input-number v-model="form.random_max_interval" :min="1" />
            <span class="field-hint">秒</span>
          </el-form-item>
        </template>

        <el-form-item label="内容来源">
          <el-radio-group v-model="form.content_source">
            <el-radio value="ai">AI 生成</el-radio>
            <el-radio value="template">模板抽取</el-radio>
            <el-radio value="mixed">混合</el-radio>
          </el-radio-group>
        </el-form-item>

        <el-form-item label="倍速刷剧">
          <el-select v-model="form.playback_speed" style="width: 180px">
            <el-option v-for="item in playbackSpeedOptions" :key="item.value" :label="item.label" :value="item.value" />
          </el-select>
          <span class="field-hint">默认 1.0x，可在任务执行时切换</span>
        </el-form-item>

        <el-form-item label="评论模板">
          <el-input
            v-model="templateText"
            type="textarea"
            :rows="5"
            placeholder="每行一条评论模板。内容来源选择模板或混合时会使用。"
          />
        </el-form-item>

        <el-form-item>
          <el-button type="primary" :loading="submitting" @click="handleSubmit">创建任务</el-button>
          <el-button @click="router.push('/hongguo')">取消</el-button>
        </el-form-item>
      </el-form>
    </el-card>
  </div>
</template>

<script setup>
import { computed, reactive, ref, onMounted } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { ElMessage } from 'element-plus'
import { createTask, getTask, updateTask } from '../api/hongguo'

const route = useRoute()
const router = useRouter()
const submitting = ref(false)
const templateText = ref('')
const editingId = computed(() => route.query.id ? Number(route.query.id) : null)
const form = reactive({
  drama_name: '',
  comment_mode: 'specified',
  start_episode: 1,
  episode_interval: 2,
  comment_interval_sec: 30,
  random_comment_count: 10,
  random_min_interval: 20,
  random_max_interval: 60,
  content_source: 'ai',
  playback_speed: '1.0x',
  templates: []
})

const playbackSpeedOptions = [
  { label: '0.75x', value: '0.75x' },
  { label: '1.0x (默认)', value: '1.0x' },
  { label: '1.25x', value: '1.25x' },
  { label: '1.5x', value: '1.5x' },
  { label: '2.0x', value: '2.0x' },
  { label: '3.0x', value: '3.0x' },
]

async function loadTaskForEdit() {
  if (!editingId.value) return
  const task = await getTask(editingId.value)
  Object.assign(form, {
    drama_name: task.drama_name || '',
    comment_mode: task.comment_mode || 'specified',
    start_episode: task.start_episode || 1,
    episode_interval: task.episode_interval || 1,
    comment_interval_sec: task.comment_interval_sec || 30,
    random_comment_count: task.random_comment_count || 10,
    random_min_interval: task.random_min_interval || 20,
    random_max_interval: task.random_max_interval || 60,
    content_source: task.content_source || 'ai',
    playback_speed: task.playback_speed || '1.0x',
    templates: task.templates || [],
  })
  templateText.value = (task.templates || []).join('\n')
}

async function handleSubmit() {
  if (!form.drama_name.trim()) {
    ElMessage.warning('请输入短剧名称')
    return
  }
  if (form.comment_mode === 'random' && form.random_min_interval > form.random_max_interval) {
    ElMessage.warning('最大间隔必须大于等于最小间隔')
    return
  }

  submitting.value = true
  try {
    const payload = {
      ...form,
      drama_name: form.drama_name.trim(),
      templates: templateText.value.split('\n').map(item => item.trim()).filter(Boolean)
    }
    if (editingId.value) {
      await updateTask(editingId.value, payload)
      ElMessage.success('任务已更新')
    } else {
      await createTask(payload)
      ElMessage.success('任务创建成功')
    }
    router.push('/hongguo')
  } finally {
    submitting.value = false
  }
}

onMounted(loadTaskForEdit)
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
.field-hint {
  margin-left: 10px;
  color: var(--text-secondary);
  font-size: 13px;
}
</style>
