<template>
  <div class="update-bar">
    <span class="version-chip" :title="versionTooltip">v{{ build.version || '—' }}</span>

    <el-tooltip
      v-if="build.code_current === false"
      content="更新包已经装好，但当前服务进程还在运行旧代码。关闭服务窗口再双击 start_superclaw.bat 即可生效。"
      placement="bottom"
    >
      <span class="pill pill-stale">
        <el-icon><WarningFilled /></el-icon>
        进程仍运行 v{{ build.loaded_version || '?' }}
      </span>
    </el-tooltip>

    <button
      v-if="phase === 'idle' && update.update_available"
      class="pill pill-ready"
      type="button"
      @click="handleDownload"
    >
      <el-icon><Download /></el-icon>
      发现新版本 v{{ update.latest_version }}，立即更新
    </button>

    <button
      v-else-if="phase === 'downloading'"
      class="pill pill-busy"
      type="button"
      disabled
    >
      <el-icon class="spin"><Loading /></el-icon>
      下载中 {{ percentText }}
    </button>

    <button
      v-else-if="phase === 'ready'"
      class="pill pill-restart"
      type="button"
      @click="handleApply"
    >
      <el-icon><RefreshRight /></el-icon>
      v{{ pendingVersion }} 已就绪，重启并更新
    </button>

    <span v-else-if="phase === 'applying'" class="pill pill-busy">
      <el-icon class="spin"><Loading /></el-icon>
      正在重启，请稍候…
    </span>

    <button
      v-else-if="phase === 'failed'"
      class="pill pill-fail"
      type="button"
      @click="handleDownload"
      :title="status.error"
    >
      <el-icon><WarningFilled /></el-icon>
      更新失败，重试
    </button>

    <el-tooltip v-else-if="update.configured && !update.update_available" content="当前已是最新版本" placement="bottom">
      <span class="dot-ok"></span>
    </el-tooltip>

    <el-tooltip v-else-if="update.message" :content="update.message" placement="bottom">
      <span class="dot-warn"></span>
    </el-tooltip>

    <button
      v-if="update.update_available && update.notes && phase === 'idle'"
      class="notes-link"
      type="button"
      @click="notesVisible = true"
    >
      版本说明
    </button>

    <el-dialog v-model="notesVisible" title="版本说明" width="560px">
      <pre class="notes">{{ update.notes || '（本次发布未填写说明）' }}</pre>
      <template #footer>
        <el-button @click="notesVisible = false">关闭</el-button>
        <el-button type="primary" @click="notesVisible = false; handleDownload()">立即更新</el-button>
      </template>
    </el-dialog>
  </div>
</template>

<script setup>
import { computed, onMounted, onUnmounted, ref } from 'vue'
import { ElMessage } from 'element-plus'
import { Download, Loading, RefreshRight, WarningFilled } from '@element-plus/icons-vue'
import { useUserStore } from '@/stores/user'
import { applyUpdate, checkUpdate, downloadUpdate, getBuildInfo, getUpdateStatus } from '@/api/system'

const POLL_MS = 1500
const HEALTH_MS = 2000

const userStore = useUserStore()
const build = ref({})
const update = ref({ configured: false, update_available: false })
const status = ref({ phase: 'idle', progress: 0 })
const notesVisible = ref(false)
const pendingVersion = ref('')

let pollTimer = null
let healthTimer = null

const phase = computed(() => status.value?.phase || 'idle')
const percentText = computed(() => {
  const total = status.value?.total_bytes || 0
  const done = status.value?.downloaded_bytes || 0
  if (!total) return `${Math.round((status.value?.progress || 0) * 100)}%`
  return `${Math.round((done / total) * 100)}%（${formatSize(done)} / ${formatSize(total)}）`
})
const versionTooltip = computed(() => {
  const parts = []
  if (build.value.git_sha && build.value.git_sha !== 'unknown') parts.push('构建 ' + build.value.git_sha)
  if (build.value.built_at) parts.push('打包于 ' + build.value.built_at)
  if (build.value.execution_mode) parts.push('执行模式 ' + build.value.execution_mode)
  if (build.value.runtime_pid) parts.push('进程 ' + build.value.runtime_pid)
  if (build.value.started_at) parts.push('启动于 ' + build.value.started_at)
  if (build.value.loaded_version && build.value.loaded_version !== build.value.version) {
    parts.push('已加载代码 v' + build.value.loaded_version + '（落后于磁盘上的 v' + build.value.version + '）')
  }
  return parts.join(' · ') || 'SuperClaw 服务端'
})

function formatSize(bytes) {
  if (!bytes) return '0 B'
  const units = ['B', 'KB', 'MB', 'GB']
  let value = bytes
  let index = 0
  while (value >= 1024 && index < units.length - 1) {
    value /= 1024
    index += 1
  }
  return `${value.toFixed(index === 0 ? 0 : 1)} ${units[index]}`
}

async function loadBuild() {
  try {
    build.value = await getBuildInfo()
  } catch (error) {
    build.value = {}
  }
}

async function loadUpdate() {
  try {
    update.value = await checkUpdate()
  } catch (error) {
    update.value = { configured: false, update_available: false }
  }
}

async function refreshStatus() {
  try {
    status.value = await getUpdateStatus()
  } catch (error) {
    /* 服务重启期间会短暂 5xx，忽略即可 */
  }
  if (phase.value === 'ready' || phase.value === 'downloading') {
    if (phase.value === 'ready' && status.value.version) pendingVersion.value = status.value.version
    pollTimer = setTimeout(refreshStatus, POLL_MS)
  } else {
    pollTimer = null
  }
}

async function handleDownload() {
  notesVisible.value = false
  try {
    const result = await downloadUpdate({
      asset: update.value.asset || undefined,
      version: update.value.latest_version || undefined,
    })
    if (!result.ok) {
      ElMessage.warning(result.message || '无法开始下载')
      return
    }
    status.value = result.status || { phase: 'downloading', progress: 0 }
    pendingVersion.value = status.value.version || update.value.latest_version || ''
    if (!pollTimer) refreshStatus()
  } catch (error) {
    /* 拦截器已提示 */
  }
}

async function handleApply() {
  try {
    const result = await applyUpdate()
    ElMessage[result.ok ? 'success' : 'warning'](result.message)
    if (!result.ok) return
    status.value = { ...status.value, phase: 'applying' }
    waitForRestart()
  } catch (error) {
    /* 拦截器已提示 */
  }
}

function waitForRestart() {
  let attempts = 0
  const tick = async () => {
    attempts += 1
    try {
      const response = await fetch('/health', { cache: 'no-store' })
      if (response.ok) {
        const payload = await response.json()
        if (payload.status === 'ok') {
          ElMessage.success('更新完成，页面即将重新加载')
          setTimeout(() => window.location.reload(), 800)
          return
        }
      }
    } catch (error) {
      /* 服务还没起来 */
    }
    if (attempts > 150) {
      ElMessage.warning('等待服务重启超时，请手动刷新页面')
      return
    }
    healthTimer = setTimeout(tick, HEALTH_MS)
  }
  healthTimer = setTimeout(tick, HEALTH_MS)
}

onMounted(() => {
  if (userStore.userInfo.role !== 'admin') return
  loadBuild()
  loadUpdate()
})

onUnmounted(() => {
  if (pollTimer) clearTimeout(pollTimer)
  if (healthTimer) clearTimeout(healthTimer)
})
</script>

<style scoped>
.update-bar { display: flex; align-items: center; gap: 10px; }
.version-chip { padding: 2px 8px; border: 1px solid var(--border-color); border-radius: 999px; color: var(--text-secondary); font-size: 12px; font-family: var(--font-mono, monospace); }
.pill { display: inline-flex; align-items: center; gap: 6px; padding: 5px 12px; border-radius: 999px; font-size: 13px; cursor: pointer; border: 1px solid transparent; }
.pill:disabled { cursor: default; }
.pill-ready { background: rgba(249, 226, 175, 0.14); border-color: #f9e2af; color: #f9e2af; }
.pill-restart { background: rgba(166, 227, 161, 0.16); border-color: #a6e3a1; color: #a6e3a1; }
.pill-busy { background: rgba(137, 180, 250, 0.14); border-color: #89b4fa; color: #89b4fa; }
.pill-fail { background: rgba(243, 139, 168, 0.14); border-color: #f38ba8; color: #f38ba8; }
.pill-stale { background: rgba(249, 226, 175, 0.14); border: 1px dashed #f9e2af; color: #f9e2af; cursor: default; }
.dot-ok, .dot-warn { width: 8px; height: 8px; border-radius: 50%; display: inline-block; }
.dot-ok { background: #a6e3a1; }
.dot-warn { background: #f9e2af; }
.notes-link { padding: 0; border: 0; background: transparent; color: var(--text-secondary); font-size: 12px; text-decoration: underline; cursor: pointer; }
.notes-link:hover { color: var(--highlight); }
.spin { animation: spin 1s linear infinite; }
@keyframes spin { to { transform: rotate(360deg); } }
.notes { white-space: pre-wrap; word-break: break-word; margin: 0; font-size: 13px; line-height: 1.7; color: var(--text-primary); font-family: var(--font-sans, inherit); }
</style>
