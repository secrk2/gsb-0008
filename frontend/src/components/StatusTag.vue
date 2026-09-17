<template>
  <span :class="['status-tag', status]">
    <span class="dot" />{{ label }}
  </span>
</template>

<script setup>
import { computed } from 'vue'

const props = defineProps({
  status: { type: String, required: true },
  labelMap: { type: Object, default: null },
})

const DEFAULT_LABELS = {
  screening: '筛选中',
  enrolled: '已入组',
  completed: '已完成',
  dropped: '脱落',
  terminated: '中止',
  screen_failed: '筛选失败',
  removed: '剔除',
}

const label = computed(() => props.labelMap?.[props.status] || DEFAULT_LABELS[props.status] || props.status)
</script>
