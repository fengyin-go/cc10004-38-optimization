<template>
  <div class="trace-tree" :class="{ 'trace-root': depth === 0 }">
    <div class="trace-line" :class="lineClass">
      <span class="trace-badge">{{ badge }}</span>
      <div class="trace-body">
        <p class="trace-text">{{ node.text }}</p>

        <!-- 字段取值明细：参与字段、实际值、空值分支 -->
        <div v-if="node.field" class="field-chip" :class="{ null: node.field.isNull }">
          <span class="chip-label">参与字段</span>
          <span>{{ node.field.label }}（{{ node.field.source }}）</span>
          <span class="chip-value">
            取值：<strong>{{ node.field.isNull ? '空值' : displayValue(node.field.value) }}</strong>
          </span>
          <span v-if="node.expected !== undefined && node.expected !== null" class="chip-value">
            比较值：{{ displayValue(node.expected) }}
          </span>
        </div>
        <p v-if="node.valueNote" class="null-note">⚠ {{ node.valueNote }}</p>

        <!-- 规则引用：证据快照 + 跨模块跳转 -->
        <div v-if="node.kind === 'rule' && !node.ruleMissing" class="rule-chip">
          <div class="rule-chip-head">
            <span class="chip-label">规则证据快照</span>
            <span>{{ node.snapshot?.ruleCode }} · v{{ node.snapshot?.version }} · 引用时状态：{{ node.snapshot?.status }}</span>
            <button class="link jump-btn" type="button" @click="jump(node)">跳转到数据筛选条件 →</button>
          </div>
          <p class="rule-cond">条件：{{ node.snapshot?.conditionText }}</p>
          <p v-if="node.statusNote" class="stale-note">⏳ {{ node.statusNote }}</p>
        </div>
        <div v-else-if="node.ruleMissing" class="rule-chip missing">
          <p class="stale-note">⚠ {{ node.text }}</p>
        </div>
      </div>
    </div>

    <div v-if="node.steps?.length" class="trace-children">
      <TraceTree v-for="(child, idx) in node.steps" :key="idx" :node="child" :depth="depth + 1" @jump="onJump" />
    </div>
  </div>
</template>

<script setup lang="ts">
import { computed } from 'vue'
import type { TraceNode } from './api'

const props = defineProps<{ node: TraceNode; depth?: number }>()
const emit = defineEmits<{ (e: 'jump', payload: NonNullable<TraceNode['jump']>): void }>()

const depth = props.depth ?? 0

const lineClass = computed(() => ({
  'is-hit': props.node.hit,
  'is-miss': !props.node.hit,
  'is-rule': props.node.kind === 'rule',
  'is-logic': props.node.kind === 'logic',
}))

const badge = computed(() => {
  if (props.node.kind === 'logic') return props.node.op
  if (props.node.kind === 'rule') return '规则'
  return props.node.hit ? '命中' : '未命中'
})

function displayValue(value: unknown): string {
  if (value === null || value === undefined || value === '') return '空值'
  if (value === true) return '是'
  if (value === false) return '否'
  return String(value)
}

function jump(node: TraceNode) {
  if (node.jump) emit('jump', node.jump)
}

function onJump(payload: NonNullable<TraceNode['jump']>) {
  emit('jump', payload)
}
</script>
