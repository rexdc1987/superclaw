<template>
  <div class="douyin-comment-page">
    <!-- 侧边栏 -->
    <aside class="sidebar">
      <div class="sidebar-brand">
        <el-icon><Monitor /></el-icon>
        <span>SuperClaw</span>
      </div>
      <el-menu :default-active="'/douyin-comment'" router background-color="#1a1a2e" text-color="#aaa" active-text-color="#8b8bff">
        <el-menu-item index="/">
          <el-icon><DataAnalysis /></el-icon>
          <span>概览</span>
        </el-menu-item>
        <el-menu-item index="/douyin-comment">
          <el-icon><VideoCamera /></el-icon>
          <span>抖音评论</span>
        </el-menu-item>
      </el-menu>
    </aside>

    <!-- 主区域 -->
    <div class="main-area">
      <div class="topbar">
        <h2><el-icon><VideoCamera /></el-icon> 抖音自动评论</h2>
        <el-tag :type="statusType" effect="dark">{{ statusText }}</el-tag>
      </div>

      <div class="content-grid">
        <!-- ===== 左栏 ===== -->
        <div class="left-col">

          <!-- 区块1: 账号选择 -->
          <el-card shadow="hover" class="block">
            <template #header>
              <div class="block-header" @click="toggleBlock('account')">
                <el-icon><User /></el-icon> 账号选择
                <el-icon class="arrow" :class="{ collapsed: !blocks.account }"><ArrowDown /></el-icon>
              </div>
            </template>
            <div v-show="blocks.account">
              <div v-for="acc in accounts" :key="acc.id"
                class="acc-card" :class="{ selected: selectedAccount === acc.id }"
                @click="selectedAccount = acc.id">
                <el-badge :type="getLoginBadgeType(acc)" dot>
                  <span class="acc-name">{{ acc.name }}</span>
                </el-badge>
                <span class="acc-meta">{{ acc.loginStatusText }}</span>
              </div>
              <el-empty v-if="!accounts.length" description="暂无账号，请先到账号管理添加" :image-size="60" />
            </div>
          </el-card>

          <!-- 区块2: 搜索配置 -->
          <el-card shadow="hover" class="block">
            <template #header>
              <div class="block-header" @click="toggleBlock('search')">
                <el-icon><Search /></el-icon> 搜索配置
                <el-icon class="arrow" :class="{ collapsed: !blocks.search }"><ArrowDown /></el-icon>
              </div>
            </template>
            <div v-show="blocks.search">
              <el-form-item label="搜索关键词（每行一个）">
                <el-input v-model="form.keywords" type="textarea" :rows="3" placeholder="香港移民&#10;移民政策&#10;人才引进" />
              </el-form-item>
              <el-row :gutter="12">
                <el-col :span="12">
                  <el-form-item label="时间筛选">
                    <el-select v-model="form.time_range" style="width:100%">
                      <el-option label="不限" :value="0" />
                      <el-option label="一天内" :value="1" />
                      <el-option label="一周内" :value="7" />
                      <el-option label="一个月内" :value="30" />
                    </el-select>
                  </el-form-item>
                </el-col>
                <el-col :span="12">
                  <el-form-item label="排序方式">
                    <el-select v-model="form.sort_by" style="width:100%">
                      <el-option label="综合排序" value="general" />
                      <el-option label="最新" value="latest" />
                      <el-option label="最热" value="hottest" />
                    </el-select>
                  </el-form-item>
                </el-col>
              </el-row>
            </div>
          </el-card>

          <!-- 区块3: 节奏控制 -->
          <el-card shadow="hover" class="block">
            <template #header>
              <div class="block-header" @click="toggleBlock('rhythm')">
                <el-icon><Timer /></el-icon> 节奏控制
                <el-icon class="arrow" :class="{ collapsed: !blocks.rhythm }"><ArrowDown /></el-icon>
              </div>
            </template>
            <div v-show="blocks.rhythm">
              <el-row :gutter="12">
                <el-col :span="8">
                  <el-form-item label="评论视频数量">
                    <el-input-number v-model="form.video_count" :min="1" :max="100" style="width:100%" />
                  </el-form-item>
                </el-col>
                <el-col :span="8">
                  <el-form-item label="每N个换关键词">
                    <el-input-number v-model="form.keyword_rotate_after" :min="1" style="width:100%" />
                  </el-form-item>
                </el-col>
                <el-col :span="8">
                  <el-form-item label="每N次休息">
                    <el-input-number v-model="form.rest_after" :min="1" style="width:100%" />
                  </el-form-item>
                </el-col>
              </el-row>
              <el-row :gutter="12">
                <el-col :span="12">
                  <el-form-item label="评论间隔（秒）">
                    <div class="range-row">
                      <el-input-number v-model="form.comment_interval[0]" :min="0" :max="60" size="small" />
                      <span>~</span>
                      <el-input-number v-model="form.comment_interval[1]" :min="1" :max="120" size="small" />
                    </div>
                  </el-form-item>
                </el-col>
                <el-col :span="12">
                  <el-form-item label="休息间隔（秒）">
                    <div class="range-row">
                      <el-input-number v-model="form.rest_interval[0]" :min="1" :max="60" size="small" />
                      <span>~</span>
                      <el-input-number v-model="form.rest_interval[1]" :min="2" :max="300" size="small" />
                    </div>
                  </el-form-item>
                </el-col>
              </el-row>
            </div>
          </el-card>

          <!-- 区块4: 评论内容 -->
          <el-card shadow="hover" class="block">
            <template #header>
              <div class="block-header" @click="toggleBlock('comment')">
                <el-icon><ChatDotRound /></el-icon> 评论内容
                <el-icon class="arrow" :class="{ collapsed: !blocks.comment }"><ArrowDown /></el-icon>
              </div>
            </template>
            <div v-show="blocks.comment">
              <el-form-item label="评论内容（每行一条，随机抽取）">
                <el-input v-model="form.comments" type="textarea" :rows="4" placeholder="太棒了！&#10;学到了很多&#10;感谢分享" />
              </el-form-item>
              <el-checkbox v-model="form.use_mention">@用户</el-checkbox>
              <el-input v-if="form.use_mention" v-model="form.mention_user" placeholder="如：豆包/风启" size="small" style="margin-top:6px" />
              <el-checkbox v-model="form.send_image" style="margin-top:10px">发图片</el-checkbox>
              <el-input v-if="form.send_image" v-model="form.image_folder" placeholder="图片文件夹路径" size="small" style="margin-top:6px" />
            </div>
          </el-card>
        </div>

        <!-- ===== 右栏 ===== -->
        <div class="right-col">

          <!-- 区块5: 过滤筛选 -->
          <el-card shadow="hover" class="block">
            <template #header>
              <div class="block-header" @click="toggleBlock('filter')">
                <el-icon><Filter /></el-icon> 过滤筛选
                <el-icon class="arrow" :class="{ collapsed: !blocks.filter }"><ArrowDown /></el-icon>
              </div>
            </template>
            <div v-show="blocks.filter">
              <el-checkbox v-model="form.use_province">过滤省份</el-checkbox>
              <el-select v-if="form.use_province" v-model="form.filter_province" multiple placeholder="选择省份" style="width:100%;margin-top:6px">
                <el-option v-for="p in provinces" :key="p" :label="p" :value="p" />
              </el-select>

              <el-checkbox v-model="form.use_filter_time" style="margin-top:12px">过滤时间</el-checkbox>
              <el-select v-if="form.use_filter_time" v-model="form.filter_time" style="width:100%;margin-top:6px">
                <el-option label="不限" :value="0" /><el-option label="一天内" :value="1" />
                <el-option label="一周内" :value="7" /><el-option label="一个月内" :value="30" />
              </el-select>

              <el-checkbox v-model="form.use_filter_kw" style="margin-top:12px">评论区关键词筛选</el-checkbox>
              <el-input v-if="form.use_filter_kw" v-model="form.filter_keywords_str" placeholder="空格分隔多个关键词" size="small" style="margin-top:6px" />

              <el-form-item label="筛选数据量" style="margin-top:10px">
                <el-input-number v-model="form.filter_count" :min="1" :max="50" />
              </el-form-item>
            </div>
          </el-card>

          <!-- 区块6: 互动行为 -->
          <el-card shadow="hover" class="block">
            <template #header>
              <div class="block-header" @click="toggleBlock('action')">
                <el-icon><Pointer /></el-icon> 互动行为
                <el-icon class="arrow" :class="{ collapsed: !blocks.action }"><ArrowDown /></el-icon>
              </div>
            </template>
            <div v-show="blocks.action">
              <el-row :gutter="12">
                <el-col :span="6"><el-checkbox v-model="form.actions.like">点赞</el-checkbox></el-col>
                <el-col :span="6"><el-checkbox v-model="form.actions.follow">关注</el-checkbox></el-col>
                <el-col :span="6"><el-checkbox v-model="form.actions.favorite">收藏</el-checkbox></el-col>
                <el-col :span="6"><el-checkbox v-model="form.actions.view">浏览</el-checkbox></el-col>
              </el-row>
            </div>
          </el-card>

          <!-- 区块7+8: 执行控制 + 结果 -->
          <el-card shadow="hover" class="block">
            <template #header><div class="block-header"><el-icon><CaretRight /></el-icon> 执行控制 & 结果</div></template>

            <el-alert :title="statusText" :type="statusType" show-icon :closable="false" style="margin-bottom:12px" />

            <div class="btn-row">
              <el-button type="primary" :icon="VideoPlay" :loading="running" @click="runTask" style="flex:2">开始执行</el-button>
              <el-button :icon="VideoPause" :disabled="!running" @click="ctrlTask('pause')">暂停</el-button>
              <el-button :icon="SwitchButton" :disabled="!running" @click="ctrlTask('stop')" type="danger">结束</el-button>
            </div>

            <el-divider />

            <h4><el-icon><Document /></el-icon> 执行日志</h4>
            <div class="log-panel" ref="logRef">
              <div v-for="(l, i) in logs" :key="i" :class="['log-line', l.type]">
                <span class="log-ts">[{{ l.time }}]</span>{{ l.msg }}
              </div>
              <div v-if="!logs.length" class="log-empty">等待执行...</div>
            </div>

            <h4 style="margin-top:12px"><el-icon><Picture /></el-icon> 截图证据</h4>
            <div class="ss-area">
              <el-image v-if="screenshot" :src="screenshot" :preview-src-list="[screenshot]" fit="contain" style="max-height:300px;width:100%" />
              <el-empty v-else description="执行完成后显示截图" :image-size="60" />
            </div>

            <h4 style="margin-top:12px"><el-icon><Notebook /></el-icon> 执行详情</h4>
            <el-input v-model="resultDetail" type="textarea" :rows="4" readonly />
          </el-card>

          <!-- 区块9: 执行历史 -->
          <el-card shadow="hover" class="block">
            <template #header>
              <div class="block-header">
                <el-icon><Clock /></el-icon> 执行历史
                <el-button type="danger" size="small" text @click="clearHistory" style="margin-left:auto">清空</el-button>
              </div>
            </template>
            <el-table :data="history" stripe size="small" max-height="300">
              <el-table-column prop="time" label="时间" width="160" />
              <el-table-column prop="keyword" label="关键词" width="120" />
              <el-table-column prop="title" label="视频标题" width="150" show-overflow-tooltip />
              <el-table-column prop="comment" label="评论" width="120" show-overflow-tooltip />
              <el-table-column label="状态" width="80">
                <template #default="{ row }">
                  <el-tag :type="row.ok ? 'success' : 'danger'" size="small">{{ row.ok ? '成功' : '失败' }}</el-tag>
                </template>
              </el-table-column>
              <el-table-column prop="dur" label="耗时" width="80" />
            </el-table>
            <el-empty v-if="!history.length" description="暂无记录" :image-size="50" />
          </el-card>
        </div>
      </div>
    </div>
  </div>
</template>

<script setup>
import { ref, reactive, onMounted } from 'vue'
import { useRouter } from 'vue-router'
import {
  Monitor, DataAnalysis, VideoCamera, User, Search, Timer,
  ChatDotRound, Filter, Pointer, CaretRight, Document, Picture,
  Notebook, Clock, ArrowDown, VideoPlay, VideoPause, SwitchButton
} from '@element-plus/icons-vue'
import { ElMessage, ElMessageBox } from 'element-plus'

const router = useRouter()

// ---- 侧边栏/区块折叠 ----
const blocks = reactive({ account: true, search: true, rhythm: true, comment: true, filter: true, action: true })
function toggleBlock(k) { blocks[k] = !blocks[k] }

// ---- 账号（从API获取，清空mock数据） ----
const accounts = ref([])
const selectedAccount = ref('')

// 登录状态badge颜色
function getLoginBadgeType(acc) {
  if (!acc.last_login_at) return 'danger'
  const days = Math.floor((Date.now() - new Date(acc.last_login_at).getTime()) / (1000 * 60 * 60 * 24))
  if (days >= 7) return 'danger'
  if (days >= 4) return 'warning'
  return 'success'
}

// 登录状态文字
function getLoginStatusText(acc) {
  if (!acc.last_login_at) return '未登录'
  const days = Math.floor((Date.now() - new Date(acc.last_login_at).getTime()) / (1000 * 60 * 60 * 24))
  if (days >= 7) return '已过期'
  if (days >= 4) return '即将过期'
  return '已登录'
}

// 从API获取账号列表
function loadAccounts() {
  fetch('/api/v1/accounts')
    .then(r => r.json())
    .then(data => {
      if (Array.isArray(data)) {
        accounts.value = data.map(a => ({
          id: a.id,
          name: a.display_name || a.username,
          last_login_at: a.last_login_at,
          loginStatusText: getLoginStatusText(a)
        }))
        // 优先选中URL参数中的账号，否则选第一个
        const urlAccountId = new URLSearchParams(window.location.search).get('account')
        if (urlAccountId && accounts.value.find(a => String(a.id) === String(urlAccountId))) {
          selectedAccount.value = Number(urlAccountId)
        } else if (accounts.value.length > 0 && !selectedAccount.value) {
          selectedAccount.value = accounts.value[0].id
        }
      }
    })
    .catch(() => {
      accounts.value = []
    })
}

// ---- 检测登录状态 ----
async function checkAccountLogin(accountId) {
  try {
    const resp = await fetch(`/api/v1/accounts/${accountId}/check`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' }
    })
    return await resp.json()
  } catch (e) {
    return { valid: false, reason: '检测登录状态失败' }
  }
}

// ---- 表单 ----
const form = reactive({
  keywords: '香港移民',
  time_range: 30,
  sort_by: 'general',
  video_count: 10,
  comment_interval: [1, 3],
  keyword_rotate_after: 10,
  rest_after: 5,
  rest_interval: [5, 10],
  comments: '',
  use_mention: false,
  mention_user: '',
  send_image: false,
  image_folder: '',
  use_province: false,
  filter_province: [],
  use_filter_time: false,
  filter_time: 0,
  use_filter_kw: false,
  filter_keywords_str: '',
  filter_count: 10,
  actions: { like: true, follow: true, favorite: true, view: true },
})

const provinces = ['北京', '上海', '广东', '浙江', '江苏', '四川', '湖北', '河南', '山东', '福建']

// ---- 执行状态 ----
const running = ref(false)
const statusType = ref('info')
const statusText = ref('就绪')
const logs = ref([])
const screenshot = ref('')
const resultDetail = ref('等待执行...')

// ---- 历史 ----
const HISTORY_KEY = 'sc_dy_comment_history'
const history = ref([])
function loadHistory() {
  try { history.value = JSON.parse(localStorage.getItem(HISTORY_KEY) || '[]') } catch { history.value = [] }
}
function pushHistory(r) {
  history.value.unshift(r)
  if (history.value.length > 200) history.value.length = 200
  localStorage.setItem(HISTORY_KEY, JSON.stringify(history.value))
}
function clearHistory() { history.value = []; localStorage.removeItem(HISTORY_KEY) }

// ---- 日志 ----
function addLog(msg, type = 'info') {
  const now = new Date().toLocaleTimeString('zh-CN', { hour12: false })
  logs.value.push({ time: now, msg, type })
}

// ---- 构建请求体 ----
function buildBody() {
  const kw = form.keywords.split('\n').map(s => s.trim()).filter(Boolean)
  const cmt = form.comments.split('\n').map(s => s.trim()).filter(Boolean)
  return {
    account_id: selectedAccount.value,
    keywords: kw,
    time_range: form.time_range,
    sort_by: form.sort_by,
    video_count: form.video_count,
    comment_interval: [...form.comment_interval],
    keyword_rotate_after: form.keyword_rotate_after,
    rest_after: form.rest_after,
    rest_interval: [...form.rest_interval],
    comments: cmt,
    mention_user: form.use_mention ? form.mention_user : '',
    send_image: form.send_image,
    image_folder: form.send_image ? form.image_folder : '',
    filter_province: form.use_province ? [...form.filter_province] : [],
    filter_time: form.use_filter_time ? form.filter_time : 0,
    filter_keywords: form.use_filter_kw ? form.filter_keywords_str.trim().split(/\s+/).filter(Boolean) : [],
    filter_count: form.filter_count,
    actions: { ...form.actions },
  }
}

// ---- 执行 ----
async function runTask() {
  const body = buildBody()
  if (!body.account_id) { ElMessage.warning('请先选择账号'); return }
  if (!body.keywords.length) { ElMessage.warning('请输入搜索关键词'); return }
  if (!body.comments.length) { ElMessage.warning('请输入评论内容'); return }

  // ====== 执行前检测登录状态 ======
  const loginCheck = await checkAccountLogin(body.account_id)

  if (!loginCheck.valid) {
    // 已过期 → 弹窗提示并跳转账号管理
    ElMessageBox.confirm(
      loginCheck.reason || '账号已过期，请到账号管理页面重新登录',
      '登录已过期',
      {
        confirmButtonText: '去登录',
        cancelButtonText: '取消',
        type: 'error',
        distinguishCancelAndClose: true
      }
    ).then(() => {
      router.push('/accounts')
    }).catch(() => {})
    return
  }

  if (loginCheck.warning) {
    // 即将过期 → 警告提示，继续执行
    ElMessage.warning(loginCheck.warning)
  }

  // ====== 登录状态正常，开始执行 ======
  running.value = true
  statusType.value = 'warning'
  statusText.value = '正在执行...'
  logs.value = []
  screenshot.value = ''
  resultDetail.value = '执行中...'

  addLog(`开始任务: ${body.keywords.length}个关键词, 评论${body.video_count}个视频, 账号=${body.account_id}`)
  const t0 = Date.now()

  try {
    const resp = await fetch('/api/douyin-comment', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(body),
    })
    const data = await resp.json()
    const dur = ((Date.now() - t0) / 1000).toFixed(1) + 's'

    if (data.success) {
      statusType.value = 'success'; statusText.value = '执行成功'
      addLog(`任务完成 (${data.duration || dur})`, 'ok')
      if (data.video_title) addLog(`视频: ${data.video_title}`)
      if (data.screenshot) { screenshot.value = data.screenshot; addLog('截图已加载', 'ok') }
      resultDetail.value = data.detail || JSON.stringify(data, null, 2)
    } else {
      statusType.value = 'danger'; statusText.value = '执行失败'
      addLog(`错误: ${data.error || '未知'}`, 'err')
      resultDetail.value = '错误: ' + (data.error || '未知')
    }
    pushHistory({
      time: new Date().toLocaleString('zh-CN'), keyword: body.keywords[0],
      title: data.video_title || '', comment: body.comments[0] || '',
      ok: data.success, dur: data.duration || dur,
    })
  } catch (e) {
    statusType.value = 'danger'; statusText.value = '请求失败'
    addLog(`网络错误: ${e.message}`, 'err')
    resultDetail.value = '异常: ' + e.message
    pushHistory({ time: new Date().toLocaleString('zh-CN'), keyword: body.keywords[0], ok: false, dur: '-' })
  } finally {
    running.value = false
  }
}

// ---- 控制 ----
async function ctrlTask(action) {
  if (action === 'stop') {
    running.value = false; statusType.value = 'info'; statusText.value = '已停止'
    addLog('手动停止', 'err'); return
  }
  try {
    await fetch('/api/douyin-comment/control', {
      method: 'POST', headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ action }),
    })
    addLog(`已发送: ${action}`)
  } catch (e) { addLog(`控制失败: ${e.message}`, 'err') }
}

onMounted(() => {
  loadHistory()
  loadAccounts()
})
</script>

<style scoped>
.douyin-comment-page { display: flex; min-height: 100vh; background: #f5f7fa; }

/* 侧边栏 */
.sidebar { width: 210px; background: #1a1a2e; flex-shrink: 0; }
.sidebar-brand { padding: 18px 20px; font-size: 17px; font-weight: 700; color: #fff; display: flex; align-items: center; gap: 8px; border-bottom: 1px solid #2a2a4a; }
.sidebar-brand span { color: #8b8bff; }
.sidebar :deep(.el-menu) { border-right: none; }

/* 主区域 */
.main-area { flex: 1; min-width: 0; }
.topbar { background: #fff; padding: 14px 28px; display: flex; justify-content: space-between; align-items: center; border-bottom: 1px solid #e5e7eb; }
.topbar h2 { font-size: 17px; display: flex; align-items: center; gap: 8px; }
.content-grid { display: grid; grid-template-columns: 1fr 1fr; gap: 16px; padding: 18px 22px; max-width: 1200px; }
@media (max-width: 960px) { .content-grid { grid-template-columns: 1fr; } }

/* 卡片 */
.block { margin-bottom: 16px; }
.block-header { display: flex; align-items: center; gap: 7px; cursor: pointer; font-size: 14px; font-weight: 600; }
.block-header .arrow { margin-left: auto; transition: transform 0.2s; }
.block-header .arrow.collapsed { transform: rotate(-90deg); }

/* range */
.range-row { display: flex; align-items: center; gap: 6px; }
.range-row span { color: #999; }

/* 账号 */
.acc-card { display: flex; align-items: center; gap: 10px; padding: 8px 12px; border: 1px solid #e5e7eb; border-radius: 6px; margin-bottom: 6px; cursor: pointer; transition: border 0.15s; }
.acc-card:hover { border-color: #8b8bff; }
.acc-card.selected { border-color: #8b8bff; background: #f0f0ff; }
.acc-name { font-size: 13px; font-weight: 500; }
.acc-meta { font-size: 11px; color: #888; margin-left: auto; }

/* 按钮行 */
.btn-row { display: flex; gap: 8px; }

/* 日志 */
.log-panel { background: #1a1a2e; color: #bbb; border-radius: 6px; padding: 10px; max-height: 220px; overflow-y: auto; font-family: 'Cascadia Code', monospace; font-size: 11px; line-height: 1.7; }
.log-line .log-ts { color: #555; margin-right: 5px; }
.log-line.info { color: #8b8bff; }
.log-line.ok { color: #4ade80; }
.log-line.err { color: #f87171; }
.log-empty { color: #555; }

/* 截图 */
.ss-area { min-height: 60px; display: flex; align-items: center; justify-content: center; }
</style>
