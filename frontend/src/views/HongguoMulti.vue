<template>
  <div class="hongguo-multi">
    <div class="page-header">
      <div>
        <h3>红果多开</h3>
        <p>检测当前开启的 MuMu 实例和红果账号，按实例批量创建并同时执行任务。</p>
      </div>
      <div class="header-actions">
        <el-button :loading="loadingDevices" @click="detectDevices">
          <el-icon><Connection /></el-icon>
          检测实例/登录
        </el-button>
        <el-button :loading="loadingRuns" @click="loadRuns">
          <el-icon><Refresh /></el-icon>
          刷新批次
        </el-button>
      </div>
    </div>

    <div class="summary-grid">
      <div class="summary-item">
        <span class="summary-label">在线实例</span>
        <strong>{{ deviceSummary.online }}</strong>
      </div>
      <div class="summary-item">
        <span class="summary-label">已登录</span>
        <strong>{{ deviceSummary.loggedIn }}</strong>
      </div>
      <div class="summary-item">
        <span class="summary-label">已选实例</span>
        <strong>{{ selectedDevices.length }}</strong>
      </div>
      <div class="summary-item">
        <span class="summary-label">当前批次</span>
        <strong>{{ activeRun?.run_id || '-' }}</strong>
      </div>
    </div>

    <div class="workbench">
      <el-card class="device-panel">
        <template #header>
          <div class="card-header">
            <span>实例与账号</span>
            <el-tag type="info">{{ devices.length }} 台</el-tag>
          </div>
        </template>
        <el-table
          ref="deviceTableRef"
          :data="devices"
          v-loading="loadingDevices"
          row-key="addr"
          height="360"
          @selection-change="selectedDevices = $event"
        >
          <el-table-column type="selection" width="44" :selectable="isDeviceSelectable" />
          <el-table-column label="实例" min-width="220" show-overflow-tooltip>
            <template #default="{ row }">
              <div class="device-title">{{ row.label || row.addr }}</div>
              <div class="device-sub">{{ row.worker_name ? row.worker_name + ' / ' : '' }}{{ row.addr }}</div>
            </template>
          </el-table-column>
          <el-table-column label="登录" width="100">
            <template #default="{ row }">
              <el-tag :type="loginTagType(row)">
                {{ loginTagText(row) }}
              </el-tag>
            </template>
          </el-table-column>
          <el-table-column label="账号" min-width="160" show-overflow-tooltip>
            <template #default="{ row }">{{ accountText(row) }}</template>
          </el-table-column>
          <el-table-column label="前台" min-width="150" show-overflow-tooltip>
            <template #default="{ row }">{{ row.device?.current_package || '-' }}</template>
          </el-table-column>
          <el-table-column label="ADB端口" min-width="130" show-overflow-tooltip>
            <template #default="{ row }">{{ adbPortText(row) }}</template>
          </el-table-column>
        </el-table>
      </el-card>

      <el-card class="rule-panel">
        <template #header>
          <div class="card-header">
            <span>执行规则</span>
            <el-tag>{{ form.playback_speed }}</el-tag>
          </div>
        </template>
        <el-form :model="form" label-width="112px">
          <el-form-item label="搜索剧名" required>
            <div class="drama-picker">
              <el-select
                v-model="selectedDramas"
                multiple
                filterable
                allow-create
                default-first-option
                collapse-tags
                collapse-tags-tooltip
                :max-collapse-tags="8"
                :reserve-keyword="false"
                placeholder="从剧单里勾选，或直接敲一个新剧名回车"
                style="width: 100%"
              >
                <el-option
                  v-for="item in playlistItems"
                  :key="item.id"
                  :label="item.drama_name"
                  :value="item.drama_name"
                >
                  <span class="drama-option">
                    <span>{{ item.drama_name }}</span>
                    <span class="drama-option-meta">跑过 {{ item.run_count || 0 }} 次</span>
                  </span>
                </el-option>
              </el-select>
              <div class="drama-toolbar">
                <el-button size="small" :disabled="!playlistItems.length" @click="selectAllDramas">
                  全选剧单
                </el-button>
                <el-button size="small" :disabled="!playlistEnabledCount" @click="selectEnabledDramas">
                  只选启用的（{{ playlistEnabledCount }}）
                </el-button>
                <el-button size="small" :disabled="!selectedDramas.length" @click="clearDramaSelection">
                  清空已选
                </el-button>
                <el-button size="small" :loading="loadingPlaylist" @click="loadPlaylist">刷新剧单</el-button>
                <el-button size="small" :loading="importingHistory" @click="importHistoryDramas">
                  导入历史剧名
                </el-button>
                <el-button
                  size="small"
                  type="primary"
                  plain
                  :disabled="!dramasOutsidePlaylist.length"
                  :loading="addingPlaylist"
                  @click="saveSelectionToPlaylist"
                >
                  把 {{ dramasOutsidePlaylist.length }} 个新剧名存进剧单
                </el-button>
              </div>
              <div class="drama-bulk">
                <el-input
                  v-model="bulkDramaText"
                  type="textarea"
                  :rows="2"
                  placeholder="自定义 / 批量粘贴：一行一部，也可以用逗号隔开"
                />
                <el-button size="small" :disabled="!bulkDramaNames.length" @click="mergeBulkDramas">
                  加入已选（{{ bulkDramaNames.length }}）
                </el-button>
              </div>
              <span class="field-hint">
                已选 {{ dramaNames.length }} 部 · 剧单共 {{ playlistItems.length }} 部（启用 {{ playlistEnabledCount }} 部）<template v-if="dramaNames.length > 1">；选「排队执行」后由服务端自动一部接一部跑</template>
                <template v-if="playlistError">
                  ；<span class="drama-error">剧单没读出来（{{ playlistError }}）—— 点「刷新剧单」重试</span>
                </template>
              </span>
            </div>
          </el-form-item>
          <el-form-item label="执行方式">
            <el-radio-group v-model="executionMode">
              <el-radio value="single">单批次</el-radio>
              <el-radio value="queue">排队执行</el-radio>
            </el-radio-group>
            <span class="field-hint">排队执行不用守着点启动，第一部跑完自动开下一部</span>
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
          <el-form-item label="随机点赞">
            <el-input-number v-model="form.random_like_count" :min="0" />
            <span class="field-hint">次</span>
          </el-form-item>
          <el-form-item label="短剧收藏">
            <el-input-number v-model="form.random_favorite_count" :min="0" :max="1" />
            <span class="field-hint">0/1</span>
          </el-form-item>
          <el-form-item label="内容来源">
            <el-radio-group v-model="form.content_source">
              <el-radio value="ai">AI 生成</el-radio>
              <el-radio value="template">模板抽取</el-radio>
              <el-radio value="mixed">混合</el-radio>
            </el-radio-group>
          </el-form-item>
          <el-form-item label="刷剧倍速">
            <el-select v-model="form.playback_speed" style="width: 160px">
              <el-option v-for="item in playbackSpeedOptions" :key="item.value" :label="item.label" :value="item.value" />
            </el-select>
          </el-form-item>
          <el-form-item v-if="form.content_source !== 'ai'" label="模板库">
            <el-select
              v-model="selectedTemplateIds"
              multiple
              filterable
              collapse-tags
              :loading="loadingTemplates"
              placeholder="选择已保存的评论模板"
              style="width: 100%"
            >
              <el-option
                v-for="item in savedTemplates"
                :key="item.id"
                :label="templateOptionLabel(item)"
                :value="item.id"
              />
            </el-select>
            <el-button link type="primary" @click="router.push('/hongguo/templates')">管理模板</el-button>
          </el-form-item>
          <el-form-item v-if="form.content_source !== 'ai'" label="临时模板">
            <el-input v-model="templateText" type="textarea" :rows="4" placeholder="每行一条评论模板" />
          </el-form-item>
          <el-form-item>
            <el-button
              type="primary"
              :loading="creating"
              @click="executionMode === 'queue' ? submitQueue() : createRun()"
            >
              <el-icon><Plus /></el-icon>
              {{ executionMode === 'queue' ? '加入队列并开跑' : '创建批次' }}
            </el-button>
            <template v-if="executionMode === 'single'">
              <el-button type="success" :disabled="!activeRun" :loading="starting" @click="startRun">
                <el-icon><VideoPlay /></el-icon>
                启动批次
              </el-button>
              <el-button type="danger" :disabled="!activeRun" :loading="stopping" @click="stopRun">
                停止批次
              </el-button>
            </template>
          </el-form-item>
        </el-form>
      </el-card>
    </div>

    <el-card class="queue-panel">
      <template #header>
        <div class="card-header">
          <span>队列进度</span>
          <div class="run-actions">
            <el-tag v-if="queueActive.queue_id" type="primary" effect="plain" size="small">
              {{ queueActive.queue_id }}
            </el-tag>
            <el-tag v-else type="info" effect="plain" size="small">当前没有队列</el-tag>
            <el-button size="small" :loading="loadingQueue" @click="loadQueueState()">刷新</el-button>
            <el-button size="small" :loading="ticking" @click="runQueueTick">立即推进一次</el-button>
            <el-button
              size="small"
              type="danger"
              plain
              :disabled="!queuePendingCount"
              :loading="cancellingQueue"
              @click="cancelQueuePending"
            >
              取消待跑项
            </el-button>
          </div>
        </div>
      </template>
      <div class="run-summary">
        <el-tag>第 {{ queueSummary.current_seq || 0 }} / 共 {{ queueSummary.total }} 部</el-tag>
        <el-tag v-if="queueSummary.current_drama" type="primary">正在跑《{{ queueSummary.current_drama }}》</el-tag>
        <el-tag type="info">排队中 {{ queuePendingCount }}</el-tag>
        <el-tag type="success">完成 {{ queueDoneCount }}</el-tag>
        <el-tag type="danger">失败 {{ queueFailedCount }}</el-tag>
        <el-tag v-if="!dispatcherEnabled" type="warning">后台调度已关闭</el-tag>
      </div>
      <el-table :data="queueItems" v-loading="loadingQueue" style="width: 100%">
        <el-table-column prop="seq" label="#" width="56" />
        <el-table-column prop="drama_name" label="短剧" min-width="180" show-overflow-tooltip />
        <el-table-column label="状态" width="100">
          <template #default="{ row }">
            <el-tag :type="queueStatusType(row.status)">{{ queueStatusText(row.status) }}</el-tag>
          </template>
        </el-table-column>
        <el-table-column prop="device_count" label="实例" width="80" />
        <el-table-column prop="attempt" label="尝试" width="80" />
        <el-table-column label="批次" min-width="210" show-overflow-tooltip>
          <template #default="{ row }">
            <el-link v-if="row.multi_run_id" type="primary" @click="selectRun(row.multi_run_id)">
              {{ row.multi_run_id }}
            </el-link>
            <span v-else>-</span>
          </template>
        </el-table-column>
        <el-table-column label="开始" width="170">
          <template #default="{ row }">{{ formatTime(row.started_at) }}</template>
        </el-table-column>
        <el-table-column prop="error_message" label="备注" min-width="200" show-overflow-tooltip />
      </el-table>
    </el-card>

    <el-card class="playlist-panel">
      <template #header>
        <div class="card-header">
          <span>剧单与每日定时</span>
          <div class="run-actions">
            <el-tag type="info">共 {{ playlistItems.length }} 部</el-tag>
            <el-tag type="success">启用 {{ playlistEnabledCount }} 部</el-tag>
            <el-button size="small" :loading="loadingPlaylist" @click="loadPlaylist">刷新剧单</el-button>
          </div>
        </div>
      </template>
      <el-form label-width="112px">
        <el-form-item label="每天自动跑">
          <el-switch v-model="dailyConfig.daily_enabled" @change="markDailyDirty" />
          <el-time-select
            v-model="dailyConfig.daily_time"
            class="daily-time"
            start="00:00"
            step="00:30"
            end="23:30"
            placeholder="开始时间"
            @change="markDailyDirty"
          />
          <el-radio-group v-model="dailyConfig.daily_mode" @change="markDailyDirty">
            <el-radio value="all_random">剧单全部随机跑一遍</el-radio>
            <el-radio value="random_one">只随机跑一部</el-radio>
          </el-radio-group>
        </el-form-item>
        <el-form-item>
          <el-button type="primary" :loading="savingDaily" @click="saveDailyConfig">保存定时设置</el-button>
          <span class="field-hint">
            到点后服务端按剧单自动入队；设备取当前勾选的实例（没勾选就沿用上次保存的）
          </span>
        </el-form-item>
      </el-form>
      <el-table :data="playlistItems" v-loading="loadingPlaylist" style="width: 100%">
        <el-table-column prop="sort_order" label="#" width="56" />
        <el-table-column prop="drama_name" label="短剧" min-width="200" show-overflow-tooltip />
        <el-table-column label="参与每日" width="110">
          <template #default="{ row }">
            <el-switch v-model="row.enabled" @change="togglePlaylistEntry(row)" />
          </template>
        </el-table-column>
        <el-table-column prop="run_count" label="跑过" width="80" />
        <el-table-column label="最近一次" width="170">
          <template #default="{ row }">{{ formatTime(row.last_run_at) }}</template>
        </el-table-column>
        <el-table-column label="操作" width="170">
          <template #default="{ row }">
            <el-button size="small" @click="renamePlaylistEntry(row)">改名</el-button>
            <el-button size="small" type="danger" plain @click="removePlaylistEntry(row)">删除</el-button>
          </template>
        </el-table-column>
        <template #empty>
          <div class="playlist-empty">
            剧单是空的：在上面的「搜索剧名」里一行写一部短剧，然后点「存进剧单」。
          </div>
        </template>
      </el-table>
    </el-card>

    <el-card class="run-panel">
      <template #header>
        <div class="card-header">
          <span>实例执行统计</span>
          <el-tag v-if="pollingActive" type="primary" effect="plain" size="small">自动刷新中</el-tag>
          <div class="run-actions">
            <el-tooltip
              content="打开时这张卡自动跟随队列正在跑的那一批；手动挑过批次会锁定，不再被抢走"
              placement="top"
            >
              <el-switch
                v-model="followQueue"
                size="small"
                active-text="跟随队列"
                inactive-text="已锁定"
                @change="onFollowQueueChange"
              />
            </el-tooltip>
            <el-select v-model="activeRunId" placeholder="选择批次" filterable clearable style="width: 280px" @change="onPickRun">
              <el-option v-for="run in runs" :key="run.run_id" :label="runLabel(run)" :value="run.run_id" />
            </el-select>
            <el-button :disabled="!activeRun" @click="reuseRuleFromActiveRun">复用规则</el-button>
            <el-button :disabled="!activeRun" :loading="rebuilding" type="primary" @click="rebuildRunFromActiveRun">按此批次重建</el-button>
            <el-button :disabled="!activeRunId" :loading="loadingRunDetail" @click="loadRunDetail(activeRunId)">刷新统计</el-button>
          </div>
        </div>
      </template>
      <div v-if="activeRun" class="run-summary">
        <el-tag>任务 {{ activeRun.task_count }}</el-tag>
        <el-tag type="primary">运行 {{ activeRun.running_count }}</el-tag>
        <el-tag type="success">完成 {{ activeRun.completed_count }}</el-tag>
        <el-tag type="danger">失败 {{ activeRun.failed_count }}</el-tag>
        <el-tag type="info">已发 {{ activeRun.comments_sent }}</el-tag>
        <el-tag type="success">已验证 {{ activeRun.comments_verified }}</el-tag>
        <el-tag type="primary">点赞 {{ activeRun.likes_completed || 0 }}</el-tag>
        <el-tag type="warning">收藏 {{ activeRun.favorites_completed || 0 }}</el-tag>
      </div>
      <el-table :data="activeRun?.tasks || []" v-loading="loadingRunDetail" style="width: 100%">
        <el-table-column prop="id" label="任务" width="80" />
        <el-table-column label="实例" min-width="230" show-overflow-tooltip>
          <template #default="{ row }">
            <div class="device-title">{{ row.device_label || row.device_addr || '-' }}</div>
            <div class="device-sub">{{ row.worker_id ? row.worker_id + ' / ' : '' }}{{ row.device_addr || '-' }}</div>
          </template>
        </el-table-column>
        <el-table-column prop="drama_name" label="短剧" min-width="150" show-overflow-tooltip />
        <el-table-column label="状态" width="110">
          <template #default="{ row }">
            <el-tag :type="statusType(row.status)">{{ statusText(row.status) }}</el-tag>
          </template>
        </el-table-column>
        <el-table-column label="当前集" width="90">
          <template #default="{ row }">{{ row.current_episode || 0 }}</template>
        </el-table-column>
        <el-table-column label="总集数" width="90">
          <template #default="{ row }">{{ row.total_episodes || '-' }}</template>
        </el-table-column>
        <el-table-column label="计划评论" min-width="130" show-overflow-tooltip>
          <template #default="{ row }">{{ plannedCommentText(row) }}</template>
        </el-table-column>
        <el-table-column label="评论" width="120">
          <template #default="{ row }">{{ row.comments_sent || 0 }} / {{ row.comments_verified || 0 }}</template>
        </el-table-column>
        <el-table-column label="互动" width="130">
          <template #default="{ row }">赞 {{ row.likes_completed || 0 }} / 藏 {{ row.favorites_completed || 0 }}</template>
        </el-table-column>
        <el-table-column label="完成截图" width="100">
          <template #default="{ row }">
            <el-link v-if="row.completion_screenshot_url" :href="row.completion_screenshot_url" target="_blank" type="primary">查看</el-link>
            <span v-else>-</span>
          </template>
        </el-table-column>
        <el-table-column label="最近过程" min-width="220" show-overflow-tooltip>
          <template #default="{ row }">{{ latestLogText(row.id) }}</template>
        </el-table-column>
        <el-table-column prop="error_message" label="错误" min-width="180" show-overflow-tooltip />
        <el-table-column label="操作" width="150">
          <template #default="{ row }">
            <el-button size="small" :loading="loadingLogs && selectedLogTaskId === row.id" @click="loadTaskLogs(row.id)">日志</el-button>
            <el-button size="small" @click="router.push('/hongguo/task/' + row.id)">查看</el-button>
          </template>
        </el-table-column>
      </el-table>
      <div v-if="selectedLogTaskId" class="process-panel">
        <div class="process-header">
          <strong>任务 {{ selectedLogTaskId }} 执行过程</strong>
          <el-button text @click="selectedLogTaskId = null">收起</el-button>
        </div>
        <el-timeline>
          <el-timeline-item
            v-for="item in taskLogs[selectedLogTaskId] || []"
            :key="item.id"
            :type="logType(item.level)"
            :timestamp="formatTime(item.created_at)"
          >
            <span class="log-level">{{ item.level }}</span>
            <span>{{ item.message }}</span>
          </el-timeline-item>
        </el-timeline>
      </div>
    </el-card>
  </div>
</template>

<script setup>
import { computed, nextTick, onBeforeUnmount, onMounted, reactive, ref } from 'vue'
import { useRouter } from 'vue-router'
import { Connection, Plus, Refresh, VideoPlay } from '@element-plus/icons-vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import {
  addPlaylistNames,
  cancelQueue,
  createMultiTasks,
  createQueue,
  deletePlaylistEntry,
  getMultiDevices,
  getMultiRun,
  getMultiRuns,
  getLogs,
  getPlaylist,
  getQueueState,
  getTemplates,
  importPlaylistHistory,
  patchPlaylistEntry,
  startMultiRun,
  stopMultiRun,
  tickQueue,
  updateQueueConfig,
} from '../api/hongguo'
import {
  normalizeTemplateList,
  partitionTemplateContents,
  resolveTemplateContents,
  templateOptionLabel,
} from '../utils/hongguoTemplates'

const router = useRouter()
const deviceTableRef = ref(null)
const devices = ref([])
const selectedDevices = ref([])
const runs = ref([])
const activeRunId = ref('')
// 统计卡默认跟随队列当前批次。队列是服务端在推进的，一部短剧跑完就自动起下一部
// （每一部都是一个新批次），所以不跟随的话这张卡会一直停在上一次手选的批次上。
// 用户一旦手动挑过批次就锁定，免得轮询把正在看的历史批次抢走。
const followQueue = ref(true)
const activeRun = ref(null)
const loadingDevices = ref(false)
const loadingRuns = ref(false)
const loadingRunDetail = ref(false)
const creating = ref(false)
const starting = ref(false)
const stopping = ref(false)
const rebuilding = ref(false)
const loadingLogs = ref(false)
const templateText = ref('')
const savedTemplates = ref([])
const selectedTemplateIds = ref([])
const loadingTemplates = ref(false)
const selectedLogTaskId = ref(null)
const taskLogs = ref({})
const pollingActive = ref(false)
let pollTimer = null
let pollInFlight = false
let pollingSuspended = false

const form = reactive({
  drama_name: '',
  comment_mode: 'specified',
  start_episode: 1,
  episode_interval: 2,
  comment_interval_sec: 30,
  random_comment_count: 10,
  random_min_interval: 20,
  random_max_interval: 60,
  random_like_count: 5,
  random_favorite_count: 1,
  content_source: 'ai',
  playback_speed: '1.0x',
  templates: [],
})

// --------------------------------------------------------------- queue & 剧单
// The picker is the single source of drama names: its options are the saved
// 剧单, `allow-create` covers one-off names, and the bulk box covers pasting a
// whole list at once. All three collapse into `selectedDramas`.
const selectedDramas = ref([])
const bulkDramaText = ref('')
const executionMode = ref('single')
const queueActive = ref(emptyActive())
const queueConfig = ref({ daily_enabled: false, daily_time: '09:00', daily_mode: 'all_random' })
const dispatcherEnabled = ref(true)
const loadingQueue = ref(false)
const ticking = ref(false)
const cancellingQueue = ref(false)
const playlistItems = ref([])
const loadingPlaylist = ref(false)
const playlistError = ref('')
const addingPlaylist = ref(false)
const importingHistory = ref(false)
const savingDaily = ref(false)
const dailyConfig = reactive({ daily_enabled: false, daily_time: '09:00', daily_mode: 'all_random' })
// The settings card re-reads the server every 8s while a queue is live, so a
// naive sync would fight the operator's half-finished edit.
let dailyDirty = false
let queueTimer = null
let queueInFlight = false

function emptyActive() {
  return {
    queue_id: null,
    items: [],
    summary: { total: 0, finished: 0, counts: {}, current_seq: null, current_drama: null },
  }
}

// Accepts a raw string or an array of strings, splits on newlines and both
// comma variants, then de-duplicates while keeping the operator's own order.
function normalizeNameList(source) {
  const seen = new Set()
  const names = []
  const rows = Array.isArray(source) ? source : [source]
  rows.forEach((row) => {
    String(row || '')
      .replace(/\r/g, '\n')
      .replace(/，/g, ',')
      .split(/[\n,]/)
      .forEach((token) => {
        const name = token.trim()
        if (!name || seen.has(name)) return
        seen.add(name)
        names.push(name)
      })
  })
  return names
}

const dramaNames = computed(() => normalizeNameList(selectedDramas.value))
const bulkDramaNames = computed(() => normalizeNameList([bulkDramaText.value]))
const playlistNameSet = computed(() => new Set(playlistItems.value.map((item) => item.drama_name)))
const dramasOutsidePlaylist = computed(() =>
  dramaNames.value.filter((name) => !playlistNameSet.value.has(name)),
)
const queueSummary = computed(() => queueActive.value.summary || emptyActive().summary)
const queueItems = computed(() => queueActive.value.items || [])
const queuePendingCount = computed(() => Number((queueSummary.value.counts || {}).pending || 0))
const queueDoneCount = computed(() => Number((queueSummary.value.counts || {}).done || 0))
const queueFailedCount = computed(() => Number((queueSummary.value.counts || {}).failed || 0))
const playlistEnabledCount = computed(() => playlistItems.value.filter((item) => item.enabled).length)
const QUEUE_STATUS_TEXT = {
  pending: '排队中',
  running: '执行中',
  done: '已完成',
  failed: '失败',
  skipped: '已跳过',
  cancelled: '已取消',
}
const QUEUE_STATUS_TYPE = {
  pending: 'info',
  running: 'primary',
  done: 'success',
  failed: 'danger',
  skipped: 'warning',
  cancelled: 'info',
}

function queueStatusText(status) {
  return QUEUE_STATUS_TEXT[status] || status || '-'
}

function queueStatusType(status) {
  return QUEUE_STATUS_TYPE[status] || 'info'
}

const playbackSpeedOptions = [
  { label: '0.75x', value: '0.75x' },
  { label: '1.0x', value: '1.0x' },
  { label: '1.25x', value: '1.25x' },
  { label: '1.5x', value: '1.5x' },
  { label: '2.0x', value: '2.0x' },
  { label: '3.0x', value: '3.0x' },
]

const deviceSummary = computed(() => ({
  online: devices.value.filter((item) => item.online).length,
  loggedIn: devices.value.filter((item) => item.logged_in).length,
}))

// -------------------------------------------------------------- queue actions

function currentRule() {
  return {
    ...form,
    templates: resolveTemplateContents(savedTemplates.value, selectedTemplateIds.value, templateText.value),
    template_ids: selectedTemplateIds.value,
  }
}

function selectedDevicePayload() {
  return selectedDevices.value.map((item) => ({
    addr: item.addr,
    label: item.label || item.addr,
    worker_id: item.worker_id || null,
  }))
}

// Shared by 单批次 and 排队执行 so the two paths cannot drift apart.
function ruleProblem() {
  if (!dramaNames.value.length) return '请输入短剧名称'
  if (!selectedDevices.value.length) return '请选择已登录实例'
  if (form.comment_mode === 'random' && form.random_min_interval > form.random_max_interval) {
    return '最大间隔必须大于等于最小间隔'
  }
  if (form.content_source === 'template' && !currentRule().templates.length) {
    return '请选择或输入至少一条评论模板'
  }
  return ''
}

function applyActive(payload) {
  if (payload && payload.active) {
    queueActive.value = payload.active
    // 入队/手动 tick 之后队列可能已经起了新的一部，统计卡跟着走。
    syncFollowedRun()
  }
}

async function loadQueueState(options = {}) {
  if (!options.silent) loadingQueue.value = true
  try {
    const result = await getQueueState(options.silent ? { silent: true } : {})
    queueActive.value = result.active || emptyActive()
    queueConfig.value = result.config || queueConfig.value
    dispatcherEnabled.value = result.dispatcher ? result.dispatcher.enabled !== false : true
    syncDailyForm()
    // 队列里正在跑的那一部就是统计卡该显示的批次。
    syncFollowedRun()
    if (queueActive.value.queue_id) startQueuePolling()
    else stopQueuePolling()
  } catch (error) {
    // Silent passes are the poll loop; the interceptor already spoke for the rest.
  } finally {
    if (!options.silent) loadingQueue.value = false
  }
}

function syncDailyForm() {
  if (dailyDirty) return
  dailyConfig.daily_enabled = Boolean(queueConfig.value.daily_enabled)
  dailyConfig.daily_time = queueConfig.value.daily_time || '09:00'
  dailyConfig.daily_mode = queueConfig.value.daily_mode || 'all_random'
}

function markDailyDirty() {
  dailyDirty = true
}

function normalizePlaylist(rows) {
  return (rows || []).map((row) => ({ ...row, enabled: Boolean(row.enabled) }))
}

// The dispatcher advances the queue server-side, so the page only mirrors it.
function startQueuePolling() {
  if (queueTimer) return
  queueTimer = window.setInterval(async () => {
    if (queueInFlight || document.visibilityState !== 'visible') return
    queueInFlight = true
    try {
      const result = await getQueueState({ silent: true })
      queueActive.value = result.active || emptyActive()
      syncDailyForm()
      // 服务端跑完一部会自动起下一部，这里把统计卡一起带过去。
      syncFollowedRun()
      if (!queueActive.value.queue_id) stopQueuePolling()
    } catch (error) {
      // The next interval retries; a blip must not spam the operator.
    } finally {
      queueInFlight = false
    }
  }, 8000)
}

function stopQueuePolling() {
  if (queueTimer) window.clearInterval(queueTimer)
  queueTimer = null
}

async function submitQueue() {
  const problem = ruleProblem()
  if (problem) {
    ElMessage.warning(problem)
    return
  }
  const names = dramaNames.value
  if (names.length > 1) {
    try {
      await ElMessageBox.confirm(
        `将按顺序排队执行 ${names.length} 部短剧：\n${names.join(' → ')}\n\n第一部跑完自动开下一部；中途可以取消还没开跑的部分。`,
        '加入队列',
        { type: 'warning', confirmButtonText: '开始排队', cancelButtonText: '取消' },
      )
    } catch (error) {
      return
    }
  }
  creating.value = true
  try {
    const result = await createQueue({
      names,
      devices: selectedDevicePayload(),
      template: currentRule(),
      remember_settings: true,
    })
    applyActive(result)
    ElMessage.success(`已入队 ${(result.enqueued || names).length} 部短剧，服务端会自动一部接一部跑`)
    startQueuePolling()
    await loadQueueState({ silent: true })
  } catch (error) {
    // 409 "already a queue running" is reported by the shared interceptor.
  } finally {
    creating.value = false
  }
}

async function runQueueTick() {
  ticking.value = true
  try {
    const result = await tickQueue()
    applyActive(result)
    const plan = result.plan || {}
    if (plan.start) {
      ElMessage.success(`已启动第 ${plan.start.seq}/${plan.start.total} 部《${plan.start.drama_name}》`)
    } else if (plan.daily_fired) {
      ElMessage.success(`每日定时已触发，入队 ${plan.daily_fired.names.length} 部短剧`)
    } else if (plan.waiting) {
      ElMessage.info('当前这一部还在跑，结束后会自动开下一部')
    } else if ((plan.notes || []).length) {
      ElMessage.warning(plan.notes.join('；'))
    } else {
      ElMessage.info('没有需要推进的队列')
    }
    await loadQueueState({ silent: true })
  } finally {
    ticking.value = false
  }
}

async function cancelQueuePending() {
  const pending = queuePendingCount.value
  if (!pending) {
    ElMessage.info('没有等待执行的短剧')
    return
  }
  try {
    await ElMessageBox.confirm(
      `取消队列里还没开跑的 ${pending} 部短剧？正在跑的那一部不受影响。`,
      '取消待跑项',
      { type: 'warning', confirmButtonText: '取消待跑', cancelButtonText: '保留' },
    )
  } catch (error) {
    return
  }
  cancellingQueue.value = true
  try {
    const result = await cancelQueue({ queue_id: queueActive.value.queue_id })
    applyActive(result)
    ElMessage.success(`已取消 ${result.cancelled || 0} 部待跑短剧`)
    await loadQueueState({ silent: true })
  } finally {
    cancellingQueue.value = false
  }
}

// ------------------------------------------------------------- 剧单/daily timer

async function loadPlaylist() {
  loadingPlaylist.value = true
  try {
    const result = await getPlaylist()
    playlistItems.value = normalizePlaylist(result.items)
    playlistError.value = ''
  } catch (error) {
    // The interceptor already toasted it, but the toast vanishes while the picker
    // keeps showing an empty list - which reads as "my saved dramas are gone".
    playlistError.value = error?.response?.data?.detail || '剧单读取失败'
  } finally {
    loadingPlaylist.value = false
  }
}

function selectAllDramas() {
  const names = normalizeNameList(playlistItems.value.map((item) => item.drama_name))
  if (!names.length) {
    ElMessage.warning('剧单还是空的：在下面的「自定义 / 批量粘贴」里写几部，再存进剧单')
    return
  }
  selectedDramas.value = names
  ElMessage.success(`已选中剧单全部 ${names.length} 部短剧`)
}

function selectEnabledDramas() {
  const names = normalizeNameList(
    playlistItems.value.filter((item) => item.enabled).map((item) => item.drama_name),
  )
  if (!names.length) {
    ElMessage.warning('剧单里没有启用中的短剧，先去下面把要跑的打开')
    return
  }
  selectedDramas.value = names
  ElMessage.success(`已选中 ${names.length} 部启用中的短剧`)
}

function clearDramaSelection() {
  selectedDramas.value = []
}

function mergeBulkDramas() {
  const names = bulkDramaNames.value
  if (!names.length) return
  selectedDramas.value = normalizeNameList([...selectedDramas.value, ...names])
  bulkDramaText.value = ''
  ElMessage.success(`已加入已选：${names.length} 部短剧`)
}

async function saveSelectionToPlaylist() {
  const names = dramasOutsidePlaylist.value
  if (!names.length) {
    ElMessage.info('当前选中的剧名都已经在剧单里了')
    return
  }
  addingPlaylist.value = true
  try {
    const result = await addPlaylistNames({ names })
    playlistItems.value = normalizePlaylist(result.items)
    ElMessage.success(`已存进剧单：${names.join('、')}`)
  } finally {
    addingPlaylist.value = false
  }
}

// Every batch run so far started with a hand-typed 剧名, so the names are already
// in the task table. Importing them beats making the operator retype the list.
async function importHistoryDramas() {
  try {
    await ElMessageBox.confirm(
      '把以前跑过的短剧名字收进剧单，已经在剧单里的不会被改动。',
      '导入历史剧名',
      { type: 'info', confirmButtonText: '开始导入', cancelButtonText: '取消' },
    )
  } catch (error) {
    return
  }
  importingHistory.value = true
  try {
    const result = await importPlaylistHistory()
    playlistItems.value = normalizePlaylist(result.items)
    const added = result.added || []
    if (added.length) {
      ElMessage.success(`已导入 ${added.length} 部短剧，剧单现在共 ${playlistItems.value.length} 部`)
    } else {
      ElMessage.info(`历史里扫到 ${result.scanned || 0} 部短剧，都已经在剧单里了`)
    }
  } finally {
    importingHistory.value = false
  }
}

async function togglePlaylistEntry(row) {
  const next = Boolean(row.enabled)
  try {
    const result = await patchPlaylistEntry(row.id, { enabled: next })
    playlistItems.value = normalizePlaylist(result.items)
    ElMessage.success(next ? `《${row.drama_name}》已加入每日剧单` : `《${row.drama_name}》已暂停`)
  } catch (error) {
    row.enabled = !next
  }
}

async function removePlaylistEntry(row) {
  try {
    await ElMessageBox.confirm(`把《${row.drama_name}》从剧单里删掉？`, '删除确认', {
      type: 'warning',
      confirmButtonText: '删除',
      cancelButtonText: '取消',
    })
  } catch (error) {
    return
  }
  const result = await deletePlaylistEntry(row.id)
  playlistItems.value = normalizePlaylist(result.items)
  ElMessage.success('已从剧单删除')
}

// A name that does not match what 红果 returns makes the on-device search fail
// quietly, so a typo must be fixable without deleting and re-adding the row.
async function renamePlaylistEntry(row) {
  let name
  try {
    const answer = await ElMessageBox.prompt('改成和红果里搜索到的一模一样的名字', '重命名短剧', {
      inputValue: row.drama_name,
      inputPattern: /\S/,
      inputErrorMessage: '名称不能为空',
      confirmButtonText: '保存',
      cancelButtonText: '取消',
    })
    name = String(answer.value || '').trim()
  } catch (error) {
    return
  }
  if (!name || name === row.drama_name) return
  const result = await patchPlaylistEntry(row.id, { drama_name: name })
  playlistItems.value = normalizePlaylist(result.items)
  // Keep whatever was already selected pointing at the new name.
  selectedDramas.value = selectedDramas.value.map((item) => (item === row.drama_name ? name : item))
  ElMessage.success(`已改名为《${name}》`)
}

async function saveDailyConfig() {
  const devices = selectedDevicePayload()
  savingDaily.value = true
  try {
    const payload = {
      daily_enabled: dailyConfig.daily_enabled,
      daily_time: dailyConfig.daily_time,
      daily_mode: dailyConfig.daily_mode,
      template: currentRule(),
    }
    // An empty selection means "this card does not own the device list", not
    // "clear it" - otherwise saving the timer before 检测实例 would wipe it.
    if (devices.length) payload.devices = devices
    const result = await updateQueueConfig(payload)
    queueConfig.value = result.config || queueConfig.value
    dailyDirty = false
    syncDailyForm()
    if (dailyConfig.daily_enabled && !playlistEnabledCount.value) {
      ElMessage.warning('定时已开启，但剧单里没有启用任何短剧，到期不会执行')
    } else if (dailyConfig.daily_enabled && !devices.length && !(queueConfig.value.devices || []).length) {
      ElMessage.warning('定时已开启，但还没选执行实例：请勾选上面的实例后再保存一次')
    } else if (dailyConfig.daily_enabled) {
      ElMessage.success(`已开启：每天 ${dailyConfig.daily_time} 随机跑一遍剧单`)
    } else {
      ElMessage.success('已关闭每日定时')
    }
  } finally {
    savingDaily.value = false
  }
}

async function loadTemplateLibrary() {
  loadingTemplates.value = true
  try {
    savedTemplates.value = normalizeTemplateList(await getTemplates())
  } finally {
    loadingTemplates.value = false
  }
}

function isDeviceSelectable(row) {
  return Boolean(row.online && row.logged_in && !row.leased_by_other)
}

function loginTagType(row) {
  if (row.leased_by_other) return 'info'
  if (row.logged_in) return 'success'
  if (row.status === 'adb_not_ready' || row.status === 'login_check_timeout') return 'danger'
  return 'warning'
}

function loginTagText(row) {
  if (row.leased_by_other) return '占用中'
  if (row.logged_in) return '已登录'
  if (row.status === 'adb_not_ready') return 'ADB未就绪'
  if (row.status === 'login_check_timeout') return '检测超时'
  if (row.online) return '未登录'
  return '未就绪'
}

function adbPortText(row) {
  const ports = row.mumu_instance?.configured_adb_ports || []
  if (ports.length) return ports.join(', ')
  const addr = row.addr || row.mumu_instance?.addr || ''
  const port = String(addr).split(':').pop()
  return port && port !== addr ? port : '-'
}

function accountText(row) {
  const account = row.account || {}
  if (!row.logged_in && !account.logged_in) {
    return row.message || account.message || '请先登录红果账号'
  }
  const parts = []
  if (account.hongguo_id) parts.push(`红果号 ${account.hongguo_id}`)
  return parts.join(' / ') || account.message || row.message || '已登录'
}

function describeEmptyDetection(result) {
  const lines = []
  const diagnostics = result.diagnostics || {}
  if (result.reason_text) lines.push(result.reason_text)
  if (result.database_error) lines.push(`后端错误：${result.database_error}`)
  if (diagnostics.adb_error) lines.push(`ADB：${diagnostics.adb_error}`)
  if (diagnostics.mumu_manager_error) lines.push(`MuMuManager：${diagnostics.mumu_manager_error}`)
  if (diagnostics.mumu_root_exists === false) {
    lines.push(`MuMu 安装目录不存在：${diagnostics.mumu_root}`)
  } else if (diagnostics.mumu_root && result.reason === 'mumu_not_found') {
    lines.push(`当前扫描目录：${diagnostics.mumu_root}`)
  }
  if (result.device_source) {
    lines.push(`数据来源：${result.device_source === 'remote_workers' ? '远程执行节点' : '本机 MuMu'}`)
  }
  if (!lines.length) {
    lines.push('未发现任何在线实例：请确认 MuMu 多开已启动、红果已登录，且当前实例为 embedded 模式。')
  }
  return lines.join('\n')
}

async function detectDevices() {
  const resumePolling = Boolean(pollTimer)
  pollingSuspended = true
  stopPolling()
  loadingDevices.value = true
  try {
    const result = await getMultiDevices()
    devices.value = result.devices || []
    selectedDevices.value = []
    await nextTick()
    devices.value.forEach((item) => {
      if (isDeviceSelectable(item)) deviceTableRef.value?.toggleRowSelection(item, true)
    })

    // The backend reports internal failures as HTTP 200 with success:false.
    // Reading only online_count turned those into a green "在线 0 台" toast,
    // which is exactly how a broken backend looked identical to "no emulator
    // running" - and hid the fact that nothing had been checked at all.
    if (result.success === false) {
      ElMessage.error(result.database_error || result.reason_text || '设备检测失败，请查看后端日志')
      return
    }

    const onlineCount = Number(result.online_count || 0)
    if (!onlineCount) {
      await ElMessageBox.alert(describeEmptyDetection(result), '未检测到在线实例', {
        type: 'warning',
        confirmButtonText: '知道了',
      })
    } else {
      ElMessage.success(`检测完成：在线 ${onlineCount} 台，已登录 ${result.logged_in_count || 0} 台`)
    }
    const ignoredDevices = result.ignored_devices || []
    if (ignoredDevices.length) {
      const lines = ignoredDevices.map((item) => `${item.label || item.addr}：${item.ignore_reason || '非 MuMu 实例，已忽略'}`)
      await ElMessageBox.alert(lines.join('\n'), '已忽略非 MuMu ADB 设备', {
        type: 'info',
        confirmButtonText: '知道了',
      })
    }
    const needLogin = devices.value.filter((item) => item.online && !item.logged_in)
    if (needLogin.length) {
      const lines = needLogin.map((item) => `${item.label || item.addr}：${item.message || item.account?.message || '请先登录红果账号'}`)
      await ElMessageBox.alert(lines.join('\n'), '以下实例需要登录', {
        type: 'warning',
        confirmButtonText: '知道了',
      })
    }
  } finally {
    loadingDevices.value = false
    pollingSuspended = false
    if (resumePolling) startPolling()
  }
}

async function createRun() {
  if (executionMode.value === 'single' && dramaNames.value.length > 1) {
    ElMessage.warning('单批次一次只跑一部短剧；想一次跑完多部，请把「执行方式」改成「排队执行」')
    return
  }
  const problem = ruleProblem()
  if (problem) {
    ElMessage.warning(problem)
    return
  }
  creating.value = true
  try {
    const payload = {
      ...form,
      drama_name: dramaNames.value[0],
      templates: currentRule().templates,
      template_ids: selectedTemplateIds.value,
      devices: selectedDevicePayload(),
    }
    const result = await createMultiTasks(payload)
    // 手动新建/重建出来的批次是用户主动发起的，锁定它，别被队列跟随抢走。
    followQueue.value = false
    activeRunId.value = result.run_id
    activeRun.value = { run_id: result.run_id, tasks: result.tasks || [] }
    ElMessage.success(`批次已创建：${result.run_id}`)
    await loadRuns()
    await loadRunDetail(result.run_id)
  } finally {
    creating.value = false
  }
}

async function startRun() {
  if (!activeRunId.value) return
  await ElMessageBox.confirm('确认同时启动当前批次的所有实例任务吗？', '启动确认', {
    type: 'warning',
    confirmButtonText: '启动',
    cancelButtonText: '取消',
  })
  starting.value = true
  startPolling()
  try {
    const result = await startMultiRun(activeRunId.value)
    activeRun.value = result
    if (result.success) {
      ElMessage.success(`已启动 ${result.started_count || 0} 个实例任务`)
    } else {
      ElMessage.warning(`部分启动失败，已启动 ${result.started_count || 0} 个`)
    }
    await refreshVisibleLogs()
  } catch (error) {
    const timedOut = error?.code === 'ECONNABORTED' || String(error?.message || '').includes('timeout')
    if (timedOut) {
      ElMessage.warning('启动请求仍在后台执行，已继续刷新批次状态和日志')
      await loadRuns()
      await loadRunDetail(activeRunId.value)
      startPolling()
      return
    }
    throw error
  } finally {
    starting.value = false
  }
}

async function stopRun() {
  if (!activeRunId.value) return
  await ElMessageBox.confirm('确认停止当前批次所有实例任务吗？', '停止确认', {
    type: 'warning',
    confirmButtonText: '停止',
    cancelButtonText: '取消',
  })
  stopping.value = true
  try {
    const result = await stopMultiRun(activeRunId.value)
    activeRun.value = result
    ElMessage.success('批次已停止')
  } finally {
    stopping.value = false
  }
}

async function loadRuns() {
  loadingRuns.value = true
  try {
    const result = await getMultiRuns()
    runs.value = result.runs || []
    if (!activeRunId.value && runs.value.length) {
      activeRunId.value = runs.value[0].run_id
      await loadRunDetail(activeRunId.value)
    }
  } finally {
    loadingRuns.value = false
  }
}

async function loadRunDetail(runId = activeRunId.value, options = {}) {
  if (!runId) {
    activeRun.value = null
    return
  }
  loadingRunDetail.value = true
  try {
    const requestConfig = options.silent ? { silent: true, timeout: 120000 } : {}
    activeRun.value = await getMultiRun(runId, requestConfig)
    activeRunId.value = runId
    await refreshVisibleLogs(options)
    // Opening the page, switching batch or clicking 刷新统计 all land here, so
    // this is the single place that decides whether the live loop should run.
    ensurePolling()
  } finally {
    loadingRunDetail.value = false
  }
}

// Jumping from a queue row straight to the batch it produced.
function selectRun(runId) {
  if (!runId) return
  // 从队列行点批次链接 = 用户主动指定看哪批，停掉自动跟随。
  followQueue.value = false
  activeRunId.value = runId
  loadRunDetail(runId)
}

// 队列里「正在跑」那一项的批次号，就是统计卡该显示的东西。
function currentQueueRunId() {
  const live = (queueItems.value || []).find(
    (item) => (item.status === 'running' || item.status === 'paused') && item.multi_run_id,
  )
  return live ? live.multi_run_id : ''
}

// 跟随开关打开时，把统计卡切到队列当前批次；队列没有在跑的批次就什么都不做，
// 保留当前画面（比如队列刚跑完，正好停在最后那一批）。
function syncFollowedRun() {
  if (!followQueue.value) return
  const runId = currentQueueRunId()
  if (!runId || runId === activeRunId.value) return
  // 跟随是后台行为，失败不打扰用户；下个轮询周期会再试。
  loadRunDetail(runId, { silent: true }).catch(() => {})
}

// 手动选批次就锁定；把开关拨回来则立刻重新跟随。
function onPickRun(runId) {
  followQueue.value = false
  loadRunDetail(runId)
}

function onFollowQueueChange(enabled) {
  if (enabled) syncFollowedRun()
}

function ruleFromTask(task) {
  return {
    drama_name: task?.drama_name || '',
    comment_mode: task?.comment_mode || 'specified',
    start_episode: task?.start_episode || 1,
    episode_interval: task?.episode_interval || 2,
    comment_interval_sec: task?.comment_interval_sec || 30,
    random_comment_count: task?.random_comment_count || 10,
    random_min_interval: task?.random_min_interval || 20,
    random_max_interval: task?.random_max_interval || 60,
    random_like_count: task?.random_like_count ?? 5,
    random_favorite_count: Math.min(task?.random_favorite_count ?? 1, 1),
    content_source: task?.content_source || 'ai',
    playback_speed: task?.playback_speed || '1.0x',
    templates: task?.templates || [],
  }
}

function reuseRuleFromActiveRun() {
  const task = activeRun.value?.tasks?.[0]
  if (!task) {
    ElMessage.warning('当前批次没有可复用的规则')
    return
  }
  Object.assign(form, ruleFromTask(task))
  // The picker is the single source of drama names now. Only fill it when it is
  // still empty - otherwise reusing the *rules* would silently replace the list
  // of dramas the operator is about to queue.
  if (!dramaNames.value.length && task.drama_name) selectedDramas.value = [task.drama_name]
  const partitioned = partitionTemplateContents(task.templates || [], savedTemplates.value)
  selectedTemplateIds.value = partitioned.selectedIds
  templateText.value = partitioned.manualText
  ElMessage.success('已复用当前批次规则')
}

async function rebuildRunFromActiveRun() {
  const tasks = activeRun.value?.tasks || []
  if (!tasks.length) {
    ElMessage.warning('当前批次没有可重建的任务')
    return
  }
  rebuilding.value = true
  try {
    const rule = ruleFromTask(tasks[0])
    const payload = {
      ...rule,
      template_ids: partitionTemplateContents(rule.templates, savedTemplates.value).selectedIds,
      devices: tasks
        .filter((item) => item.device_addr)
        .map((item) => ({
          addr: item.device_addr,
          label: item.device_label || item.device_addr,
          worker_id: item.worker_id || null,
        })),
    }
    if (!payload.devices.length) {
      ElMessage.warning('当前批次没有可复用的设备')
      return
    }
    const result = await createMultiTasks(payload)
    // 手动新建/重建出来的批次是用户主动发起的，锁定它，别被队列跟随抢走。
    followQueue.value = false
    activeRunId.value = result.run_id
    activeRun.value = { run_id: result.run_id, tasks: result.tasks || [] }
    ElMessage.success(`已按原规则重建批次：${result.run_id}`)
    await loadRuns()
    await loadRunDetail(result.run_id)
  } finally {
    rebuilding.value = false
  }
}

async function loadTaskLogs(taskId, options = {}) {
  if (!taskId) return
  selectedLogTaskId.value = taskId
  // Silent refreshes come from the poll loop: the panel is already on screen,
  // so flipping the button into its loading state every 5s is just noise.
  if (!options.silent) loadingLogs.value = true
  try {
    const requestConfig = options.silent ? { silent: true, timeout: 120000 } : {}
    const result = await getLogs(taskId, { limit: 80, current_run_only: true }, requestConfig)
    taskLogs.value = { ...taskLogs.value, [taskId]: Array.isArray(result) ? result : (result.value || []) }
  } finally {
    if (!options.silent) loadingLogs.value = false
  }
}

async function refreshVisibleLogs(options = {}) {
  const tasks = activeRun.value?.tasks || []
  const targets = tasks.slice(0, 6)
  await Promise.all(targets.map(async (task) => {
    try {
      const requestConfig = options.silent ? { silent: true, timeout: 120000 } : {}
      const result = await getLogs(task.id, { limit: 8, current_run_only: true }, requestConfig)
      taskLogs.value = { ...taskLogs.value, [task.id]: Array.isArray(result) ? result : (result.value || []) }
    } catch (error) {
      // Ignore per-task log refresh failures; the main run state is still useful.
    }
  }))
}

function runIsLive(run) {
  return Boolean(
    run && (run.tasks || []).some((item) => item.status === 'running' || item.status === 'paused'),
  )
}

function startPolling() {
  stopPolling()
  pollingActive.value = true
  pollTimer = window.setInterval(async () => {
    if (!activeRunId.value || pollInFlight) return
    pollInFlight = true
    try {
      await loadRunDetail(activeRunId.value, { silent: true })
      // Refresh the open 执行过程 panel as well. It used to keep showing the
      // snapshot taken when 日志 was clicked, so a live run looked frozen.
      if (selectedLogTaskId.value) {
        await loadTaskLogs(selectedLogTaskId.value, { silent: true })
      }
      if (!runIsLive(activeRun.value)) stopPolling()
    } catch (error) {
      // The next interval retries without interrupting the user's workflow.
    } finally {
      pollInFlight = false
    }
  }, 5000)
}

function stopPolling() {
  if (pollTimer) window.clearInterval(pollTimer)
  pollTimer = null
  pollingActive.value = false
}

// Polling used to be armed only by 开始执行 on this page, so a run started
// anywhere else — a script, another tab, another machine — sat on screen
// looking stuck and the process was invisible. Arm it whenever the selected
// run still has live tasks, no matter who started them.
function ensurePolling() {
  if (pollingSuspended) return
  if (runIsLive(activeRun.value)) {
    if (!pollTimer) startPolling()
    return
  }
  stopPolling()
}

function runLabel(run) {
  return `${run.run_id}｜${run.task_count}台｜运行${run.running_count}｜完成${run.completed_count}｜失败${run.failed_count}`
}

function statusType(status) {
  return {
    pending: 'info',
    waiting_login: 'warning',
    running: 'primary',
    paused: 'warning',
    completed: 'success',
    failed: 'danger',
    stopped: 'warning',
  }[status] || 'info'
}

function statusText(status) {
  return {
    pending: '待执行',
    waiting_login: '等待登录',
    running: '执行中',
    paused: '已暂停',
    completed: '已完成',
    failed: '失败',
    stopped: '已停止',
  }[status] || status || '-'
}

function plannedCommentText(row) {
  const plan = row.execution_plan || {}
  const episodes = Array.isArray(plan.comment_episodes) ? plan.comment_episodes : []
  if (episodes.length) {
    const preview = episodes.slice(0, 8).join(', ')
    return episodes.length > 8 ? `${preview} ... 共${episodes.length}集` : preview
  }
  if (row.comment_mode === 'random') return `随机 ${row.random_comment_count || 0} 次`
  return `从${row.start_episode || 1}起，每${row.episode_interval || 1}集`
}

function latestLogText(taskId) {
  const logs = taskLogs.value[taskId] || []
  return logs[0]?.message || '暂无日志'
}

function logType(level) {
  return {
    error: 'danger',
    warn: 'warning',
    info: 'primary',
  }[level] || 'info'
}

function formatTime(value) {
  if (!value) return '-'
  const date = new Date(value)
  return Number.isNaN(date.getTime()) ? value : date.toLocaleString('zh-CN')
}

onMounted(() => {
  loadRuns()
  loadTemplateLibrary()
  loadQueueState()
  loadPlaylist()
  document.addEventListener('visibilitychange', resyncVisibleRun)
  window.addEventListener('focus', resyncVisibleRun)
})

onBeforeUnmount(() => {
  document.removeEventListener('visibilitychange', resyncVisibleRun)
  window.removeEventListener('focus', resyncVisibleRun)
  stopPolling()
  stopQueuePolling()
})

// A backgrounded or frozen tab stops its own timers, so this page could sit on a
// stale snapshot for hours — the run may have finished already, or a task may
// have been restarted from the API. Re-sync whenever the page becomes visible or
// focused again, regardless of the batch's last known state, and let
// loadRunDetail() decide whether the 5s live loop should resume.
let lastResyncAt = 0
function resyncVisibleRun() {
  if (document.visibilityState !== 'visible') return
  const now = Date.now()
  if (now - lastResyncAt < 2000) return
  lastResyncAt = now
  if (activeRunId.value) loadRunDetail(activeRunId.value, { silent: true })
  loadQueueState({ silent: true })
}
</script>

<style scoped>
.page-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 16px;
  margin-bottom: 16px;
}
.page-header h3 {
  margin: 0;
  color: var(--text-primary);
  font-size: 18px;
}
.page-header p {
  margin: 6px 0 0;
  color: var(--text-secondary);
  font-size: 13px;
}
.header-actions,
.run-actions {
  display: flex;
  align-items: center;
  gap: 10px;
}
.summary-grid {
  display: grid;
  grid-template-columns: repeat(4, minmax(140px, 1fr));
  gap: 12px;
  margin-bottom: 16px;
}
.summary-item {
  min-height: 72px;
  padding: 14px 16px;
  border: 1px solid var(--border-color);
  border-radius: 8px;
  background: var(--bg-secondary);
}
.summary-label {
  display: block;
  margin-bottom: 8px;
  color: var(--text-secondary);
  font-size: 13px;
}
.summary-item strong {
  color: var(--text-primary);
  font-size: 20px;
}
.workbench {
  display: grid;
  grid-template-columns: minmax(0, 1.15fr) minmax(360px, 0.85fr);
  gap: 16px;
  margin-bottom: 16px;
}
.card-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
}
.device-title {
  color: var(--text-primary);
  font-weight: 600;
}
.device-sub {
  margin-top: 2px;
  color: var(--text-secondary);
  font-size: 12px;
}
.field-hint {
  margin-left: 8px;
  color: var(--text-secondary);
  font-size: 13px;
}
.drama-picker {
  width: 100%;
}
.drama-toolbar {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: 8px;
  margin-top: 8px;
}
.drama-bulk {
  display: flex;
  align-items: flex-start;
  gap: 8px;
  margin-top: 8px;
}
.drama-bulk .el-textarea {
  flex: 1;
}
.drama-option {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 16px;
}
.drama-option-meta {
  color: var(--text-secondary);
  font-size: 12px;
}
.drama-picker .field-hint {
  display: block;
  margin: 8px 0 0;
}
.drama-error {
  color: var(--el-color-danger);
}
.queue-panel,
.playlist-panel {
  margin-bottom: 16px;
}
.daily-time {
  width: 140px;
  margin: 0 12px;
}
.playlist-empty {
  padding: 18px 0;
  color: var(--text-secondary);
  font-size: 13px;
}
.run-panel {
  margin-bottom: 20px;
}
.run-summary {
  display: flex;
  flex-wrap: wrap;
  gap: 8px;
  margin-bottom: 12px;
}
.process-panel {
  margin-top: 14px;
  padding: 14px 16px;
  border: 1px solid var(--border-color);
  border-radius: 8px;
  background: var(--bg-secondary);
}
.process-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  margin-bottom: 12px;
  color: var(--text-primary);
}
.log-level {
  display: inline-block;
  min-width: 46px;
  margin-right: 8px;
  color: var(--text-secondary);
  text-transform: uppercase;
}
@media (max-width: 1180px) {
  .workbench,
  .summary-grid {
    grid-template-columns: 1fr;
  }
}
@media (max-width: 760px) {
  .page-header,
  .header-actions,
  .card-header,
  .run-actions {
    align-items: stretch;
    flex-direction: column;
  }
}
</style>
