<script setup>
import { onMounted, reactive, ref } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import {
  api, formatTime, FOLLOW_COLORS, FOLLOW_LABEL, INTENTS
} from '../api'
import LeadDrawer from '../components/LeadDrawer.vue'

const loading = ref(false)
const rows = ref([])
const total = ref(0)
const page = ref(1)
const size = ref(20)
const stats = ref(null)
const drawer = ref(null)

const filters = reactive({
  intents: [...INTENTS],
  statuses: ['pending', 'followed', 'invalid'],
  q: '',
  range: 'all',
  onlyDup: false,
  onlyFailed: false
})

const RANGE_OPTIONS = [
  { label: '全部时间', value: 'all' },
  { label: '今天', value: 'today' },
  { label: '近 7 天', value: '7d' },
  { label: '近 30 天', value: '30d' }
]

function dateFrom() {
  const now = new Date()
  if (filters.range === 'today') {
    const d = new Date(now.getFullYear(), now.getMonth(), now.getDate())
    return d.toISOString()
  }
  if (filters.range === '7d') return new Date(now.getTime() - 6 * 864e5).toISOString()
  if (filters.range === '30d') return new Date(now.getTime() - 29 * 864e5).toISOString()
  return undefined
}

async function loadStats() {
  try {
    stats.value = await api.stats(7)
  } catch {
    stats.value = null
  }
}

async function reload(resetPage = false) {
  if (resetPage) page.value = 1
  loading.value = true
  try {
    const data = await api.list({
      intent: filters.intents.join(','),
      follow_status: filters.statuses.join(','),
      q: filters.q.trim(),
      date_from: dateFrom(),
      only_dup: filters.onlyDup || undefined,
      only_failed: filters.onlyFailed || undefined,
      page: page.value,
      size: size.value
    })
    rows.value = data.items
    total.value = data.total
  } catch (error) {
    ElMessage.error(error.message)
  } finally {
    loading.value = false
  }
}

function refreshAll(resetPage = false) {
  reload(resetPage)
  loadStats()
}

async function markFollowed(row) {
  const next = row.follow_status === 'followed' ? 'pending' : 'followed'
  try {
    await api.update(row.id, { follow_status: next })
    row.follow_status = next
    ElMessage.success(next === 'followed' ? '已标记跟进' : '已撤回跟进')
    loadStats()
  } catch (error) {
    ElMessage.error(error.message)
  }
}

async function verifyCorrect(row) {
  try {
    const result = row.human_verified === 'correct' ? 'unchecked' : 'correct'
    await api.verify(row.id, result)
    row.human_verified = result
    ElMessage.success(result === 'correct' ? '已确认识别正确' : '已取消确认')
    loadStats()
  } catch (error) {
    ElMessage.error(error.message)
  }
}

async function removeLead(row) {
  try {
    await ElMessageBox.confirm(
      `删除后 7 天内可恢复。确定删除这条线索吗？`,
      '删除线索',
      { type: 'warning', confirmButtonText: '删除', cancelButtonText: '取消' }
    )
  } catch {
    return
  }
  try {
    await api.remove(row.id)
    ElMessage.success('已删除（可在数据库恢复窗口内找回）')
    refreshAll()
  } catch (error) {
    ElMessage.error(error.message)
  }
}

async function retryParse(row) {
  try {
    await api.retry(row.id)
    ElMessage.success('已重新解析')
    refreshAll()
  } catch (error) {
    ElMessage.error(error.message)
  }
}

function openDetail(row) {
  drawer.value.open(row.id, () => refreshAll())
}

function rowClass({ row }) {
  return row.parse_status === 'failed' ? 'row-failed' : ''
}

onMounted(() => refreshAll())
</script>

<template>
  <div>
    <div class="page-head">
      <div>
        <h1>线索看板</h1>
        <p class="sub">待跟进置顶、高意向优先 —— 打开就能从上往下打电话</p>
      </div>
      <div class="head-actions">
        <el-button :loading="loading" @click="refreshAll()">刷新</el-button>
        <el-button type="primary" @click="$router.push('/input')">+ 录入线索</el-button>
      </div>
    </div>

    <div class="stat-strip">
      <div class="stat">
        <div class="stat-label">线索总量</div>
        <div class="stat-value">{{ stats?.cards.total ?? '—' }}</div>
        <div class="stat-hint">近 7 天新增 {{ stats ? stats.daily.reduce((s, d) => s + d.count, 0) : '—' }} 条</div>
      </div>
      <div class="stat accent">
        <div class="stat-label">有效线索</div>
        <div class="stat-value">{{ stats?.cards.valid ?? '—' }}</div>
        <div class="stat-hint">已排除 AI 判定的无效广告</div>
      </div>
      <div class="stat warn">
        <div class="stat-label">待跟进</div>
        <div class="stat-value">{{ stats?.cards.pending ?? '—' }}</div>
        <div class="stat-hint">含高意向 {{ rows.filter((r) => r.intent_level === '高' && r.follow_status === 'pending').length }} 条（当前页）</div>
      </div>
      <div class="stat danger">
        <div class="stat-label">解析失败</div>
        <div class="stat-value">{{ stats?.cards.failed ?? '—' }}</div>
        <div class="stat-hint">原文已保留，可重试或手填</div>
      </div>
    </div>

    <div class="filter-bar">
      <div class="filter-row">
        <span class="filter-label">意向</span>
        <el-checkbox-group v-model="filters.intents" @change="reload(true)">
          <el-checkbox-button v-for="level in INTENTS" :key="level" :label="level">{{ level }}</el-checkbox-button>
        </el-checkbox-group>

        <span class="filter-label" style="margin-left: 8px">状态</span>
        <el-checkbox-group v-model="filters.statuses" @change="reload(true)">
          <el-checkbox-button label="pending">待跟进</el-checkbox-button>
          <el-checkbox-button label="followed">已跟进</el-checkbox-button>
          <el-checkbox-button label="invalid">已放弃</el-checkbox-button>
        </el-checkbox-group>

        <el-select v-model="filters.range" style="width: 118px; margin-left: 8px" @change="reload(true)">
          <el-option v-for="opt in RANGE_OPTIONS" :key="opt.value" :label="opt.label" :value="opt.value" />
        </el-select>
      </div>

      <div class="filter-row">
        <el-input
          v-model="filters.q"
          class="grow"
          placeholder="搜索手机号（支持后四位）、需求、行业或原文内容"
          clearable
          @keyup.enter="reload(true)"
          @clear="reload(true)"
        />
        <el-button @click="reload(true)">搜索</el-button>
        <el-switch v-model="filters.onlyDup" active-text="仅看重复" @change="reload(true)" />
        <el-switch v-model="filters.onlyFailed" active-text="仅看失败" @change="reload(true)" />
      </div>
    </div>

    <div class="table-card">
      <el-table
        v-loading="loading"
        :data="rows"
        :row-class-name="rowClass"
        style="width: 100%"
        @row-click="openDetail"
      >
        <el-table-column label="录入时间" width="108">
          <template #default="{ row }">
            <span class="cell-mono">{{ formatTime(row.created_at) }}</span>
          </template>
        </el-table-column>

        <el-table-column label="手机号" width="152">
          <template #default="{ row }">
            <span class="cell-mono">{{ row.phone_masked || '—' }}</span>
            <span v-if="row.is_duplicate" class="badge-dup">重复</span>
            <span v-else-if="!row.phone" class="badge-fail" style="background:#f2f4f7;color:#667085">缺联系方式</span>
          </template>
        </el-table-column>

        <el-table-column label="客户行业" width="80">
          <template #default="{ row }">
            <span>{{ row.customer_industry || '—' }}</span>
          </template>
        </el-table-column>

        <el-table-column label="需求摘要" min-width="220">
          <template #default="{ row }">
            <div class="cell-demand">{{ row.parse_status === 'failed' ? '（解析失败，待补录）' : row.demand || '—' }}</div>
          </template>
        </el-table-column>

        <el-table-column label="意向" width="84">
          <template #default="{ row }">
            <span class="intent-chip" :class="`intent-${row.parse_status === 'failed' ? '无效' : row.intent_level}`">
              <i class="intent-dot"></i>
              {{ row.parse_status === 'failed' ? '失败' : row.intent_level }}
            </span>
          </template>
        </el-table-column>

        <el-table-column label="跟进状态" width="80">
          <template #default="{ row }">
            <el-tag size="small" :type="FOLLOW_COLORS[row.follow_status]" effect="plain">
              {{ FOLLOW_LABEL[row.follow_status] }}
            </el-tag>
          </template>
        </el-table-column>

        <el-table-column label="操作" width="224">
          <template #default="{ row }">
            <div @click.stop>
              <el-button link type="primary" size="small" @click="openDetail(row)">详情</el-button>
              <el-button
                link
                :type="row.follow_status === 'followed' ? 'info' : 'success'"
                size="small"
                @click="markFollowed(row)"
              >
                {{ row.follow_status === 'followed' ? '撤回' : '已跟进' }}
              </el-button>
              <el-button
                link
                :type="row.human_verified === 'correct' ? 'info' : 'success'"
                size="small"
                @click="verifyCorrect(row)"
              >
                {{ row.human_verified === 'correct' ? '已确认' : '确认正确' }}
              </el-button>
              <el-dropdown trigger="click" style="margin-left: 8px">
                <el-button link size="small">更多</el-button>
                <template #dropdown>
                  <el-dropdown-menu>
                    <el-dropdown-item v-if="row.parse_status === 'failed'" @click="retryParse(row)">重试解析</el-dropdown-item>
                    <el-dropdown-item @click="openDetail(row)">标记识别错误</el-dropdown-item>
                    <el-dropdown-item divided @click="removeLead(row)">删除线索</el-dropdown-item>
                  </el-dropdown-menu>
                </template>
              </el-dropdown>
            </div>
          </template>
        </el-table-column>

        <template #empty>
          <div class="empty-hint">
            没有符合条件的线索。<br />
            可以放宽筛选条件，或去「线索录入」粘贴一段对话试试。
          </div>
        </template>
      </el-table>

      <div class="pager">
        <el-pagination
          v-model:current-page="page"
          v-model:page-size="size"
          :total="total"
          :page-sizes="[10, 20, 50]"
          layout="total, sizes, prev, pager, next"
          background
          @current-change="reload()"
          @size-change="reload(true)"
        />
      </div>
    </div>

    <LeadDrawer ref="drawer" @changed="refreshAll()" />
  </div>
</template>
