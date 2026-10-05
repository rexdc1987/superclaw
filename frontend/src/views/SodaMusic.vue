<template>
  <div class="soda-page">
    <div class="page-header">
      <div>
        <h3>汽水音乐曲库</h3>
        <p>维护可展示的热歌曲目，用于选题参考与内容规划。</p>
      </div>
      <div class="header-actions">
        <el-button :loading="seeding" @click="handleSeed">
          <el-icon><Download /></el-icon>
          导入示例数据
        </el-button>
        <el-button v-if="isAdmin" type="primary" @click="openCreate">
          <el-icon><Plus /></el-icon>
          新增曲目
        </el-button>
      </div>
    </div>

    <div class="stat-grid">
      <div v-for="card in statCards" :key="card.label" class="stat-card">
        <div class="stat-icon">
          <el-icon><component :is="card.icon" /></el-icon>
        </div>
        <div class="stat-body">
          <div class="stat-value">{{ card.value }}</div>
          <div class="stat-label">{{ card.label }}</div>
        </div>
      </div>
    </div>

    <el-card>
      <div class="filter-row">
        <el-input
          v-model="query.keyword"
          placeholder="搜索曲名 / 歌手 / 专辑 / 标签"
          clearable
          style="width: 280px"
          @keyup.enter="reload"
          @clear="reload"
        >
          <template #prefix><el-icon><Search /></el-icon></template>
        </el-input>

        <el-select v-model="query.genre" placeholder="全部曲风" clearable style="width: 140px" @change="reload">
          <el-option v-for="item in filterOptions.genres" :key="item" :label="item" :value="item" />
        </el-select>

        <el-select v-model="query.language" placeholder="全部语种" clearable style="width: 140px" @change="reload">
          <el-option v-for="item in filterOptions.languages" :key="item" :label="item" :value="item" />
        </el-select>

        <el-select v-model="query.sort" style="width: 150px" @change="reload">
          <el-option label="按榜单排名" value="rank" />
          <el-option label="按热度" value="heat" />
          <el-option label="最新收录" value="newest" />
          <el-option label="按曲名" value="title" />
        </el-select>

        <el-checkbox v-model="query.ranked_only" @change="reload">仅看上榜</el-checkbox>

        <el-button text @click="resetQuery">
          <el-icon><Refresh /></el-icon>
          重置
        </el-button>
      </div>
    </el-card>

    <el-card>
      <el-table :data="songs" v-loading="loading" style="width: 100%">
        <template #empty>
          <div class="empty-state">
            <p>曲库还没有数据</p>
            <p class="empty-hint">点击右上角「导入示例数据」快速填充 {{ SEED_HINT }} 首曲目</p>
          </div>
        </template>

        <el-table-column label="排名" width="80">
          <template #default="{ row }">
            <span v-if="row.rank_position" class="rank-badge" :class="rankClass(row.rank_position)">
              {{ row.rank_position }}
            </span>
            <span v-else class="rank-none">—</span>
          </template>
        </el-table-column>

        <el-table-column label="曲目" min-width="190" show-overflow-tooltip>
          <template #default="{ row }">
            <div class="song-cell">
              <div class="song-title">{{ row.title }}</div>
              <div class="song-sub">{{ row.artist || '未知歌手' }}</div>
            </div>
          </template>
        </el-table-column>

        <el-table-column prop="album" label="专辑" min-width="150" show-overflow-tooltip>
          <template #default="{ row }">{{ row.album || '-' }}</template>
        </el-table-column>

        <el-table-column label="曲风" width="100">
          <template #default="{ row }">
            <span v-if="row.genre" class="tag-chip">{{ row.genre }}</span>
            <span v-else class="rank-none">-</span>
          </template>
        </el-table-column>

        <el-table-column label="语种" width="84">
          <template #default="{ row }">{{ row.language || '-' }}</template>
        </el-table-column>

        <el-table-column label="时长" width="86">
          <template #default="{ row }">{{ row.duration_text }}</template>
        </el-table-column>

        <el-table-column label="热度" width="164">
          <template #default="{ row }">
            <div class="heat-cell">
              <div class="heat-bar">
                <div class="heat-fill" :style="{ width: heatPercent(row.heat) + '%' }"></div>
              </div>
              <span class="heat-num">{{ formatHeat(row.heat) }}</span>
            </div>
          </template>
        </el-table-column>

        <el-table-column label="标签" min-width="150">
          <template #default="{ row }">
            <template v-if="splitTags(row.tags).length">
              <span v-for="tag in splitTags(row.tags)" :key="tag" class="tag-chip alt">{{ tag }}</span>
            </template>
            <span v-else class="rank-none">-</span>
          </template>
        </el-table-column>

        <el-table-column label="发行日期" width="116">
          <template #default="{ row }">{{ row.release_date || '-' }}</template>
        </el-table-column>

        <el-table-column v-if="isAdmin" label="操作" width="140" fixed="right">
          <template #default="{ row }">
            <el-button size="small" @click="openEdit(row)">编辑</el-button>
            <el-button size="small" type="danger" @click="handleDelete(row)">删除</el-button>
          </template>
        </el-table-column>
      </el-table>

      <div class="pager">
        <el-pagination
          background
          layout="total, sizes, prev, pager, next"
          :total="total"
          :current-page="query.page"
          :page-size="query.page_size"
          :page-sizes="[10, 20, 50, 100]"
          @current-change="handlePageChange"
          @size-change="handleSizeChange"
        />
      </div>
    </el-card>

    <el-dialog
      v-model="dialogVisible"
      :title="editingId ? '编辑曲目' : '新增曲目'"
      width="640px"
      :close-on-click-modal="false"
    >
      <el-form :model="form" label-width="92px">
        <el-row :gutter="12">
          <el-col :span="12">
            <el-form-item label="曲名" required>
              <el-input v-model="form.title" placeholder="必填" />
            </el-form-item>
          </el-col>
          <el-col :span="12">
            <el-form-item label="歌手">
              <el-input v-model="form.artist" />
            </el-form-item>
          </el-col>
          <el-col :span="12">
            <el-form-item label="专辑">
              <el-input v-model="form.album" />
            </el-form-item>
          </el-col>
          <el-col :span="12">
            <el-form-item label="曲风">
              <el-input v-model="form.genre" placeholder="例如：流行 / 民谣" />
            </el-form-item>
          </el-col>
          <el-col :span="12">
            <el-form-item label="语种">
              <el-input v-model="form.language" placeholder="例如：国语 / 粤语" />
            </el-form-item>
          </el-col>
          <el-col :span="12">
            <el-form-item label="时长(秒)">
              <el-input-number v-model="form.duration_sec" :min="0" :max="86400" style="width: 100%" />
            </el-form-item>
          </el-col>
          <el-col :span="12">
            <el-form-item label="热度">
              <el-input-number v-model="form.heat" :min="0" style="width: 100%" />
            </el-form-item>
          </el-col>
          <el-col :span="12">
            <el-form-item label="榜单排名">
              <el-input-number
                v-model="form.rank_position"
                :min="1"
                :max="9999"
                placeholder="留空表示未上榜"
                style="width: 100%"
              />
            </el-form-item>
          </el-col>
          <el-col :span="12">
            <el-form-item label="发行日期">
              <el-input v-model="form.release_date" placeholder="YYYY-MM-DD" />
            </el-form-item>
          </el-col>
          <el-col :span="12">
            <el-form-item label="标签">
              <el-input v-model="form.tags" placeholder="逗号分隔" />
            </el-form-item>
          </el-col>
          <el-col :span="24">
            <el-form-item label="备注">
              <el-input v-model="form.remark" type="textarea" :rows="2" />
            </el-form-item>
          </el-col>
        </el-row>
      </el-form>
      <template #footer>
        <el-button @click="dialogVisible = false">取消</el-button>
        <el-button type="primary" :loading="submitting" @click="handleSave">保存</el-button>
      </template>
    </el-dialog>
  </div>
</template>

<script setup>
import { computed, onMounted, reactive, ref } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import { useUserStore } from '@/stores/user'
import {
  createSodaSong,
  deleteSodaSong,
  getSodaFilters,
  getSodaSongs,
  getSodaStats,
  seedSodaSongs,
  updateSodaSong,
} from '@/api/soda'

const userStore = useUserStore()
const isAdmin = computed(() => (userStore.userInfo.role || '') === 'admin')

const loading = ref(false)
const seeding = ref(false)
const submitting = ref(false)
const dialogVisible = ref(false)
const editingId = ref(null)
const songs = ref([])
const total = ref(0)
const stats = ref({ total: 0, artist_count: 0, genre_count: 0, ranked_count: 0, total_heat: 0, avg_duration_sec: 0, top_genre: null })
const filterOptions = reactive({ genres: [], languages: [] })

const query = reactive({
  keyword: '',
  genre: '',
  language: '',
  ranked_only: false,
  sort: 'rank',
  page: 1,
  page_size: 20,
})

const emptyForm = () => ({
  title: '',
  artist: '',
  album: '',
  genre: '',
  language: '',
  duration_sec: 0,
  heat: 0,
  rank_position: null,
  release_date: '',
  tags: '',
  remark: '',
})
const form = reactive(emptyForm())

const statCards = computed(() => [
  { label: '曲目总数', value: stats.value.total, icon: 'Collection' },
  { label: '歌手数', value: stats.value.artist_count, icon: 'Microphone' },
  { label: '已上榜', value: stats.value.ranked_count, icon: 'Trophy' },
  { label: '累计热度', value: formatHeat(stats.value.total_heat), icon: 'TrendCharts' },
])

const maxHeat = computed(() => Math.max(1, ...songs.value.map((item) => Number(item.heat) || 0)))

function heatPercent(heat) {
  return Math.min(100, Math.round(((Number(heat) || 0) / maxHeat.value) * 100))
}

function formatHeat(value) {
  const num = Number(value) || 0
  if (num >= 100000000) return (num / 100000000).toFixed(1) + '亿'
  if (num >= 10000) return (num / 10000).toFixed(1) + '万'
  return String(num)
}

function rankClass(position) {
  if (position === 1) return 'top1'
  if (position === 2) return 'top2'
  if (position === 3) return 'top3'
  return ''
}

function splitTags(tags) {
  if (!tags) return []
  return String(tags)
    .split(/[,，]/)
    .map((item) => item.trim())
    .filter(Boolean)
}

async function loadSongs() {
  loading.value = true
  try {
    const params = {
      page: query.page,
      page_size: query.page_size,
      sort: query.sort,
      ranked_only: query.ranked_only,
    }
    if (query.keyword.trim()) params.keyword = query.keyword.trim()
    if (query.genre) params.genre = query.genre
    if (query.language) params.language = query.language
    const res = await getSodaSongs(params)
    songs.value = res.items || []
    total.value = res.total || 0
  } finally {
    loading.value = false
  }
}

async function loadStats() {
  stats.value = await getSodaStats()
}

async function loadFilters() {
  const res = await getSodaFilters()
  filterOptions.genres = res.genres || []
  filterOptions.languages = res.languages || []
}

async function refreshAll() {
  await Promise.all([loadSongs(), loadStats(), loadFilters()])
}

function reload() {
  query.page = 1
  loadSongs()
}

function resetQuery() {
  Object.assign(query, {
    keyword: '',
    genre: '',
    language: '',
    ranked_only: false,
    sort: 'rank',
    page: 1,
  })
  loadSongs()
}

function handlePageChange(page) {
  query.page = page
  loadSongs()
}

function handleSizeChange(size) {
  query.page_size = size
  query.page = 1
  loadSongs()
}

function openCreate() {
  editingId.value = null
  Object.assign(form, emptyForm())
  dialogVisible.value = true
}

function openEdit(row) {
  editingId.value = row.id
  Object.assign(form, {
    title: row.title || '',
    artist: row.artist || '',
    album: row.album || '',
    genre: row.genre || '',
    language: row.language || '',
    duration_sec: row.duration_sec || 0,
    heat: row.heat || 0,
    rank_position: row.rank_position ?? null,
    release_date: row.release_date || '',
    tags: row.tags || '',
    remark: row.remark || '',
  })
  dialogVisible.value = true
}

async function handleSave() {
  if (!form.title.trim()) {
    ElMessage.warning('请输入曲名')
    return
  }
  submitting.value = true
  try {
    const payload = {
      title: form.title.trim(),
      artist: (form.artist || '').trim(),
      album: form.album || null,
      genre: form.genre || null,
      language: form.language || null,
      duration_sec: Number(form.duration_sec) || 0,
      heat: Number(form.heat) || 0,
      rank_position: form.rank_position === null || form.rank_position === undefined || form.rank_position === ''
        ? null
        : Number(form.rank_position),
      release_date: form.release_date || null,
      tags: form.tags || null,
      remark: form.remark || null,
    }
    if (editingId.value) {
      await updateSodaSong(editingId.value, payload)
    } else {
      await createSodaSong(payload)
    }
    dialogVisible.value = false
    ElMessage.success(editingId.value ? '更新成功' : '添加成功')
    await refreshAll()
  } finally {
    submitting.value = false
  }
}

async function handleDelete(row) {
  await ElMessageBox.confirm(`确定删除《${row.title}》吗？`, '删除确认', {
    type: 'warning',
    confirmButtonText: '删除',
    cancelButtonText: '取消',
  })
  await deleteSodaSong(row.id)
  ElMessage.success('删除成功')
  if (songs.value.length === 1 && query.page > 1) query.page -= 1
  await refreshAll()
}

async function handleSeed() {
  if (stats.value.total > 0) {
    await ElMessageBox.confirm(
      '曲库已有数据。继续将只补充缺失的示例曲目，不会覆盖已有记录。',
      '导入示例数据',
      { type: 'info', confirmButtonText: '继续导入', cancelButtonText: '取消' },
    )
  }
  seeding.value = true
  try {
    const res = await seedSodaSongs(false)
    ElMessage.success(`导入完成：新增 ${res.created} 首，跳过 ${res.skipped} 首，当前共 ${res.total} 首`)
    await refreshAll()
  } finally {
    seeding.value = false
  }
}

onMounted(refreshAll)
</script>

<style scoped>
.soda-page { display: flex; flex-direction: column; gap: 16px; }
.page-header { display: flex; align-items: center; justify-content: space-between; gap: 16px; }
.page-header h3 { margin: 0; font-size: 18px; color: var(--text-primary); }
.page-header p { margin-top: 6px; font-size: 13px; color: var(--text-secondary); }
.header-actions { display: flex; gap: 10px; flex-shrink: 0; }

.stat-grid { display: grid; grid-template-columns: repeat(4, minmax(0, 1fr)); gap: 14px; }
.stat-card { display: flex; align-items: center; gap: 14px; padding: 16px 18px; background: var(--bg-card); border: 1px solid var(--border-color); border-radius: 12px; }
.stat-icon { display: flex; align-items: center; justify-content: center; width: 42px; height: 42px; border-radius: 10px; background: var(--bg-input); color: var(--highlight); font-size: 20px; flex-shrink: 0; }
.stat-value { font-size: 22px; font-weight: 600; line-height: 1.2; color: var(--text-primary); }
.stat-label { margin-top: 2px; font-size: 12px; color: var(--text-secondary); }

.filter-row { display: flex; flex-wrap: wrap; align-items: center; gap: 10px; }

.empty-state { padding: 24px 0; }
.empty-state p { color: var(--text-secondary); font-size: 14px; }
.empty-hint { margin-top: 6px; font-size: 12px; color: var(--text-muted); }

.song-cell .song-title { font-weight: 500; color: var(--text-primary); }
.song-cell .song-sub { margin-top: 2px; font-size: 12px; color: var(--text-secondary); }

.rank-badge { display: inline-flex; align-items: center; justify-content: center; min-width: 26px; height: 22px; padding: 0 6px; border-radius: 6px; font-size: 12px; font-weight: 600; background: var(--bg-input); color: var(--text-secondary); }
.rank-badge.top1 { background: rgba(249, 226, 175, 0.18); color: #f9e2af; }
.rank-badge.top2 { background: rgba(203, 214, 230, 0.18); color: #cbd6e6; }
.rank-badge.top3 { background: rgba(224, 168, 120, 0.18); color: #e0a878; }
.rank-none { color: var(--text-muted); }

.tag-chip { display: inline-block; margin-right: 6px; padding: 1px 8px; border-radius: 6px; font-size: 12px; background: rgba(137, 180, 250, 0.14); color: #89b4fa; white-space: nowrap; }
.tag-chip.alt { background: rgba(166, 227, 161, 0.14); color: #a6e3a1; }

.heat-cell { display: flex; align-items: center; gap: 8px; }
.heat-bar { flex: 1; min-width: 56px; height: 6px; border-radius: 3px; background: var(--bg-input); overflow: hidden; }
.heat-fill { height: 100%; border-radius: 3px; background: linear-gradient(90deg, rgba(137, 180, 250, 0.5), #89b4fa); }
.heat-num { min-width: 48px; text-align: right; font-size: 12px; color: var(--text-secondary); }

.pager { display: flex; justify-content: flex-end; margin-top: 16px; }

@media (max-width: 1100px) {
  .stat-grid { grid-template-columns: repeat(2, minmax(0, 1fr)); }
}
@media (max-width: 620px) {
  .stat-grid { grid-template-columns: 1fr; }
  .page-header { flex-direction: column; align-items: flex-start; }
}
</style>
