<template>
  <div class="agenda">
    <div v-if="!groups.length" class="agenda-empty">
      <el-icon :size="34" color="#b6bfcc"><Calendar /></el-icon>
      <div class="ae-title">当前范围内没有可展示的访视安排</div>
      <div class="ae-desc">
        可调整上方的中心 / 状态筛选或时间范围；若受试者刚入组，访视将在排程生成后出现。
      </div>
    </div>

    <div v-for="g in groups" :key="g.key" class="ag-day">
      <div :class="['ag-day-head', { today: g.key === todayKey }]">
        <span class="ag-date">{{ g.label }}</span>
        <span v-if="g.key === todayKey" class="ag-today">今天</span>
        <span class="ag-count">{{ g.items.length }} 项</span>
      </div>
      <div v-for="item in g.items" :key="item.uid" class="ag-card-wrap">
        <router-link :to="`/visit-plans/subjects/${item.subject_id}`" class="ag-card">
          <div class="ag-top">
            <span :class="['visit-chip', item.visit_state]">● {{ item.visit_state_label }}</span>
            <span class="ag-no num-mono">{{ item.visit_no }}</span>
            <el-tag v-if="item.version_label" size="small" effect="plain" class="ag-ver">
              {{ item.version_label }}
            </el-tag>
            <el-icon v-if="item.locked" color="#b9851f" size="14"><Lock /></el-icon>
            <span v-if="item.kind === 'unscheduled'" class="ag-u">◆ 计划外</span>
          </div>
          <div class="ag-name">{{ item.name }}</div>
          <div class="ag-meta">
            {{ item.masked_name }} · {{ item.site_code }}
            <span v-if="item.actual_date"> · 实际 {{ item.actual_date }}</span>
          </div>
          <div class="ag-foot">
            <el-progress :percentage="item.completion.rate" :stroke-width="5"
                         :show-text="false" style="flex:1" />
            <span class="ag-pct num-mono">{{ item.completion.rate }}%</span>
            <span class="ag-forms num-mono">
              关键表单 {{ item.completion.key_done }}/{{ item.completion.key_total }}
            </span>
          </div>
          <div v-if="item.divergence_days !== 0" class="ag-diverge">
            随机化口径名义日 {{ item.nominal_date }}，与现行计划差 {{ item.divergence_days }} 天
          </div>
        </router-link>
        <div v-if="item.can_edit" class="ag-actions">
          <el-button size="small" text type="primary"
                     @click="$emit('reschedule', { visit: item, row: item })">改期</el-button>
          <el-button size="small" text type="warning"
                     @click="$emit('skip', { visit: item })">跳过</el-button>
        </div>
      </div>
    </div>
  </div>
</template>

<script setup>
import { computed } from 'vue'
import { Calendar, Lock } from '@element-plus/icons-vue'
import { parseDate, toKey } from '@/utils/date'

const props = defineProps({
  subjects: { type: Array, required: true },
  todayKey: { type: String, required: true },
  fromKey: { type: String, required: true },
  toKey: { type: String, required: true },
})
defineEmits(['reschedule', 'skip'])

const groups = computed(() => {
  const map = new Map()
  for (const row of props.subjects) {
    for (const v of row.visits) {
      if (v.planned_date < props.fromKey || v.planned_date > props.toKey) continue
      if (!map.has(v.planned_date)) map.set(v.planned_date, [])
      map.get(v.planned_date).push({ ...v, uid: v.id, subject_id: row.subject_id,
        masked_name: row.masked_name, site_code: row.site_code })
    }
  }
  return [...map.entries()]
    .sort((a, b) => (a[0] < b[0] ? -1 : 1))
    .map(([key, items]) => {
      const d = parseDate(key)
      const label = `${d.getMonth() + 1}月${d.getDate()}日 周${'日一二三四五六'[d.getDay()]}`
      return { key, label, items }
    })
})
</script>

<style scoped>
.agenda { display: flex; flex-direction: column; gap: 12px; }
.agenda-empty, .subject-empty {
  background: var(--surface-card); border: 1px dashed var(--border);
  border-radius: var(--radius); padding: 28px 20px; text-align: center;
}
.ae-title { font-weight: 600; margin: 10px 0 6px; }
.ae-desc { color: var(--ink-3); font-size: 13px; line-height: 1.7; }
.ag-day-head {
  display: flex; align-items: center; gap: 8px;
  font-weight: 600; font-size: 13px; color: var(--ink-2);
}
.ag-day-head.today .ag-date { color: var(--brand-700); font-size: 15px; }
.ag-today {
  background: var(--status-critical); color: #fff; font-size: 10px;
  padding: 1px 7px; border-radius: 9px;
}
.ag-count { color: var(--ink-3); font-weight: 400; font-size: 12px; }
.ag-card-wrap { position: relative; }
.ag-card {
  display: block; background: var(--surface-card); border: 1px solid var(--border);
  border-radius: var(--radius); padding: 10px 12px; margin-top: 8px;
  text-decoration: none; color: inherit; box-shadow: var(--shadow-card);
}
.ag-top { display: flex; align-items: center; gap: 7px; flex-wrap: wrap; }
.ag-no { font-weight: 700; font-size: 13px; }
.ag-ver { transform: scale(0.9); }
.ag-u { font-size: 11px; color: var(--brand-600); }
.ag-name { font-weight: 600; margin: 6px 0 2px; }
.ag-meta { font-size: 12px; color: var(--ink-3); }
.ag-foot { display: flex; align-items: center; gap: 8px; margin-top: 8px; }
.ag-pct { font-weight: 700; font-size: 12px; color: var(--brand-600); min-width: 42px; }
.ag-forms { font-size: 11px; color: var(--ink-3); }
.ag-diverge { font-size: 11px; color: #8a6d2a; margin-top: 6px; }
.ag-actions {
  position: absolute; right: 6px; bottom: 6px; display: flex;
}
</style>
