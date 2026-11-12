<template>
  <section class="sample-panel">
    <header class="panel-head">
      <h3>演示客户样本（可直接编辑）</h3>
      <div class="head-actions">
        <button class="btn" type="button" @click="$emit('reset')">恢复初始样本</button>
        <span class="panel-tip">改完字段后重新试算/重算，解释结果会随之变化</span>
      </div>
    </header>
    <div class="table-scroll">
      <table class="data-table sample-table">
        <thead>
          <tr>
            <th v-for="col in columns" :key="col.key">{{ col.label }}<span class="source-hint">{{ col.source }}</span></th>
            <th>操作</th>
          </tr>
        </thead>
        <tbody>
          <tr v-for="row in items" :key="row.客户编号">
            <td v-for="col in columns" :key="col.key">
              <!-- 主键与名称不允许清空，其余字段支持留空演示空值分支 -->
              <select v-if="col.kind === 'boolean'" v-model="drafts[row.客户编号][col.key]" class="cell-input">
                <option value="">空值</option>
                <option value="true">是</option>
                <option value="false">否</option>
              </select>
              <input
                v-else
                v-model="drafts[row.客户编号][col.key]"
                class="cell-input"
                :type="col.kind === 'number' ? 'number' : col.kind === 'date' ? 'date' : 'text'"
                :placeholder="col.key === '客户编号' || col.key === '客户名称' ? '' : '留空=空值'"
              />
            </td>
            <td>
              <button class="link" type="button" @click="$emit('save', row.客户编号, normalize(row.客户编号))">保存</button>
            </td>
          </tr>
        </tbody>
      </table>
    </div>
    <p v-if="savedTip" class="save-tip">{{ savedTip }}</p>
  </section>
</template>

<script setup lang="ts">
import { reactive, ref, watch } from 'vue'
import type { FieldCatalogItem, SampleObject } from './api'

const props = defineProps<{ items: SampleObject[]; catalog: FieldCatalogItem[] }>()
defineEmits<{
  (e: 'reset'): void
  (e: 'save', objectId: string, values: Partial<SampleObject>): void
}>()

const columns = props.catalog
const drafts = reactive<Record<string, Record<string, string>>>({})

function toCell(value: unknown): string {
  if (value === null || value === undefined) return ''
  if (value === true) return 'true'
  if (value === false) return 'false'
  return String(value)
}

function syncDrafts() {
  props.items.forEach((row) => {
    const bag: Record<string, string> = {}
    props.catalog.forEach((col) => {
      bag[col.key] = toCell((row as unknown as Record<string, unknown>)[col.key])
    })
    drafts[row.客户编号] = bag
  })
}

watch(() => props.items, syncDrafts, { immediate: true, deep: true })

const savedTip = ref('')
function normalize(objectId: string): Partial<SampleObject> {
  const bag = drafts[objectId]
  const values: Record<string, string | number | boolean | null> = {}
  props.catalog.forEach((col) => {
    const raw = bag[col.key]
    if (raw === '') {
      values[col.key] = null
    } else if (col.kind === 'number') {
      values[col.key] = Number(raw)
    } else if (col.kind === 'boolean') {
      values[col.key] = raw === 'true'
    } else {
      values[col.key] = raw
    }
  })
  savedTip.value = `已保存 ${objectId} 的字段修改，可重新计算查看解释变化`
  window.setTimeout(() => (savedTip.value = ''), 2500)
  return values as Partial<SampleObject>
}
</script>
