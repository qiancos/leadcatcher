<script setup>
import { computed, reactive, ref } from 'vue'
import { ElMessage } from 'element-plus'
import { api, formatTime, FOLLOW_LABEL, INTENTS } from '../api'

const emit = defineEmits(['changed'])

const visible = ref(false)
const lead = ref(null)
const loading = ref(false)
const editing = ref(false)
const showFeedback = ref(false)
const submitting = ref(false)
let onChanged = null

const editForm = reactive({
  phone: '', customer_industry: '', demand: '', budget_hint: '',
  intent_level: '', risk_note: '', follow_status: ''
})

const feedback = reactive({
  wrong_fields: [],
  correct_values: {},
  error_category: 'BC-2',
  note: ''
})

const FIELD_OPTIONS = [
  { value: 'phone', label: '手机号' },
  { value: 'customer_industry', label: '客户行业' },
  { value: 'demand', label: '需求摘要' },
  { value: 'budget_hint', label: '预算' },
  { value: 'intent_level', label: '意向等级' },
  { value: 'overall', label: '整体漏识别' }
]

const CATEGORY_OPTIONS = [
  { value: 'BC-1', label: 'BC-1 手机号漏提取 / 误提取' },
  { value: 'BC-2', label: 'BC-2 意向判断偏差' },
  { value: 'BC-3', label: 'BC-3 需求摘要失真' },
  { value: 'BC-4', label: 'BC-4 行业误判' },
  { value: 'BC-5', label: 'BC-5 重复误判' },
  { value: 'BC-6', label: 'BC-6 格式 / 解析失败' }
]

const title = computed(() => (lead.value ? `线索 #${lead.value.id}` : '线索详情'))

async function open(id, callback) {
  onChanged = callback || null
  visible.value = true
  editing.value = false
  showFeedback.value = false
  loading.value = true
  try {
    lead.value = await api.get(id)
    Object.assign(editForm, {
      phone: lead.value.phone || '',
      customer_industry: lead.value.customer_industry || '',
      demand: lead.value.demand || '',
      budget_hint: lead.value.budget_hint || '',
      intent_level: lead.value.intent_level,
      risk_note: lead.value.risk_note || '',
      follow_status: lead.value.follow_status
    })
  } catch (error) {
    ElMessage.error(error.message)
    visible.value = false
  } finally {
    loading.value = false
  }
}

defineExpose({ open })

function refresh() {
  if (onChanged) onChanged()
  emit('changed')
}

async function saveEdit() {
  submitting.value = true
  try {
    await api.update(lead.value.id, { ...editForm })
    ElMessage.success('已保存，人工修正已记录')
    lead.value = await api.get(lead.value.id)
    editing.value = false
    refresh()
  } catch (error) {
    ElMessage.error(error.message)
  } finally {
    submitting.value = false
  }
}

async function verify(result) {
  try {
    await api.verify(lead.value.id, result)
    lead.value.human_verified = result
    ElMessage.success(result === 'correct' ? '已确认这条识别正确' : '已标记')
    refresh()
  } catch (error) {
    ElMessage.error(error.message)
  }
}

async function retry() {
  submitting.value = true
  try {
    const data = await api.retry(lead.value.id)
    lead.value = data.lead
    ElMessage.success('已重新解析')
    refresh()
  } catch (error) {
    ElMessage.error(error.message)
  } finally {
    submitting.value = false
  }
}

async function submitFeedback() {
  if (!feedback.wrong_fields.length) {
    ElMessage.warning('先勾选哪些字段识别错了')
    return
  }
  submitting.value = true
  try {
    await api.submitFeedback({
      lead_id: lead.value.id,
      wrong_fields: feedback.wrong_fields,
      correct_values: feedback.correct_values,
      error_category: feedback.error_category,
      note: feedback.note || null
    })
    ElMessage.success('反馈已入库，会成为下一轮 Prompt 迭代的样本')
    showFeedback.value = false
    feedback.wrong_fields = []
    feedback.correct_values = {}
    feedback.note = ''
    lead.value = await api.get(lead.value.id)
    refresh()
  } catch (error) {
    ElMessage.error(error.message)
  } finally {
    submitting.value = false
  }
}
</script>

<template>
  <el-drawer v-model="visible" :title="title" size="700px" destroy-on-close>
    <div v-loading="loading" class="drawer-body">
      <template v-if="lead">
        <div class="compare">
          <div class="compare-col">
            <h4>对话原文</h4>
            <div class="raw-text">{{ lead.raw_text }}</div>
          </div>

          <div class="compare-col">
            <h4>解析结果</h4>
            <div class="field-list">
              <div class="field-row">
                <div class="field-key">手机号</div>
                <div class="field-val" :class="{ muted: !lead.phone }">
                  <span class="cell-mono">{{ lead.phone || '未提取到' }}</span>
                </div>
              </div>
              <div class="field-row">
                <div class="field-key">客户行业</div>
                <div class="field-val" :class="{ muted: !lead.customer_industry }">{{ lead.customer_industry || '未判断' }}</div>
              </div>
              <div class="field-row">
                <div class="field-key">需求摘要</div>
                <div class="field-val" :class="{ muted: !lead.demand }">{{ lead.demand || '—' }}</div>
              </div>
              <div class="field-row">
                <div class="field-key">预算</div>
                <div class="field-val" :class="{ muted: !lead.budget_hint }">{{ lead.budget_hint || '对话未提及' }}</div>
              </div>
              <div class="field-row">
                <div class="field-key">意向等级</div>
                <div class="field-val">
                  <span class="intent-chip" :class="`intent-${lead.intent_level}`">
                    <i class="intent-dot"></i>{{ lead.intent_level }}
                  </span>
                  <span class="status-text" style="margin-left: 10px">{{ FOLLOW_LABEL[lead.follow_status] }}</span>
                </div>
              </div>
              <div class="field-row">
                <div class="field-key">风险备注</div>
                <div class="field-val" :class="{ muted: !lead.risk_note }">{{ lead.risk_note || '无异常' }}</div>
              </div>
              <div class="field-row">
                <div class="field-key">复核状态</div>
                <div class="field-val">
                  <el-tag v-if="lead.human_verified === 'correct'" size="small" type="success" effect="plain">人工确认正确</el-tag>
                  <el-tag v-else-if="lead.human_verified === 'wrong'" size="small" type="danger" effect="plain">人工标记错误</el-tag>
                  <span v-else class="status-text">尚未复核</span>
                </div>
              </div>
            </div>
          </div>
        </div>

        <div class="result-meta">
          <span>录入 <b>{{ formatTime(lead.created_at) }}</b></span>
          <span>Prompt <b>{{ lead.prompt_version }}</b></span>
          <span>解析耗时 <b>{{ lead.parse_ms ? lead.parse_ms + 'ms' : '<1ms' }}</b></span>
          <span v-if="lead.is_duplicate">与 <b>#{{ lead.duplicate_of }}</b> 手机号重复</span>
          <span v-if="lead.parse_error" style="color: #b42318">失败原因：{{ lead.parse_error }}</span>
        </div>

        <div v-if="!editing" class="drawer-actions">
          <el-button @click="editing = true">编辑字段</el-button>
          <el-button type="success" plain :disabled="lead.human_verified === 'correct'" @click="verify('correct')">
            确认识别正确
          </el-button>
          <el-button type="danger" plain @click="showFeedback = !showFeedback">标记识别错误</el-button>
          <el-button v-if="lead.parse_status === 'failed'" type="warning" plain :loading="submitting" @click="retry">
            重试解析
          </el-button>
        </div>

        <!-- 编辑 -->
        <div v-else class="panel" style="box-shadow: none">
          <p class="panel-title">人工修正</p>
          <p class="panel-desc">原文不可修改；这里改的是 AI 的解析结果，改动会覆盖原值并记录更新时间。</p>
          <el-form label-width="88px" label-position="left">
            <el-form-item label="手机号">
              <el-input v-model="editForm.phone" placeholder="11 位手机号，留空表示无" />
            </el-form-item>
            <el-form-item label="客户行业">
              <el-select v-model="editForm.customer_industry" clearable placeholder="选择或留空" style="width: 100%">
                <el-option v-for="item in ['餐饮','零售','教育','美业','房产','汽车','医疗','金融','本地生活','制造','互联网','其他']" :key="item" :label="item" :value="item" />
              </el-select>
            </el-form-item>
            <el-form-item label="需求摘要">
              <el-input v-model="editForm.demand" type="textarea" :rows="2" maxlength="60" show-word-limit />
            </el-form-item>
            <el-form-item label="预算">
              <el-input v-model="editForm.budget_hint" maxlength="40" placeholder="原文中的预算表述" />
            </el-form-item>
            <el-form-item label="意向等级">
              <el-radio-group v-model="editForm.intent_level">
                <el-radio-button v-for="level in INTENTS" :key="level" :label="level" />
              </el-radio-group>
            </el-form-item>
            <el-form-item label="跟进状态">
              <el-radio-group v-model="editForm.follow_status">
                <el-radio-button label="pending">待跟进</el-radio-button>
                <el-radio-button label="followed">已跟进</el-radio-button>
                <el-radio-button label="invalid">已放弃</el-radio-button>
              </el-radio-group>
            </el-form-item>
            <el-form-item label="风险备注">
              <el-input v-model="editForm.risk_note" maxlength="40" placeholder="无异常可留空" />
            </el-form-item>
          </el-form>
          <div class="drawer-actions">
            <el-button type="primary" :loading="submitting" @click="saveEdit">保存</el-button>
            <el-button @click="editing = false">取消</el-button>
          </div>
        </div>

        <!-- 纠错反馈 -->
        <div v-if="showFeedback && !editing" class="feedback-form">
          <p class="panel-title">标记识别错误</p>
          <p class="panel-desc">
            反馈不是"记一笔抱怨"，而是下一轮改 Prompt 的样本。请尽量填对正确值，并选准错误归因。
          </p>

          <el-form label-width="88px" label-position="left">
            <el-form-item label="错误字段">
              <el-checkbox-group v-model="feedback.wrong_fields">
                <el-checkbox v-for="opt in FIELD_OPTIONS" :key="opt.value" :label="opt.value">
                  {{ opt.label }}
                </el-checkbox>
              </el-checkbox-group>
            </el-form-item>

            <template v-for="field in feedback.wrong_fields" :key="field">
              <el-form-item v-if="field !== 'overall'" :label="FIELD_OPTIONS.find((o) => o.value === field)?.label">
                <el-radio-group v-if="field === 'intent_level'" v-model="feedback.correct_values[field]">
                  <el-radio-button v-for="level in INTENTS" :key="level" :label="level" />
                </el-radio-group>
                <el-input v-else v-model="feedback.correct_values[field]" placeholder="填写正确值" />
              </el-form-item>
            </template>

            <el-form-item label="错误归因">
              <el-select v-model="feedback.error_category" style="width: 100%">
                <el-option v-for="opt in CATEGORY_OPTIONS" :key="opt.value" :label="opt.label" :value="opt.value" />
              </el-select>
            </el-form-item>

            <el-form-item label="备注">
              <el-input v-model="feedback.note" type="textarea" :rows="2" placeholder="例如：客户只说先看看，判成高偏乐观" />
            </el-form-item>
          </el-form>

          <div class="drawer-actions">
            <el-button type="primary" :loading="submitting" @click="submitFeedback">提交反馈</el-button>
            <el-button @click="showFeedback = false">取消</el-button>
          </div>
          <p class="form-tip">提交后这条线索会被标记为「人工标记错误」，进入反馈库等待周度聚类复盘。</p>
        </div>
      </template>
    </div>
  </el-drawer>
</template>
