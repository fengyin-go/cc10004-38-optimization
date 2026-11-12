<template>
  <section class="page derive-page" data-module="filter">
    <header class="page-head">
      <div>
        <h2>数据筛选 · 条件推导</h2>
        <p class="page-desc">
          维护筛选条件表达式，对样本对象试算并查看分步推导；确认后的解释保留规则版本快照，
          规则停用或修订后旧解释仍引用当时证据。
        </p>
      </div>
      <div class="page-actions">
        <button class="btn" type="button" @click="resetAll">重置全部演示数据</button>
      </div>
    </header>

    <!-- 跨模块跳回高亮提示 -->
    <div v-if="jumpHint" class="jump-banner">
      来自数据标签的跳转：当前查看规则「{{ jumpHint.ruleCode }}」在 v{{ jumpHint.version }} 时被标签引用的证据
      <button class="link" type="button" @click="jumpHint = null">知道了</button>
    </div>

    <SamplePanel :items="samples" :catalog="catalog" @reset="resetSamples" @save="saveSample" />

    <section class="work-panel">
      <header class="panel-head">
        <h3>筛选规则与条件版本</h3>
        <span class="panel-tip">规则状态沿用原有审批流（提交校验/启用/停用），条件修订单独升版本</span>
      </header>
      <div class="rule-grid">
        <article
          v-for="rule in rules"
          :key="rule.id"
          class="rule-card"
          :class="{ active: selectedRuleId === rule.id, highlight: highlightRuleId === rule.id }"
        >
          <div class="rule-card-head">
            <strong>{{ rule.规则编号 }}</strong>
            <span class="state-pill" :class="statusClass(rule.status)">{{ rule.status }}</span>
          </div>
          <p class="rule-name">目标数据集：{{ rule.目标数据集 }}</p>
          <p v-if="conditions[rule.id]" class="rule-cond">v{{ conditions[rule.id].version }}：{{ conditions[rule.id].conditionText }}</p>
          <p v-else class="rule-cond muted">暂无结构化条件</p>
          <div class="rule-card-actions">
            <button class="btn primary" type="button" @click="selectRule(rule.id)">推导 / 修订</button>
            <button
              v-for="action in ruleActions"
              :key="action"
              class="link"
              type="button"
              @click="runRuleAction(action, rule)"
            >
              {{ action }}
            </button>
          </div>
        </article>
      </div>
    </section>

    <template v-if="selectedRule">
      <section class="work-panel">
        <header class="panel-head">
          <h3>{{ selectedRule.规则编号 }} · 条件表达式与修订历史</h3>
        </header>
        <div class="expr-editor">
          <label class="expr-input-wrap">
            <span>条件表达式</span>
            <textarea v-model="conditionDraft" rows="3" class="expr-input" />
          </label>
          <div class="expr-side">
            <label>
              <span>修订说明</span>
              <input v-model="conditionNote" class="cell-input" placeholder="例如：收紧消费金额阈值" />
            </label>
            <div class="expr-btns">
              <button class="btn primary" type="button" @click="saveCondition">保存条件（升新版本）</button>
              <button class="btn" type="button" @click="trial()">对全部样本试算</button>
            </div>
          </div>
        </div>
        <p v-if="conditionError" class="error-text">{{ conditionError }}</p>

        <div v-if="currentCondition" class="revision-list">
          <p class="sub-title">修订历史（旧标签引用的证据按当时版本保留）</p>
          <ol>
            <li v-for="rev in [...currentCondition.revisions].reverse()" :key="rev.version" class="revision-item">
              <span class="version-tag">v{{ rev.version }}</span>
              <span class="rev-text">{{ rev.conditionText }}</span>
              <span class="rev-meta">{{ rev.changedAt }} · {{ rev.note }}</span>
            </li>
          </ol>
        </div>
      </section>

      <section class="work-panel">
        <header class="panel-head">
          <h3>试算结果与分步推导</h3>
          <div v-if="latestRun" class="head-actions">
            <span class="panel-tip">运行 {{ latestRun.runId }} · 覆盖 {{ latestRun.coverageCount }}/{{ latestRun.totalCount }}</span>
            <button class="btn primary" type="button" @click="confirmAll">全部确认生成有效解释</button>
          </div>
        </header>

        <div v-if="!latestRun" class="empty-block">尚未试算，点击上方按钮查看每个对象的推导过程</div>
        <div v-else class="result-list">
          <article v-for="result in latestRun.results" :key="result.objectId" class="result-card" :class="result.hit ? 'card-hit' : 'card-miss'">
            <header class="expl-head">
              <div class="expl-title">
                <span class="state-pill" :class="result.hit ? 'pill-hit' : 'pill-miss'">
                  {{ result.hit ? '命中' : '本次未命中' }}
                </span>
                <strong>{{ result.objectLabel }}（{{ result.objectId }}）</strong>
              </div>
              <button class="btn" type="button" @click="trial(result.objectId)">只算该对象</button>
            </header>
            <TraceTree :node="result.trace" @jump="onJump" />
            <footer class="result-foot">
              <button class="btn primary" type="button" @click="confirmOne(result)">确认这条解释</button>
            </footer>
          </article>
        </div>
        <p v-if="confirmTip" class="save-tip">{{ confirmTip }}</p>
      </section>

      <section class="work-panel">
        <header class="panel-head">
          <h3>已确认解释（重复确认只保留一份）</h3>
          <label class="version-filter">
            按版本筛选：
            <select v-model.number="explVersion" @change="loadExplanations">
              <option :value="undefined">全部版本</option>
              <option v-for="rev in currentCondition?.revisions ?? []" :key="rev.version" :value="rev.version">
                v{{ rev.version }}
              </option>
            </select>
          </label>
        </header>
        <div v-if="!explanations.length" class="empty-block">还没有确认过解释</div>
        <ExplanationCard v-for="item in explanations" :key="item.explId" :explanation="item" @jump="onJump" />
      </section>
    </template>

    <AmbiguityDialog
      :visible="ambiguity.visible"
      :ambiguities="ambiguity.items"
      @close="ambiguity.visible = false"
      @confirm="resolveAmbiguity"
    />
  </section>
</template>

<script setup lang="ts">
import { computed, onMounted, reactive, ref } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { request } from '@/api/client'
import AmbiguityDialog from '@/views/derive/AmbiguityDialog.vue'
import ExplanationCard from '@/views/derive/ExplanationCard.vue'
import SamplePanel from '@/views/derive/SamplePanel.vue'
import TraceTree from '@/views/derive/TraceTree.vue'
import {
  deriveApi,
  readError,
  type Ambiguity,
  type Explanation,
  type FieldCatalogItem,
  type FilterCondition,
  type RunPayload,
  type RunResult,
  type SampleObject,
} from '@/views/derive/api'

interface FilterRow {
  id: number
  status: string
  规则编号: string
  目标数据集: string
}

const route = useRoute()
const router = useRouter()
const ruleActions = ['提交校验', '启用规则', '停用规则']

const samples = ref<SampleObject[]>([])
const catalog = ref<FieldCatalogItem[]>([])
const rules = ref<FilterRow[]>([])
const conditions = reactive<Record<number, FilterCondition>>({})
const selectedRuleId = ref<number | null>(null)
const conditionDraft = ref('')
const conditionNote = ref('业务修订')
const conditionError = ref('')
const latestRun = ref<RunPayload | null>(null)
const explanations = ref<Explanation[]>([])
const explVersion = ref<number | undefined>(undefined)
const confirmTip = ref('')
const highlightRuleId = ref<number | null>(null)
const jumpHint = ref<{ ruleCode: string; version: number } | null>(null)
const ambiguity = reactive<{
  visible: boolean
  items: Ambiguity[]
  retry: null | ((identityMap: Record<string, string>) => Promise<void>)
}>({
  visible: false,
  items: [],
  retry: null,
})

const selectedRule = computed(() => rules.value.find((item) => item.id === selectedRuleId.value) ?? null)
const currentCondition = computed(() => (selectedRuleId.value ? conditions[selectedRuleId.value] : undefined))

function statusClass(status: string): string {
  if (status === '已启用') return 'pill-hit'
  if (status === '已停用') return 'pill-off'
  return 'pill-wait'
}

async function loadBase() {
  const [sampleResp, catalogResp, ruleResp] = await Promise.all([
    deriveApi.samples(),
    deriveApi.catalog(),
    request('/api/filter?size=50'),
  ])
  samples.value = sampleResp.items
  catalog.value = catalogResp.fields
  rules.value = (await ruleResp.json()).items
  await Promise.all(
    rules.value.map(async (rule) => {
      try {
        conditions[rule.id] = await deriveApi.filterCondition(rule.id)
      } catch {
        // 没有结构化条件的规则保留空态
      }
    }),
  )
}

async function selectRule(ruleId: number) {
  selectedRuleId.value = ruleId
  latestRun.value = null
  conditionError.value = ''
  explVersion.value = undefined
  const condition = conditions[ruleId]
  conditionDraft.value = condition?.conditionText ?? ''
  await loadExplanations()
}

async function saveCondition() {
  if (!selectedRuleId.value) return
  conditionError.value = ''
  const response = await deriveApi.putFilterCondition(
    selectedRuleId.value,
    conditionDraft.value,
    {},
    conditionNote.value,
  )
  if (response.ok) {
    const payload = await response.json()
    conditions[selectedRuleId.value] = payload.condition
    conditionDraft.value = payload.condition.conditionText
    confirmTip.value = '条件已保存并升版本，旧版本证据继续保留'
    window.setTimeout(() => (confirmTip.value = ''), 2500)
    return
  }
  const error = await readError(response)
  if (response.status === 409 && error.ambiguities.length) {
    openAmbiguity(error.ambiguities, (identityMap) => saveConditionWith(identityMap))
  } else {
    conditionError.value = error.message
  }
}

async function saveConditionWith(identityMap: Record<string, string>) {
  if (!selectedRuleId.value) return
  const response = await deriveApi.putFilterCondition(
    selectedRuleId.value,
    conditionDraft.value,
    identityMap,
    conditionNote.value,
  )
  if (!response.ok) {
    const error = await readError(response)
    conditionError.value = error.message
    return
  }
  const payload = await response.json()
  conditions[selectedRuleId.value] = payload.condition
}

async function trial(objectId?: string) {
  if (!selectedRuleId.value) return
  conditionError.value = ''
  try {
    latestRun.value = await deriveApi.filterTrial(selectedRuleId.value, objectId)
  } catch (error) {
    conditionError.value = error instanceof Error ? error.message : '试算失败'
  }
}

async function confirmOne(result: RunResult) {
  if (!selectedRuleId.value || !latestRun.value) return
  const response = await deriveApi.filterConfirm(selectedRuleId.value, {
    runId: latestRun.value.runId,
    objectId: result.objectId,
  })
  const payload = await response.json()
  confirmTip.value = payload.message
  window.setTimeout(() => (confirmTip.value = ''), 2500)
  await loadExplanations()
}

async function confirmAll() {
  if (!selectedRuleId.value || !latestRun.value) return
  const response = await deriveApi.filterConfirm(selectedRuleId.value, {
    runId: latestRun.value.runId,
    all: true,
  })
  const payload = await response.json()
  confirmTip.value = `确认完成：新增 ${payload.created} 条，重复去重 ${payload.deduped} 条`
  window.setTimeout(() => (confirmTip.value = ''), 3000)
  await loadExplanations()
}

async function loadExplanations() {
  if (!selectedRuleId.value) {
    explanations.value = []
    return
  }
  const payload = await deriveApi.filterExplanations(selectedRuleId.value, explVersion.value)
  explanations.value = payload.items
}

async function runRuleAction(action: string, rule: FilterRow) {
  const response = await request(`/api/filter/${rule.id}/actions`, {
    method: 'POST',
    body: JSON.stringify({ values: { action } }),
  })
  if (response.ok) {
    const payload = await response.json()
    rule.status = payload.entry.status
  }
}

async function saveSample(objectId: string, values: Partial<SampleObject>) {
  await deriveApi.patchSample(objectId, values)
  const payload = await deriveApi.samples()
  samples.value = payload.items
}

async function resetSamples() {
  await deriveApi.resetSamples()
  samples.value = (await deriveApi.samples()).items
  latestRun.value = null
}

async function resetAll() {
  await deriveApi.resetAll()
  conditions && Object.keys(conditions).forEach((key) => delete conditions[Number(key)])
  await loadBase()
  selectedRuleId.value = null
  latestRun.value = null
  explanations.value = []
}

function openAmbiguity(items: Ambiguity[], retry: (identityMap: Record<string, string>) => Promise<void>) {
  ambiguity.items = items
  ambiguity.retry = retry
  ambiguity.visible = true
}

async function resolveAmbiguity(identityMap: Record<string, string>) {
  ambiguity.visible = false
  if (ambiguity.retry) {
    const retry = ambiguity.retry
    ambiguity.retry = null
    await retry(identityMap)
  }
}

function onJump(payload: { module: string; ruleId: number; version: number }) {
  // 跨模块跳转：筛选页内定位卡片；从标签页过来时已带 query
  highlightRuleId.value = payload.ruleId
  selectRule(payload.ruleId)
  const rule = rules.value.find((item) => item.id === payload.ruleId)
  if (rule) jumpHint.value = { ruleCode: rule.规则编号, version: payload.version }
}

onMounted(async () => {
  await loadBase()
  const jumpRuleId = Number(route.query.ruleId)
  const jumpVersion = Number(route.query.version)
  if (jumpRuleId && rules.value.some((item) => item.id === jumpRuleId)) {
    await selectRule(jumpRuleId)
    highlightRuleId.value = jumpRuleId
    const rule = rules.value.find((item) => item.id === jumpRuleId)
    jumpHint.value = { ruleCode: rule?.规则编号 ?? '', version: jumpVersion }
    router.replace({ query: {} })
  }
})
</script>
