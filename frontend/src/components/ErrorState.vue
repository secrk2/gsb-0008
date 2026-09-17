<template>
  <div class="state-block card">
    <div :class="['state-icon', type]">
      <el-icon><component :is="icon" /></el-icon>
    </div>
    <div class="state-title">{{ title }}</div>
    <div class="state-desc">{{ message }}</div>
    <div v-if="$slots.default" style="margin-top: 8px"><slot /></div>
  </div>
</template>

<script setup>
import { WarningFilled, Warning, Box } from '@element-plus/icons-vue'
const props = defineProps({
  type: { type: String, default: 'empty' }, // forbidden | warn | empty
  title: { type: String, default: '' },
  message: { type: String, default: '' },
})
const icon = props.type === 'forbidden' ? WarningFilled : props.type === 'warn' ? Warning : Box
</script>
