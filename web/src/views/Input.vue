<script setup>
import { computed, ref } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import { api, formatTime } from '../api'

const mode = ref('single')
const text = ref('')
const results = ref([])
const submitting = ref(false)

const MAX_LEN = 8000
const BATCH_LIMIT = 20

const charCount = computed(() => text.value.length)
const overLimit = computed(() => charCount.value > MAX_LEN)

const slices = computed(() => (mode.value === 'batch' ? splitText(text.value) : []))

function splitText(raw) {
  const trimmed = (raw || '').trim()
  if (!trimmed) return []

  // 切分优先级：分隔行 > 连续空行 > 一行一条（PRD FR-1.2）
  let parts = trimmed.split(/\n\s*(?:-{3,}|={3,})\s*\n/)
  if (parts.length > 1) return parts.map((s) => s.trim()).filter(Boolean)

  parts = trimmed.split(/\n\s*\n+/)
  if (parts.length > 1) return parts.map((s) => s.trim()).filter(Boolean)

  return trimmed.split(/\n/).map((s) => s.trim()).filter(Boolean)
}

function switchMode(next) {
  mode.value = next
  results.value = []
}

async function runOne(index) {
  const item = results.value[index]
  item.status = 'running'
  try {
    const res = await api.parse(item.text)
    if (res.status === 'duplicate_text') {
      item.status = 'dup_text'
      item.existing = res.existing
    } else {
      item.status = 'ok'
      item.lead = res.lead
      item.duplicate = res.duplicate
      item.meta = res.meta
    }
  } catch (error) {
    item.status = 'error'
    item.message = error.message
  }
}

async function submit() {
  const items = mode.value === 'batch' ? slices.value : [text.value.trim()]
  if (!items.length || !items[0]) {
    ElMessage.warning('请先粘贴对话内容')
    return
  }
  if (items.length > BATCH_LIMIT) {
    ElMessage.warning(`本次识别到 ${items.length} 段，最多提交 ${BATCH_LIMIT} 段`)
    return
  }
  if (items.some((item) => item.length > MAX_LEN)) {
    ElMessage.error(`有片段超过 ${MAX_LEN} 字，请截取关键内容`)
    return
  }

  submitting.value = true
  results.value = items.map((item) => ({ text: item, status: 'pending' }))

  // 3 并发：早出结果早跟进，单条失败不影响其他条（PRD FR-1.2）
  let cursor = 0
  const workers = Array.from({ length: Math.min(3, items.length) }, async () => {
    while (true) {
      const index = cursor
      cursor += 1
      if (index >= items.length) break
      await runOne(index)
    }
  })
  await Promise.all(workers)
  submitting.value = false

  const okCount = results.value.filter((r) => r.status === 'ok').length
  if (okCount) ElMessage.success(`解析完成 ${okCount} 条`)
}

async function forceSave(item) {
  try {
    const res = await api.parse(item.text, true)
    item.status = 'ok'
    item.lead = res.lead
    item.duplicate = res.duplicate
    item.meta = res.meta
  } catch (error) {
    ElMessage.error(error.message)
  }
}

async function retryItem(item) {
  item.status = 'pending'
  const index = results.value.indexOf(item)
  await runOne(index)
}

function reset() {
  text.value = ''
  results.value = []
}

const SAMPLE = `你好，我们下个月在杭州开第三家火锅店，想做本地生活平台的推广，预算大概3万左右，方便的话加我 138-0012-3456 详聊？`

function fillSample() {
  text.value = SAMPLE
  mode.value = 'single'
  results.value = []
}

function intentClass(level) {
  return `intent-${level || '无效'}`
}
</script>

<template>
  <div>
    <div class="page-head">
      <div>
        <h1>线索录入</h1>
        <p class="sub">粘贴即解析：抽 6 个字段、判四级意向、查重，一条 5 秒内落地</p>
      </div>
      <div class="head-actions">
        <el-button @click="fillSample">填入示例</el-button>
        <el-button @click="$router.push('/')">去看板</el-button>
      </div>
    </div>

    <div class="input-grid">
      <div class="panel">
        <p class="panel-title">
          <span>{{ mode === 'batch' ? '批量粘贴（最多 20 段）' : '粘贴对话原文' }}</span>
          <el-button v-if="text" link size="small" @click="reset">清空</el-button>
        </p>
        <p class="panel-desc">
          支持微信聊天、私信、评论区、表单留言等纯文本。批量模式下用 <b>---</b> 或空行分隔多条；
          内容不含客户本人信息时也能入库，只是会标「缺联系方式」。
        </p>

        <el-radio-group :model-value="mode" style="margin-bottom: 12px" @change="switchMode">
          <el-radio-button label="single">单条</el-radio-button>
          <el-radio-button label="batch">批量</el-radio-button>
        </el-radio-group>

        <div class="textarea-wrap">
          <el-input
            v-model="text"
            type="textarea"
            :rows="mode === 'batch' ? 12 : 9"
            resize="none"
            placeholder="把客户发来的话原样粘进来，不用整理格式…"
          />
          <div class="counter">
            <span>{{ mode === 'batch' ? `已识别 ${slices.length} 段` : '单条模式' }}</span>
            <span :class="{ over: overLimit }">{{ charCount }} / {{ MAX_LEN }}</span>
          </div>
        </div>

        <div v-if="mode === 'batch' && slices.length" class="slice-list">
          <div v-for="(slice, index) in slices" :key="index" class="slice-item">
            <span class="slice-index">{{ index + 1 }}</span>
            <span class="slice-text">{{ slice }}</span>
            <span style="margin-left: auto; color: #98a2b3; white-space: nowrap">{{ slice.length }} 字</span>
          </div>
        </div>

        <div class="drawer-actions" style="margin-top: 14px">
          <el-button
            type="primary"
            :loading="submitting"
            :disabled="!text.trim() || overLimit"
            @click="submit"
          >
            {{ submitting ? '解析中…' : '开始解析' }}
          </el-button>
          <span class="toolbar-note">
            解析失败不会丢数据：原文照常入库，可在看板重试或手填
          </span>
        </div>
      </div>

      <div class="panel">
        <p class="panel-title">
          <span>解析结果</span>
          <span v-if="results.length" class="toolbar-note">{{ results.filter((r) => r.status === 'ok').length }} / {{ results.length }} 成功</span>
        </p>
        <p class="panel-desc">
          每条结果都能直接编辑纠错。判错的样本点「标记错误」，会进入反馈库成为 Prompt 迭代素材。
        </p>

        <div v-if="!results.length" class="empty-hint">
          还没有结果。<br />在左侧粘贴一段对话，点「开始解析」试试。
        </div>

        <div v-else class="result-list">
          <div v-for="(item, index) in results" :key="index" class="result-card" :class="{ failed: item.status === 'error' }">
            <div class="result-head">
              <span class="toolbar-note">#{{ index + 1 }} · {{ item.text.length }} 字</span>
              <el-tag v-if="item.status === 'running'" size="small" type="warning" effect="plain">解析中</el-tag>
              <el-tag v-else-if="item.status === 'ok'" size="small" type="success" effect="plain">
                {{ item.meta?.provider === 'mock' ? '规则引擎' : '模型' }} · {{ item.meta?.elapsed_ms ? item.meta.elapsed_ms + 'ms' : '<1ms' }}
              </el-tag>
              <el-tag v-else-if="item.status === 'error'" size="small" type="danger" effect="plain">失败</el-tag>
              <el-tag v-else-if="item.status === 'dup_text'" size="small" type="info" effect="plain">内容重复</el-tag>
              <el-tag v-else size="small" type="info" effect="plain">排队中</el-tag>
            </div>

            <template v-if="item.status === 'ok'">
              <div class="result-demand">{{ item.lead.demand }}</div>
              <div class="result-meta">
                <span>手机号 <b class="cell-mono">{{ item.lead.phone || '—' }}</b></span>
                <span>行业 <b>{{ item.lead.customer_industry || '—' }}</b></span>
                <span>预算 <b>{{ item.lead.budget_hint || '未提及' }}</b></span>
                <span>
                  意向
                  <b><span class="intent-chip" :class="intentClass(item.lead.intent_level)"><i class="intent-dot"></i>{{ item.lead.intent_level }}</span></b>
                </span>
                <span>录入 <b>{{ formatTime(item.lead.created_at) }}</b></span>
              </div>

              <div v-if="item.duplicate?.is_duplicate" class="notice warn">
                手机号与线索 #{{ item.duplicate.duplicate_of }} 重复，已标记「重复」。可去详情确认是否同一客户。
              </div>
              <div v-else-if="item.duplicate?.weak" class="notice warn">
                疑似与 #{{ item.duplicate.weak.id }} 重复（相似度 {{ item.duplicate.weak.score }}），仅提示，未标记。
              </div>
              <div v-if="item.lead.risk_note" class="notice danger">{{ item.lead.risk_note }}</div>
              <div v-if="item.meta?.parse_error" class="notice danger">解析异常：{{ item.meta.parse_error }}</div>
            </template>

            <template v-else-if="item.status === 'dup_text'">
              <div class="notice warn">
                这段内容已经录入过（创建于 {{ formatTime(item.existing.created_at) }}，意向 {{ item.existing.intent_level }}）。
              </div>
              <div class="drawer-actions" style="margin-top: 8px">
                <el-button size="small" @click="forceSave(item)">仍然录入</el-button>
                <el-button size="small" type="info" link @click="$router.push('/')">去看原线索</el-button>
              </div>
            </template>

            <template v-else-if="item.status === 'error'">
              <div class="notice danger">{{ item.message }}</div>
              <el-button size="small" style="margin-top: 8px" @click="retryItem(item)">重试</el-button>
            </template>

            <template v-else>
              <div class="notice" style="background: #f8f9fb; color: #667085">等待解析…</div>
            </template>
          </div>
        </div>
      </div>
    </div>
  </div>
</template>
