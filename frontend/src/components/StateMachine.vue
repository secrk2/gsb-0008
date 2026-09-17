<template>
  <div class="fsm">
    <div class="fsm-row">
      <div :class="['fsm-node', 'screening', { current: status === 'screening', past: isPast('screening') }]">
        筛选登记<small>分配筛选号</small>
      </div>
      <span class="fsm-arrow">→</span>
      <div :class="['fsm-node', 'enrolled', { current: status === 'enrolled', past: isPast('enrolled') }]">
        入组<small>分配受试者编号 · 姓名脱敏</small>
      </div>
      <span class="fsm-arrow">→</span>
      <div :class="['fsm-node', 'completed', { current: status === 'completed' }]">
        已完成<small>终态</small>
      </div>
    </div>
    <div class="fsm-branches">
      <div class="branch-col">
        <span class="branch-link">╲</span>
        <div :class="['fsm-node', 'screen_failed', { current: status === 'screen_failed' }]">
          筛选失败<small>终态 · 仅筛选中可转入</small>
        </div>
      </div>
      <div class="branch-col enrolled-branches">
        <span class="branch-link">↓ 入组后分支（均为终态，需填原因）</span>
        <div class="branch-row">
          <div :class="['fsm-node', 'dropped', { current: status === 'dropped' }]">脱落</div>
          <div :class="['fsm-node', 'terminated', { current: status === 'terminated' }]">中止</div>
          <div :class="['fsm-node', 'removed', { current: status === 'removed' }]">剔除</div>
        </div>
      </div>
    </div>
  </div>
</template>

<script setup>
import { computed } from 'vue'
const props = defineProps({ status: { type: String, required: true } })

// 已入组/完成/脱落/中止/剔除都意味着经过了筛选；完成意味着经过了入组
const passedScreening = ['enrolled', 'completed', 'dropped', 'terminated', 'removed']
const passedEnrolled = ['completed', 'dropped', 'terminated', 'removed']
function isPast(node) {
  if (node === 'screening') return passedScreening.includes(props.status)
  if (node === 'enrolled') return passedEnrolled.includes(props.status)
  return false
}
</script>

<style scoped>
.fsm { display: flex; flex-direction: column; gap: 14px; flex-wrap: wrap; }
.fsm-row { display: flex; align-items: center; gap: 8px; flex-wrap: wrap; }
.fsm-node {
  border: 1.5px solid var(--border); border-radius: 9px; padding: 9px 14px;
  background: #fafbfd; text-align: center; font-weight: 600; font-size: 13px;
  min-width: 108px; line-height: 1.35;
}
.fsm-node small { display: block; font-weight: 400; font-size: 11px; color: var(--ink-3); margin-top: 3px; }
.fsm-arrow { color: var(--ink-3); font-size: 18px; font-weight: 700; }
.fsm-node.past { opacity: .55; }
.fsm-node.current {
  border-color: var(--brand-500); background: var(--brand-50);
  color: var(--brand-700); box-shadow: 0 0 0 3px rgba(28,92,171,.14);
}
.fsm-node.screening.current { border-color: #3987e5; }
.fsm-node.completed.current { border-color: var(--status-good); background: var(--status-good-bg); color: #0b6b2c; }
.fsm-node.screen_failed.current { border-color: #999; background: #f1f1f1; }
.fsm-node.dropped.current { border-color: var(--status-serious); background: var(--status-serious-bg); color: #9c451f; }
.fsm-node.terminated.current { border-color: #8e44ad; background: #f3e9fb; color: #6d3296; }
.fsm-node.removed.current { border-color: var(--status-critical); background: var(--status-critical-bg); color: #a52020; }

.fsm-branches { display: flex; gap: 26px; flex-wrap: wrap; padding-left: 20px; }
.branch-col { display: flex; flex-direction: column; align-items: center; gap: 4px; }
.enrolled-branches { align-items: flex-start; gap: 6px; }
.branch-link { color: var(--ink-3); font-size: 12px; }
.branch-row { display: flex; gap: 10px; flex-wrap: wrap; }

@media (max-width: 640px) {
  .fsm-node { min-width: 92px; padding: 8px 10px; font-size: 12px; }
  .fsm-branches { padding-left: 4px; gap: 14px; }
}
</style>
