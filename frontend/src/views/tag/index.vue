<template>
  <section class="page derive-page" data-module="tag">
    <header class="page-head">
      <div>
        <h2>数据标签 · 推导解释</h2>
        <p class="page-desc">
          分步说明标签计算经过哪些环节：参与字段、空值分支、规则引用快照与覆盖对象。
          同名字段以已确认身份为准；规则停用或修订后，旧标签解释仍保留当时证据。
        </p>
      </div>
      <div class="page-actions">
        <button class="btn" type="button" @click="resetAll">重置全部演示数据</button>
      </div>
    </header>

    <SamplePanel :items="samples" :catalog="catalog" @reset="resetSamples" @save="saveSample" />

    <section class="work-panel">
      <header class="panel-head">
        <h3>标签定义</h3>
        <span class="panel-tip">选择标签查看推导；历史标签没有计算证据时会明确提示「旧证据缺失」</span>
      </header>
      <div class="rule-grid">
        <article
          v-for="tag in tags"
          :key="tag.id"
          class="rule-card"
          :class="{ active: selectedTagId === tag.id }"
        >
          <div class="rule-card-head">
            <strong>{{ tag.标签编号 }} · {{ tag.标签名称 }}</strong>
            <span class="state-pill" :class="statusClass(tag.status)">{{ tag.status }}</span>
          </div>
          <p class="rule-cond">{{ tag.计算表达式 }}</p>
          <p class="rule-meta">覆盖对象：{{ tag.覆盖对象 }} · 更新频率：{{ tag.更新频率 }}</p>
          <div class="rule-card-actions">
            <button class="btn primary" type="button" @click="selectTag(tag.id)">查看推导</button>
            <button
              v-for="action in tagActions"
              :key="action"
              class="link"
              type="button"
              @click="runTagAction(action, tag)"
            >
              {{ action }}
            </button>
          </div>
        </article>
      </div>
    </section>

    <template v-if="selectedTag">
      <!-- 旧证据缺失：历史标签没有保存过计算过程 -->
      <section v-if="board?.legacy" class="work-panel legacy-panel">
        <header class="panel-head"><h3>解释卡</h3></header>
        <div class="legacy-banner">
          <strong>旧证据缺失</strong>
          <p>{{ board.message }}</p>
        </div>
        <div class="expr-editor">
          <label class="expr-input-wrap">
            <span>为历史标签登记计算表达式</span>
            <textarea v-model="legacyDraft" rows="3" class="expr-input" />
          </label>
          <div class="expr-side">
            <div class="expr-btns">
              <button class="btn primary" type="button" @click="bootstrapLegacy()">登记并首次重算</button>
            </div>
            <p v-if="legacyError" class="error-text">{{ legacyError }}</p>
          </div>
        </div>
      </section>

      <template v-else>
        <section class="work-panel">
          <header class="panel-head">
            <h3>{{ selectedTag.标签编号 }} · 表达式版本</h3>
            <span class="panel-tip">每次修订生成新版本；两个版本同时重算各自留痕，互不覆盖</span>
          </header>

          <div v-if="board" class="version-list">
            <article
              v-for="ver in board.versions"
              :key="ver.version"
              class="version-card"
              :class="{ current: ver.version === board.currentVersion }"
            >
              <div class="rule-card-head">
                <span class="version-tag">v{{ ver.version }}</span>
                <span v-if="ver.version === board.currentVersion" class="state-pill pill-wait">当前版本</span>
              </div>
              <p class="rule-cond">{{ ver.expression }}</p>
              <p class="rev-meta">{{ ver.createdAt }} · {{ ver.note }}</p>
              <p v-if="Object.keys(ver.identityMap).length" class="identity-line">
                已确认身份：
                <span v-for="(key, label) in ver.identityMap" :key="label" class="identity-chip">{{ label }} → {{ key }}</span>
              </p>
              <div class="rule-card-actions">
                <button class="btn primary" type="button" @click="recompute(ver.version)">按此版本重算</button>
              </div>
            </article>
          </div>

          <div class="expr-editor new-version">
            <label class="expr-input-wrap">
              <span>登记新版本表达式</span>
              <textarea v-model="newExpression" rows="3" class="expr-input" />
            </label>
            <div class="expr-side">
              <label>
                <span>修订说明</span>
                <input v-model="newNote" class="cell-input" placeholder="例如：改用风控等级" />
              </label>
              <div class="expr-btns">
                <button class="btn primary" type="button" @click="createVersion()">保存新版本</button>
                <button class="btn" type="button" @click="recompute()">重算当前版本（全部样本）</button>
              </div>
            </div>
          </div>
          <p v-if="actionError" class="error-text">{{ actionError }}</p>
        </section>

        <section class="work-panel">
          <header class="panel-head">
            <h3>本次重算结果</h3>
            <div v-if="latestRun" class="head-actions">
              <span class="panel-tip">
                运行 {{ latestRun.runId }} · v{{ latestRun.version }} · 覆盖 {{ latestRun.coverageCount }}/{{ latestRun.totalCount }}
              </span>
              <button class="btn primary" type="button" @click="confirmAll">全部确认解释</button>
            </div>
          </header>
          <div v-if="!latestRun" class="empty-block">尚未重算，点击「重算」查看每个覆盖对象的分步推导</div>
          <div v-else class="result-list">
            <article v-for="result in latestRun.results" :key="result.objectId" class="result-card" :class="result.hit ? 'card-hit' : 'card-miss'">
              <header class="expl-head">
                <div class="expl-title">
                  <span class="state-pill" :class="result.hit ? 'pill-hit' : 'pill-miss'">
                    {{ result.hit ? '命中' : '本次未命中' }}
                  </span>
                  <strong>{{ result.objectLabel }}（{{ result.objectId }}）</strong>
                </div>
                <button class="btn" type="button" @click="recompute(undefined, result.objectId)">只算该对象</button>
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
            <h3>解释卡（已确认的有效解释）</h3>
            <label class="version-filter">
              按版本筛选：
              <select v-model.number="boardVersion" @change="loadBoard">
                <option :value="undefined">全部版本</option>
                <option v-for="ver in board?.versions ?? []" :key="ver.version" :value="ver.version">v{{ ver.version }}</option>
              </select>
            </label>
          </header>
          <div v-if="!board?.explanations.length" class="empty-block">
            暂无确认解释。注意「本次未命中」与「旧证据缺失」不同：前者有完整推导、只是条件不成立。
          </div>
          <ExplanationCard
            v-for="item in board?.explanations ?? []"
            :key="item.explId"
            :explanation="item"
            @jump="onJump"
          />
        </section>
      </template>
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
import { useRouter } from 'vue-router'
import { request } from '@/api/client'
import AmbiguityDialog from '@/views/derive/AmbiguityDialog.vue'
import ExplanationCard from '@/views/derive/ExplanationCard.vue'
import SamplePanel from '@/views/derive/SamplePanel.vue'
import TraceTree from '@/views/derive/TraceTree.vue'
import {
  deriveApi,
  readError,
  type Ambiguity,
  type FieldCatalogItem,
  type RunPayload,
  type RunResult,
  type SampleObject,
  type TagBoard,
} from '@/views/derive/api'

interface TagRow {
  id: number
  status: string
  标签编号: string
  标签名称: string
  计算表达式: string
  覆盖对象: string
  更新频率: string
}

const router = useRouter()
const tagActions = ['提交校验', '启用标签', '停用标签']

const samples = ref<SampleObject[]>([])
const catalog = ref<FieldCatalogItem[]>([])
const tags = ref<TagRow[]>([])
const selectedTagId = ref<number | null>(null)
const board = ref<TagBoard | null>(null)
const boardVersion = ref<number | undefined>(undefined)
const latestRun = ref<RunPayload | null>(null)
const newExpression = ref('')
const newNote = ref('登记新版本')
const legacyDraft = ref('')
const legacyError = ref('')
const actionError = ref('')
const confirmTip = ref('')
const ambiguity = reactive<{
  visible: boolean
  items: Ambiguity[]
  retry: null | ((identityMap: Record<string, string>) => Promise<void>)
}>({ visible: false, items: [], retry: null })

const selectedTag = computed(() => tags.value.find((item) => item.id === selectedTagId.value) ?? null)

function statusClass(status: string): string {
  if (status === '已启用') return 'pill-hit'
  if (status === '已停用') return 'pill-off'
  return 'pill-wait'
}

async function loadBase() {
  const [sampleResp, catalogResp, tagResp] = await Promise.all([
    deriveApi.samples(),
    deriveApi.catalog(),
    request('/api/tag?size=50'),
  ])
  samples.value = sampleResp.items
  catalog.value = catalogResp.fields
  tags.value = (await tagResp.json()).items
}

async function selectTag(tagId: number) {
  selectedTagId.value = tagId
  latestRun.value = null
  boardVersion.value = undefined
  actionError.value = ''
  await loadBoard()
  const versions = board.value?.versions ?? []
  newExpression.value = versions.length ? versions[versions.length - 1].expression : ''
}

async function loadBoard() {
  if (!selectedTagId.value) return
  board.value = await deriveApi.tagBoard(selectedTagId.value, boardVersion.value)
}

async function recompute(version?: number, objectId?: string, identityMap: Record<string, string> = {}) {
  if (!selectedTagId.value) return
  actionError.value = ''
  const response = await deriveApi.recompute(selectedTagId.value, { version, objectId, identityMap })
  if (response.ok) {
    latestRun.value = await response.json()
    return
  }
  const error = await readError(response)
  if (response.status === 409 && error.ambiguities.length) {
    openAmbiguity(error.ambiguities, (map) => recompute(version, objectId, map))
  } else {
    actionError.value = error.message
  }
}

async function createVersion(identityMap: Record<string, string> = {}) {
  if (!selectedTagId.value) return
  actionError.value = ''
  const response = await deriveApi.createTagVersion(
    selectedTagId.value,
    newExpression.value,
    identityMap,
    newNote.value,
  )
  if (response.ok) {
    await loadBoard()
    confirmTip.value = '新版本已登记，旧版本解释不受影响'
    window.setTimeout(() => (confirmTip.value = ''), 2500)
    await recompute()
    return
  }
  const error = await readError(response)
  if (response.status === 409 && error.ambiguities.length) {
    openAmbiguity(error.ambiguities, (map) => createVersion(map))
  } else {
    actionError.value = error.message
  }
}

async function bootstrapLegacy(identityMap: Record<string, string> = {}) {
  if (!selectedTagId.value) return
  legacyError.value = ''
  const response = await deriveApi.createTagVersion(
    selectedTagId.value,
    legacyDraft.value,
    identityMap,
    '历史标签补录证据',
  )
  if (response.ok) {
    await selectTag(selectedTagId.value)
    await recompute()
    return
  }
  const error = await readError(response)
  if (response.status === 409 && error.ambiguities.length) {
    openAmbiguity(error.ambiguities, (map) => bootstrapLegacy(map))
  } else {
    legacyError.value = error.message
  }
}

async function confirmOne(result: RunResult) {
  if (!selectedTagId.value || !latestRun.value) return
  const response = await deriveApi.tagConfirm(selectedTagId.value, {
    runId: latestRun.value.runId,
    objectId: result.objectId,
  })
  const payload = await response.json()
  confirmTip.value = payload.message
  window.setTimeout(() => (confirmTip.value = ''), 2500)
  await loadBoard()
}

async function confirmAll() {
  if (!selectedTagId.value || !latestRun.value) return
  const response = await deriveApi.tagConfirm(selectedTagId.value, {
    runId: latestRun.value.runId,
    all: true,
  })
  const payload = await response.json()
  confirmTip.value = `确认完成：新增 ${payload.created} 条，重复去重 ${payload.deduped} 条`
  window.setTimeout(() => (confirmTip.value = ''), 3000)
  await loadBoard()
}

async function runTagAction(action: string, tag: TagRow) {
  const response = await request(`/api/tag/${tag.id}/actions`, {
    method: 'POST',
    body: JSON.stringify({ values: { action } }),
  })
  if (response.ok) {
    const payload = await response.json()
    tag.status = payload.entry.status
  }
}

async function saveSample(objectId: string, values: Partial<SampleObject>) {
  await deriveApi.patchSample(objectId, values)
  samples.value = (await deriveApi.samples()).items
}

async function resetSamples() {
  await deriveApi.resetSamples()
  samples.value = (await deriveApi.samples()).items
  latestRun.value = null
}

async function resetAll() {
  await deriveApi.resetAll()
  await loadBase()
  selectedTagId.value = null
  board.value = null
  latestRun.value = null
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
  // 跨模块跳到数据筛选实际采用的条件，并带上引用版本用于高亮
  router.push({
    path: '/filter',
    query: { ruleId: String(payload.ruleId), version: String(payload.version) },
  })
}

onMounted(loadBase)
</script>
