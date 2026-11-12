<script setup>
import { computed, onBeforeUnmount, onMounted, ref, watch } from 'vue'
import * as echarts from 'echarts'
import { ElMessage } from 'element-plus'
import { api, tokenStore } from '../api'

const days = ref(7)
const stats = ref(null)
const loading = ref(false)
const pieRef = ref(null)
const lineRef = ref(null)
const needToken = ref(false)
const tokenInput = ref('')

let pieChart = null
let lineChart = null

const INTENT_COLOR = { 高: '#d92d20', 中: '#dc6803', 低: '#667085', 无效: '#cbd5e1' }

const totalValid = computed(() => {
  if (!stats.value) return 0
  return Object.values(stats.value.intent_dist).reduce((sum, n) => sum + n, 0)
})

const intentRows = computed(() => {
  if (!stats.value) return []
  return ['高', '中', '低', '无效'].map((level) => ({
    level,
    value: stats.value.intent_dist[level] || 0,
    color: INTENT_COLOR[level],
    pct: totalValid.value ? Math.round(((stats.value.intent_dist[level] || 0) / totalValid.value) * 100) : 0
  }))
})

function renderPie() {
  if (!pieRef.value) return
  if (!pieChart) pieChart = echarts.init(pieRef.value)
  pieChart.setOption({
    tooltip: { trigger: 'item', formatter: '{b}：{c} 条（{d}%）' },
    graphic: [
      {
        type: 'text',
        left: 'center',
        top: '43%',
        style: {
          text: String(totalValid.value),
          fill: '#101828',
          fontSize: 26,
          fontWeight: 600,
          textAlign: 'center'
        }
      },
      {
        type: 'text',
        left: 'center',
        top: '54%',
        style: { text: '条有效线索', fill: '#98a2b3', fontSize: 11, textAlign: 'center' }
      }
    ],
    series: [
      {
        type: 'pie',
        radius: ['55%', '78%'],
        center: ['50%', '50%'],
        avoidLabelOverlap: true,
        itemStyle: { borderColor: '#fff', borderWidth: 3 },
        label: { show: false },
        labelLine: { show: false },
        emphasis: { scale: true, scaleSize: 6 },
        data: intentRows.value.map((row) => ({
          value: row.value,
          name: row.level,
          itemStyle: { color: row.color }
        }))
      }
    ]
  })
}

function renderLine() {
  if (!lineRef.value) return
  if (!lineChart) lineChart = echarts.init(lineRef.value)
  const daily = stats.value?.daily || []
  lineChart.setOption({
    grid: { left: 8, right: 12, top: 26, bottom: 6, containLabel: true },
    tooltip: { trigger: 'axis' },
    legend: { right: 0, top: 0, itemWidth: 8, itemHeight: 8, textStyle: { fontSize: 11, color: '#667085' } },
    xAxis: {
      type: 'category',
      data: daily.map((d) => d.date.slice(5)),
      axisLine: { lineStyle: { color: '#eaecf0' } },
      axisTick: { show: false },
      axisLabel: { color: '#98a2b3', fontSize: 11 }
    },
    yAxis: {
      type: 'value',
      min: 0,
      minInterval: 1,
      splitLine: { lineStyle: { color: '#f2f4f7' } },
      axisLabel: { color: '#98a2b3', fontSize: 11 }
    },
    series: [
      {
        name: '新增线索',
        type: 'line',
        smooth: 0.2,
        symbol: 'circle',
        symbolSize: 6,
        itemStyle: { color: '#3538cd' },
        lineStyle: { width: 2.5, color: '#3538cd' },
        areaStyle: {
          color: new echarts.graphic.LinearGradient(0, 0, 0, 1, [
            { offset: 0, color: 'rgba(53,56,205,0.18)' },
            { offset: 1, color: 'rgba(53,56,205,0.01)' }
          ])
        },
        data: daily.map((d) => d.count)
      },
      {
        name: '解析失败',
        type: 'bar',
        barWidth: 10,
        itemStyle: { color: '#fecdca', borderRadius: [3, 3, 0, 0] },
        data: daily.map((d) => d.failed)
      }
    ]
  })
}

async function load() {
  loading.value = true
  try {
    stats.value = await api.stats(days.value)
    needToken.value = false
    renderPie()
    renderLine()
  } catch (error) {
    if (error.status === 401) {
      needToken.value = true
    } else {
      ElMessage.error(error.message)
    }
  } finally {
    loading.value = false
  }
}

function saveToken() {
  tokenStore.set(tokenInput.value.trim())
  load()
}

function handleResize() {
  pieChart?.resize()
  lineChart?.resize()
}

watch(days, load)

onMounted(() => {
  load()
  window.addEventListener('resize', handleResize)
})

onBeforeUnmount(() => {
  window.removeEventListener('resize', handleResize)
  pieChart?.dispose()
  lineChart?.dispose()
})

const cards = computed(() => {
  const c = stats.value?.cards
  return [
    { label: '线索总量', value: c?.total ?? '—', hint: `近 ${days.value} 天趋势见右图`, tone: '' },
    { label: '有效线索', value: c?.valid ?? '—', hint: 'AI 判级非「无效」且解析成功', tone: 'accent' },
    { label: '待跟进', value: c?.pending ?? '—', hint: '真正反映今天要打几个电话', tone: 'warn' },
    { label: '解析失败', value: c?.failed ?? '—', hint: '原文保留，可重试或手填', tone: 'danger' }
  ]
})
</script>

<template>
  <div>
    <div class="page-head">
      <div>
        <h1>数据大盘</h1>
        <p class="sub">口径固定：有效线索只看 AI 判级，不随人工改状态而漂移</p>
      </div>
      <div class="head-actions">
        <el-radio-group v-model="days" size="default">
          <el-radio-button :label="7">7 天</el-radio-button>
          <el-radio-button :label="14">14 天</el-radio-button>
          <el-radio-button :label="30">30 天</el-radio-button>
        </el-radio-group>
        <el-button :loading="loading" @click="load">刷新</el-button>
      </div>
    </div>

    <div v-if="needToken" class="panel" style="margin-bottom: 16px">
      <p class="panel-title">需要访问口令</p>
      <p class="panel-desc">服务端配置了 ADMIN_TOKEN，输入后才能读取数据。</p>
      <div class="filter-row">
        <el-input v-model="tokenInput" placeholder="输入访问口令" show-password style="max-width: 280px" @keyup.enter="saveToken" />
        <el-button type="primary" @click="saveToken">确认</el-button>
      </div>
    </div>

    <div class="stat-strip">
      <div v-for="card in cards" :key="card.label" class="stat" :class="card.tone">
        <div class="stat-label">{{ card.label }}</div>
        <div class="stat-value">{{ card.value }}</div>
        <div class="stat-hint">{{ card.hint }}</div>
      </div>
    </div>

    <div class="chart-grid">
      <div class="panel">
        <div class="chart-head">
          <span class="chart-title">意向等级分布</span>
          <span class="chart-sub">分母 = 解析成功 {{ totalValid }} 条</span>
        </div>
        <div ref="pieRef" class="chart-box"></div>
        <div class="legend-list">
          <div v-for="row in intentRows" :key="row.level" class="legend-row">
            <span class="intent-chip" :class="`intent-${row.level}`"><i class="intent-dot"></i>{{ row.level }}</span>
            <div class="legend-bar"><i :style="{ width: row.pct + '%', background: row.color }"></i></div>
            <span class="legend-val">{{ row.value }} 条 · {{ row.pct }}%</span>
          </div>
        </div>
      </div>

      <div class="panel">
        <div class="chart-head">
          <span class="chart-title">每日新增线索</span>
          <span class="chart-sub">近 {{ days }} 天 · 含失败条数</span>
        </div>
        <div ref="lineRef" class="chart-box"></div>
      </div>
    </div>

    <div class="chart-grid" style="grid-template-columns: 1fr 1fr">
      <div class="panel">
        <div class="chart-head">
          <span class="chart-title">AI 识别质量</span>
          <span class="chart-sub">来自人工双动作复核</span>
        </div>
        <div v-if="stats" style="margin-top: 10px">
          <div class="legend-row" style="margin-bottom: 10px">
            <span style="width: 64px; color: #667085; font-size: 12px">准确率</span>
            <el-progress
              :percentage="Math.round((stats.accuracy.rate || 0) * 100)"
              :stroke-width="10"
              :color="(stats.accuracy.rate || 0) >= 0.8 ? '#039855' : '#dc6803'"
              style="flex: 1"
            />
          </div>
          <div class="result-meta" style="gap: 18px">
            <span>已复核 <b>{{ stats.accuracy.checked }}</b> 条</span>
            <span>确认正确 <b>{{ stats.accuracy.correct }}</b></span>
            <span>标记错误 <b>{{ stats.accuracy.wrong }}</b></span>
            <span>待处理反馈 <b>{{ stats.feedback.open }}</b></span>
          </div>
          <p class="panel-desc" style="margin: 12px 0 0">
            这个数只有在业务真的点过「确认正确 / 标记错误」之后才有意义 —— 没有分母的准确率是编的。
          </p>
        </div>
      </div>

      <div class="panel">
        <div class="chart-head">
          <span class="chart-title">口径说明</span>
          <span class="chart-sub">PRD 6.5</span>
        </div>
        <div class="field-list" style="margin-top: 8px">
          <div class="field-row">
            <div class="field-key">线索总量</div>
            <div class="field-val">全部未删除线索，含无效与失败</div>
          </div>
          <div class="field-row">
            <div class="field-key">有效线索</div>
            <div class="field-val">解析成功且 AI 判级非「无效」；人工放弃的线索仍计入，避免口径随人工操作漂移</div>
          </div>
          <div class="field-row">
            <div class="field-key">意向占比</div>
            <div class="field-val">分母为解析成功条数，失败与已删除不计入</div>
          </div>
          <div class="field-row">
            <div class="field-key">准确率</div>
            <div class="field-val">人工确认正确 ÷（确认正确 + 标记错误），口径与验收标准一致</div>
          </div>
        </div>
      </div>
    </div>
  </div>
</template>
