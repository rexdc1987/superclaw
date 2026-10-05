<template>
  <div class="attr-page">
    <div class="page-header">
      <div>
        <h3>机器归属</h3>
        <p>哪台机器属于哪个账号、它跑了多少产出，以及归属缺口在哪（仅管理员可见）。</p>
      </div>
      <div class="header-actions">
        <el-button :loading="loading" @click="reload">
          <el-icon><Refresh /></el-icon>
          刷新
        </el-button>
      </div>
    </div>

    <div class="stat-grid">
      <div v-for="card in statCards" :key="card.label" class="stat-card">
        <div class="stat-icon"><el-icon><component :is="card.icon" /></el-icon></div>
        <div class="stat-body">
          <div class="stat-value">{{ card.value }}</div>
          <div class="stat-label">{{ card.label }}</div>
        </div>
      </div>
    </div>

    <el-card v-loading="loading">
      <template #header>
        <div class="card-head">
          <span>机器档案与产出</span>
          <span class="card-sub">{{ summary.owned_count || 0 }} / {{ summary.machine_count || 0 }} 台已认领</span>
        </div>
      </template>
      <el-table :data="machines" style="width: 100%">
        <el-table-column label="机器" min-width="240">
          <template #default="{ row }">
            <div class="machine-id">{{ row.worker_id }}</div>
            <div class="cell-sub">{{ row.host }} · 最后心跳 {{ fmtTime(row.last_seen_at) }}</div>
          </template>
        </el-table-column>
        <el-table-column label="归属账号" min-width="170">
          <template #default="{ row }">
            <template v-if="row.owner_user_id">
              <el-tag type="primary" effect="plain" size="small">
                {{ row.owner_username || '#' + row.owner_user_id }}
              </el-tag>
              <div class="cell-sub">绑定于 {{ fmtTime(row.owner_bound_at) }}</div>
            </template>
            <el-tag v-else type="warning" effect="plain" size="small">未归属</el-tag>
          </template>
        </el-table-column>
        <el-table-column label="任务" min-width="170">
          <template #default="{ row }">
            <div class="cell-main">{{ row.task_total || 0 }}</div>
            <div class="cell-sub">
              运行 {{ row.task_running || 0 }} · 完成 {{ row.task_completed || 0 }} · 失败 {{ row.task_failed || 0 }}
            </div>
          </template>
        </el-table-column>
        <el-table-column label="评论" min-width="120">
          <template #default="{ row }">
            <div class="cell-main">{{ row.comments_sent || 0 }}</div>
            <div class="cell-sub">已验证 {{ row.comments_verified || 0 }}</div>
          </template>
        </el-table-column>
        <el-table-column label="互动" min-width="120">
          <template #default="{ row }">
            <div class="cell-main">赞 {{ row.likes_completed || 0 }}</div>
            <div class="cell-sub">藏 {{ row.favorites_completed || 0 }}</div>
          </template>
        </el-table-column>
        <el-table-column label="累计时长" width="110">
          <template #default="{ row }">{{ fmtDuration(row.duration_seconds) }}</template>
        </el-table-column>
        <el-table-column label="活动区间" min-width="200">
          <template #default="{ row }">
            <div class="cell-sub">{{ fmtTime(row.first_task_at) }}</div>
            <div class="cell-sub">→ {{ fmtTime(row.last_task_at) }}</div>
          </template>
        </el-table-column>
        <el-table-column label="操作" width="110" fixed="right">
          <template #default="{ row }">
            <el-button link type="primary" @click="openBind(row)">
              {{ row.owner_user_id ? '改绑' : '归属' }}
            </el-button>
          </template>
        </el-table-column>
        <template #empty>
          <div class="empty-state">
            <p>还没有机器档案。</p>
            <div class="empty-hint">机器第一次上报心跳时才会出现在这里。</div>
          </div>
        </template>
      </el-table>
    </el-card>

    <el-card v-loading="loading">
      <template #header>
        <div class="card-head">
          <span>归属建议（从历史任务反推，只读）</span>
          <span class="card-sub">
            需人工确认 {{ inference.ambiguous_count || 0 }} 台
          </span>
        </div>
      </template>
      <el-table :data="inference.proposals || []" style="width: 100%">
        <el-table-column label="机器" min-width="200">
          <template #default="{ row }">
            <div class="machine-id">{{ row.worker_id }}</div>
            <div class="cell-sub">共 {{ row.tasks_total || 0 }} 个任务，其中 {{ row.tasks_without_owner || 0 }} 个无主</div>
          </template>
        </el-table-column>
        <el-table-column label="建议归属" min-width="150">
          <template #default="{ row }">
            <el-tag v-if="row.proposed_owner_username" effect="plain" size="small">
              {{ row.proposed_owner_username }}
            </el-tag>
            <span v-else class="cell-sub">无法判断</span>
          </template>
        </el-table-column>
        <el-table-column label="置信度" min-width="160">
          <template #default="{ row }">
            <el-progress :percentage="row.confidence || 0" :stroke-width="8" />
          </template>
        </el-table-column>
        <el-table-column label="该机出现过的账号" min-width="240">
          <template #default="{ row }">
            <el-tag
              v-for="acct in row.distinct_accounts || []"
              :key="acct.owner_user_id"
              class="acct-chip"
              effect="plain"
              size="small"
              :type="acct.owner_user_id === row.proposed_owner_user_id ? 'primary' : 'info'"
            >
              {{ acct.username || '#' + acct.owner_user_id }} · {{ acct.tasks }}
            </el-tag>
          </template>
        </el-table-column>
        <el-table-column label="状态" width="110">
          <template #default="{ row }">
            <el-tag v-if="row.ambiguous" type="warning" effect="plain" size="small">需人工</el-tag>
            <el-tag v-else type="success" effect="plain" size="small">唯一</el-tag>
          </template>
        </el-table-column>
        <el-table-column label="操作" width="110" fixed="right">
          <template #default="{ row }">
            <el-button
              link
              type="primary"
              :disabled="!row.proposed_owner_username"
              @click="adopt(row)"
            >
              采纳
            </el-button>
          </template>
        </el-table-column>
        <template #empty><div class="empty-state"><p>没有可推断的历史任务。</p></div></template>
      </el-table>
      <div v-if="inference.note" class="note">{{ inference.note }}</div>
    </el-card>

    <el-card v-loading="loading">
      <template #header>
        <div class="card-head">
          <span>按账号统计</span>
          <span class="card-sub">两种口径：原始归属 vs 归属 + 机器回收</span>
        </div>
      </template>
      <el-tabs v-model="statTab">
        <el-tab-pane name="effective">
          <template #label>有效口径（归属 + 机器回收）</template>
          <el-table :data="byOwnerEffective" style="width: 100%">
            <el-table-column label="账号" min-width="150">
              <template #default="{ row }">
                <el-tag v-if="row.username" effect="plain" size="small">{{ row.username }}</el-tag>
                <el-tag v-else type="warning" effect="plain" size="small">未归属</el-tag>
              </template>
            </el-table-column>
            <el-table-column prop="total" label="任务" width="90" />
            <el-table-column label="来源" min-width="150">
              <template #default="{ row }">
                <div class="cell-sub">直接 {{ row.direct || 0 }} · 机器回收 {{ row.via_machine || 0 }}</div>
              </template>
            </el-table-column>
            <el-table-column label="运行/完成/失败" min-width="150">
              <template #default="{ row }">
                <div class="cell-sub">
                  {{ row.running || 0 }} / {{ row.completed || 0 }} / {{ row.failed || 0 }}
                </div>
              </template>
            </el-table-column>
            <el-table-column label="评论（发出/验证）" min-width="150">
              <template #default="{ row }">
                {{ row.comments_sent || 0 }} / {{ row.comments_verified || 0 }}
              </template>
            </el-table-column>
            <el-table-column label="互动（赞/藏）" min-width="130">
              <template #default="{ row }">
                {{ row.likes_completed || 0 }} / {{ row.favorites_completed || 0 }}
              </template>
            </el-table-column>
            <el-table-column label="最近任务" min-width="150">
              <template #default="{ row }">{{ fmtTime(row.last_task_at) }}</template>
            </el-table-column>
            <template #empty><div class="empty-state"><p>暂无数据。</p></div></template>
          </el-table>
        </el-tab-pane>
        <el-tab-pane name="raw">
          <template #label>原始口径（仅任务自身归属）</template>
          <el-table :data="byOwner" style="width: 100%">
            <el-table-column label="账号" min-width="150">
              <template #default="{ row }">
                <el-tag v-if="row.username" effect="plain" size="small">{{ row.username }}</el-tag>
                <el-tag v-else type="warning" effect="plain" size="small">未归属</el-tag>
              </template>
            </el-table-column>
            <el-table-column prop="total" label="任务" width="90" />
            <el-table-column label="其中无机器" width="120">
              <template #default="{ row }">{{ row.missing_worker || 0 }}</template>
            </el-table-column>
            <el-table-column label="运行/完成/失败" min-width="150">
              <template #default="{ row }">
                <div class="cell-sub">
                  {{ row.running || 0 }} / {{ row.completed || 0 }} / {{ row.failed || 0 }}
                </div>
              </template>
            </el-table-column>
            <el-table-column label="最近任务" min-width="150">
              <template #default="{ row }">{{ fmtTime(row.last_task_at) }}</template>
            </el-table-column>
            <template #empty><div class="empty-state"><p>暂无数据。</p></div></template>
          </el-table>
        </el-tab-pane>
      </el-tabs>
    </el-card>

    <el-card v-loading="loading">
      <template #header><div class="card-head"><span>归属缺口</span></div></template>
      <div class="gap-row">
        <div class="gap-item">
          <div class="gap-value">{{ gaps.tasks_without_owner || 0 }}</div>
          <div class="gap-label">无主任务</div>
        </div>
        <div class="gap-item">
          <div class="gap-value">{{ gaps.tasks_without_machine || 0 }}</div>
          <div class="gap-label">无机器任务</div>
        </div>
      </div>
      <el-table v-if="(gaps.orphan_buckets || []).length" :data="gaps.orphan_buckets" style="width: 100%; margin-top: 14px">
        <el-table-column label="机器" min-width="140">
          <template #default="{ row }">
            <span v-if="row.worker_id">{{ row.worker_id }}</span>
            <span v-else class="cell-sub">（空）</span>
          </template>
        </el-table-column>
        <el-table-column prop="n" label="任务数" width="100" />
        <el-table-column prop="min_id" label="最小 id" width="100" />
        <el-table-column prop="max_id" label="最大 id" width="100" />
        <el-table-column label="时间区间" min-width="220">
          <template #default="{ row }">{{ fmtTime(row.first_at) }} → {{ fmtTime(row.last_at) }}</template>
        </el-table-column>
      </el-table>
      <div v-if="gaps.note" class="note">{{ gaps.note }}</div>
    </el-card>

    <el-dialog v-model="bindVisible" title="机器归属" width="460px" :close-on-click-modal="false">
      <div class="bind-target">机器：<strong>{{ bindForm.worker_id }}</strong></div>
      <el-form label-width="94px" style="margin-top: 12px">
        <el-form-item label="归属账号">
          <el-select v-model="bindForm.username" filterable placeholder="选择账号" style="width: 100%">
            <el-option
              v-for="item in accountOptions"
              :key="item.id"
              :label="item.username + (item.nickname ? '（' + item.nickname + '）' : '')"
              :value="item.username"
            />
          </el-select>
        </el-form-item>
        <el-form-item label="强制覆盖">
          <el-switch v-model="bindForm.force" />
          <span class="form-hint">机器已有归属时才会用到，会写进 owner_conflict 留痕</span>
        </el-form-item>
        <el-form-item label="认领历史">
          <el-switch v-model="bindForm.backfill" />
          <span class="form-hint">把这台机器上 owner_user_id=0 的历史任务一起认领给该账号</span>
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="bindVisible = false">取消</el-button>
        <el-button type="primary" :loading="binding" @click="submitBind">保存</el-button>
      </template>
    </el-dialog>
  </div>
</template>

<script setup>
import { computed, onMounted, reactive, ref } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import { getUsers } from '@/api'
import {
  bindMachine,
  getAttributionGaps,
  getAttributionInference,
  getAttributionMachines,
} from '@/api/attribution'

const loading = ref(false)
const summary = ref({})
const machines = ref([])
const byOwner = ref([])
const byOwnerEffective = ref([])
const inference = ref({ proposals: [], ambiguous_count: 0, note: '' })
const gaps = ref({ orphan_buckets: [] })
const statTab = ref('effective')

const bindVisible = ref(false)
const binding = ref(false)
const accountOptions = ref([])
const bindForm = reactive({ worker_id: '', username: '', force: false, backfill: false })

const statCards = computed(() => [
  { label: '机器总数', value: summary.value.machine_count || 0, icon: 'Monitor' },
  { label: '已认领', value: summary.value.owned_count || 0, icon: 'CircleCheck' },
  { label: '归属冲突', value: summary.value.conflict_count || 0, icon: 'WarningFilled' },
  { label: '未归属机器', value: summary.value.unowned_machine_count || 0, icon: 'QuestionFilled' },
  { label: '任务总数', value: summary.value.task_total || 0, icon: 'List' },
  { label: '无主任务', value: summary.value.task_without_owner || 0, icon: 'UserFilled' },
  { label: '机器回收覆盖', value: summary.value.task_recovered_by_machine || 0, icon: 'Connection' },
  { label: '仍无归属', value: summary.value.task_still_unattributed || 0, icon: 'WarningFilled' },
])

function fmtTime(value) {
  if (!value) return '—'
  return String(value).replace('T', ' ').slice(0, 19)
}

function fmtDuration(seconds) {
  const total = Number(seconds || 0)
  if (total <= 0) return '—'
  const hours = Math.floor(total / 3600)
  const minutes = Math.round((total % 3600) / 60)
  if (hours <= 0) return minutes + ' 分钟'
  return hours + ' 小时 ' + minutes + ' 分'
}

async function loadAll() {
  loading.value = true
  try {
    const overview = await getAttributionMachines()
    summary.value = overview.summary || {}
    machines.value = overview.machines || []
    byOwner.value = overview.by_owner || []
    byOwnerEffective.value = overview.by_owner_effective || []
  } finally {
    loading.value = false
  }
  // 这两块各自独立，任一块失败不该把整页拖垮
  const [gapResult, inferenceResult] = await Promise.allSettled([
    getAttributionGaps(),
    getAttributionInference(),
  ])
  if (gapResult.status === 'fulfilled') gaps.value = gapResult.value || {}
  if (inferenceResult.status === 'fulfilled') inference.value = inferenceResult.value || {}
}

async function loadAccounts() {
  try {
    const users = await getUsers()
    accountOptions.value = (Array.isArray(users) ? users : users?.items || []).filter(
      (item) => item && item.username
    )
  } catch (error) {
    accountOptions.value = []
  }
}

function reload() {
  return loadAll()
}

function openBind(row) {
  Object.assign(bindForm, {
    worker_id: row.worker_id,
    username: row.owner_username || '',
    force: Boolean(row.owner_user_id),
    backfill: false,
  })
  bindVisible.value = true
}

function openBindFor(workerId, username) {
  Object.assign(bindForm, { worker_id: workerId, username: username || '', force: false, backfill: false })
  bindVisible.value = true
}

async function adopt(row) {
  if (!row.proposed_owner_username) return
  try {
    await ElMessageBox.confirm(
      '把机器 ' + row.worker_id + ' 归属给 ' + row.proposed_owner_username + '？',
      '采纳归属建议',
      { type: 'warning' }
    )
  } catch (error) {
    return
  }
  const hasOwner = machines.value.some(
    (item) => item.worker_id === row.worker_id && item.owner_user_id
  )
  openBindFor(row.worker_id, row.proposed_owner_username)
  bindForm.force = hasOwner
}

async function submitBind() {
  if (!bindForm.username) {
    ElMessage.warning('请选择归属账号')
    return
  }
  binding.value = true
  try {
    const result = await bindMachine(
      bindForm.worker_id,
      { username: bindForm.username, force: bindForm.force },
      bindForm.backfill
    )
    ElMessage.success(
      '已归属给 ' + result.owner_username +
      (result.tasks_backfilled ? '，并认领 ' + result.tasks_backfilled + ' 个历史任务' : '')
    )
    bindVisible.value = false
    await loadAll()
  } finally {
    binding.value = false
  }
}

onMounted(() => {
  loadAll()
  loadAccounts()
})
</script>

<style scoped>
.attr-page { display: flex; flex-direction: column; gap: 16px; }
.page-header { display: flex; align-items: center; justify-content: space-between; gap: 16px; }
.page-header h3 { margin: 0; font-size: 18px; color: var(--text-primary); }
.page-header p { margin-top: 6px; font-size: 13px; color: var(--text-secondary); }
.header-actions { display: flex; gap: 10px; flex-shrink: 0; }

.stat-grid { display: grid; grid-template-columns: repeat(4, minmax(0, 1fr)); gap: 14px; }
.stat-card { display: flex; align-items: center; gap: 14px; padding: 16px 18px; background: var(--bg-card); border: 1px solid var(--border-color); border-radius: 12px; }
.stat-icon { display: flex; align-items: center; justify-content: center; width: 42px; height: 42px; border-radius: 10px; background: var(--bg-input); color: var(--highlight); font-size: 20px; flex-shrink: 0; }
.stat-value { font-size: 22px; font-weight: 600; line-height: 1.2; color: var(--text-primary); }
.stat-label { margin-top: 2px; font-size: 12px; color: var(--text-secondary); }

.card-head { display: flex; align-items: center; justify-content: space-between; gap: 12px; }
.card-sub { font-size: 12px; color: var(--text-secondary); }
.machine-id { font-weight: 500; color: var(--text-primary); word-break: break-all; }
.cell-main { color: var(--text-primary); }
.cell-sub { margin-top: 2px; font-size: 12px; color: var(--text-secondary); }
.acct-chip { margin: 0 6px 6px 0; }

.note { margin-top: 12px; padding: 10px 12px; border-radius: 8px; background: var(--bg-input); color: var(--text-secondary); font-size: 12px; line-height: 1.6; }
.empty-state { padding: 20px 0; text-align: center; }
.empty-state p { color: var(--text-secondary); font-size: 14px; }
.empty-hint { margin-top: 6px; font-size: 12px; color: var(--text-muted); }

.gap-row { display: flex; gap: 28px; }
.gap-item { min-width: 120px; }
.gap-value { font-size: 24px; font-weight: 600; color: var(--text-primary); }
.gap-label { margin-top: 2px; font-size: 12px; color: var(--text-secondary); }

.bind-target { font-size: 13px; color: var(--text-secondary); }
.bind-target strong { color: var(--text-primary); }
.form-hint { margin-left: 10px; font-size: 12px; color: var(--text-muted); }

@media (max-width: 1200px) {
  .stat-grid { grid-template-columns: repeat(2, minmax(0, 1fr)); }
}
</style>
