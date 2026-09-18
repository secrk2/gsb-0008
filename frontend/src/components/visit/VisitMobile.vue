<template>
  <div class="phone-list">
    <div v-for="group in groups" :key="group.date" class="pl-day">
      <div :class="['pl-date', { today: group.date === today }]">
        {{ group.date }}
        <span class="pl-dow">{{ dow(group.date) }}</span>
        <span v-if="group.date === today" class="pl-today">今天</span>
      </div>
      <div
        v-for="item in group.items" :key="`${item.subject.subject_id}-${item.visit.id}`"
        class="pl-card card"
        @click="$emit('open', item.visit, item.subject)"
      >
        <div class="pl-top">
          <span class="pl-mask">{{ item.subject.masked_name }}</span>
          <span :class="['visit-chip', item.visit.visit_state]">{{ item.visit.visit_state_label }}</span>
        </div>
        <div class="pl-mid">
          <span class="pl-no">{{ item.visit.visit_no }}</span>
          <span class="pl-vname">{{ item.visit.name }}</span>
        </div>
        <div class="pl-tags">
          <el-tag v-if="item.visit.kind === 'unscheduled'" size="small" type="warning" effect="plain">计划外</el-tag>
          <el-tag v-if="item.visit.version !== item.subject.active_version" size="small" type="info" effect="plain">
            旧版 {{ item.visit.version }}
          </el-tag>
          <el-tag v-else size="small" type="success" effect="plain">{{ item.visit.version }}</el-tag>
          <el-tag v-if="item.visit.locked" size="small" type="danger" effect="plain">
            <el-icon style="vertical-align:-2px"><Lock /></el-icon> 锁库
          </el-tag>
          <el-tag v-if="item.subject.mixed_versions" size="small" type="warning" effect="plain">新旧并存</el-tag>
        </div>
        <div class="pl-foot num-mono">
          <span>{{ item.subject.subject_code || item.subject.screening_no }}</span>
          <span>窗前{{ item.visit.window_before }}/后{{ item.visit.window_after }}</span>
          <span>表单 {{ item.visit.key_form_done }}/{{ item.visit.key_form_total }}</span>
        </div>
      </div>
    </div>
    <div v-if="!groups.length" class="pl-no-range">
      当前时间范围内没有访视，请切换月/周或翻页查看。
    </div>
  </div>
</template>

<script setup>
import { computed } from 'vue'
import { Lock } from '@element-plus/icons-vue'

const props = defineProps({
  subjects: { type: Array, default: () => [] },
  days: { type: Array, default: () => [] },
  today: { type: String, default: '' },
})
defineEmits(['open'])

const inRange = computed(() => new Set(props.days.map((d) => d.date)))
const groups = computed(() => {
  const map = new Map()
  for (const s of props.subjects) {
    for (const v of s.visits) {
      if (v.status === 'skipped') continue
      if (!inRange.value.has(v.planned_date)) continue
      if (!map.has(v.planned_date)) map.set(v.planned_date, [])
      map.get(v.planned_date).push({ subject: s, visit: v })
    }
  }
  return [...map.entries()]
    .sort((a, b) => (a[0] < b[0] ? -1 : 1))
    .map(([date, items]) => ({
      date,
      items: items.sort((a, b) =>
        a.subject.subject_id === b.subject.subject_id
          ? a.visit.order_index - b.visit.order_index
          : String(a.subject.subject_code).localeCompare(String(b.subject.subject_code))
      ),
    }))
})
function dow(isoStr) {
  return '周' + ['日', '一', '二', '三', '四', '五', '六'][new Date(isoStr + 'T00:00:00').getDay()]
}
</script>

<style scoped>
.phone-list { display: flex; flex-direction: column; gap: 14px; }
.pl-date { font-size: 13px; font-weight: 700; color: var(--ink-2); display: flex; gap: 8px; align-items: center; }
.pl-date.today { color: var(--status-critical); }
.pl-dow { font-weight: 400; color: var(--ink-3); font-size: 12px; }
.pl-today { background: var(--status-critical); color: #fff; font-size: 10px; padding: 1px 6px; border-radius: 8px; }
.pl-card { padding: 11px 13px; display: flex; flex-direction: column; gap: 7px; }
.pl-top { display: flex; justify-content: space-between; align-items: center; gap: 8px; }
.pl-mask { font-weight: 600; font-size: 14px; }
.pl-mid { display: flex; gap: 8px; align-items: baseline; }
.pl-no { font-weight: 700; color: var(--brand-600); }
.pl-vname { font-size: 13px; }
.pl-tags { display: flex; flex-wrap: wrap; gap: 5px; }
.pl-foot { display: flex; justify-content: space-between; font-size: 11px; color: var(--ink-3); }
.pl-no-range { color: var(--ink-3); font-size: 13px; text-align: center; padding: 30px 0; }
</style>
