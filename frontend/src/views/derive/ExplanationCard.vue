<template>
  <article class="expl-card" :class="cardClass">
    <header class="expl-head">
      <div class="expl-title">
        <span class="state-pill" :class="stateClass">{{ stateText }}</span>
        <strong>{{ explanation.objectLabel }}（{{ explanation.objectId }}）</strong>
        <span class="version-tag">v{{ explanation.version }}</span>
      </div>
      <div class="expl-meta">
        <span>解释编号：{{ explanation.explId }}</span>
        <span>确认人：{{ explanation.confirmedBy }}</span>
        <span>{{ explanation.confirmedAt }}</span>
      </div>
    </header>

    <!-- 规则证据过期提示：停用/修订后旧解释仍保留当时证据 -->
    <div v-for="(note, idx) in explanation.staleNotes" :key="idx" class="stale-banner" :class="{ fresh: !note.stale }">
      <span>{{ note.stale ? '⏳' : '✓' }} {{ note.ruleCode }}：{{ note.reason }}</span>
      <button class="link jump-btn" type="button" @click="$emit('jump', note.jump)">在数据筛选中查看该条件 →</button>
    </div>

    <TraceTree :node="explanation.trace" @jump="(payload) => $emit('jump', payload)" />
  </article>
</template>

<script setup lang="ts">
import { computed } from 'vue'
import TraceTree from './TraceTree.vue'
import type { Explanation } from './api'

const props = defineProps<{ explanation: Explanation }>()
defineEmits<{ (e: 'jump', payload: { module: string; ruleId: number; version: number }): void }>()

const stateText = computed(() => (props.explanation.hit ? '命中' : '本次未命中'))
const stateClass = computed(() => (props.explanation.hit ? 'pill-hit' : 'pill-miss'))
const cardClass = computed(() => (props.explanation.hit ? 'card-hit' : 'card-miss'))
</script>
