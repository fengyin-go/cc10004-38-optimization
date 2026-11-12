<template>
  <div v-if="visible" class="modal-mask" @click.self="$emit('close')">
    <div class="modal-card">
      <header class="modal-head">
        <h3>同名字段身份确认</h3>
        <button class="btn ghost" type="button" @click="$emit('close')">关闭</button>
      </header>
      <p class="modal-desc">
        表达式中存在同名字段，系统无法判断指向哪个来源。请逐项确认身份；确认结果绑定到当前版本，
        之后重算以已确认身份为准，两个版本的确认互不覆盖。
      </p>

      <div v-for="item in ambiguities" :key="item.field" class="ambiguity-block">
        <p class="ambiguity-field">字段「{{ item.field }}」存在 {{ item.candidates.length }} 个同名字段：</p>
        <label v-for="candidate in item.candidates" :key="candidate.key" class="candidate-item">
          <input
            type="radio"
            :name="item.field"
            :value="candidate.key"
            v-model="picked[item.field]"
          />
          <span>
            <strong>{{ candidate.label }}</strong>
            <em>（来源：{{ candidate.source }}，存储字段：{{ candidate.key }}，类型：{{ candidate.kind }}）</em>
          </span>
        </label>
      </div>

      <footer class="modal-foot">
        <button class="btn" type="button" @click="$emit('close')">取消</button>
        <button class="btn primary" type="button" :disabled="!allPicked" @click="$emit('confirm', { ...picked })">
          确认身份并重新计算
        </button>
      </footer>
    </div>
  </div>
</template>

<script setup lang="ts">
import { computed, reactive, watch } from 'vue'
import type { Ambiguity } from './api'

const props = defineProps<{ visible: boolean; ambiguities: Ambiguity[] }>()
defineEmits<{
  (e: 'close'): void
  (e: 'confirm', identityMap: Record<string, string>): void
}>()

const picked = reactive<Record<string, string>>({})

watch(
  () => props.visible,
  (visible) => {
    if (visible) {
      Object.keys(picked).forEach((key) => delete picked[key])
      props.ambiguities.forEach((item) => {
        if (item.candidates.length === 1) picked[item.field] = item.candidates[0].key
      })
    }
  },
)

const allPicked = computed(() => props.ambiguities.every((item) => Boolean(picked[item.field])))
</script>
