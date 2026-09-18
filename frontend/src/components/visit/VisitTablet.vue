<template>
  <div class="two-pane card">
    <!-- 左栏：受试者 -->
    <div class="pane-subjects">
      <div class="pane-title">受试者（{{ subjects.length }}）</div>
      <div class="subj-scroll">
        <button
          v-for="s in subjects" :key="s.subject_id"
          :class="['subj-item', { active: selectedId === s.subject_id }]"
          @click="selectedId = s.subject_id"
        >
          <div class="si-top">
            <span class="si-name">{{ s.masked_name }}</span>
            <span v-if="s.mixed_versions" class="ver-badge">新旧并存</span>
          </div>
          <div class="si-code num-mono">{{ s.subject_code || s.screening_no }}</div>
          <el-progress :percentage="s.completion_percent" :stroke-width="5" />
          <div class="si-foot num-mono">{{ s.completion_percent }}% · {{ s.completion_label }}
            <span v-if="s.skipped_count" class="si-skip">· 跳过{{ s.skipped_count }}</span>
          </div>
        </button>
      </div>
    </div>

    <!-- 右栏：所选受试者在当前范围内的日程 -->
    <div class="pane-agenda">
      <template v-if="selected">
        <div class="agenda-head">
          <div>
            <div class="agenda-name">
              {{ selected.masked_name }}
              <span class="num-mono agenda-code">{{ selected.subject_code || selected.screening_no }}</span>
            </div>
            <div class="agenda-site">{{ selected.site_name }}</div>
          </div>
          <el-button size="small" text type="primary" @click="$emit('openSubject', selected.subject_id)">
            受试者链路 →
          </el-button>
        </div>

        <el-alert
          v-if="selected.mixed_versions"
          type="warning" :closable="false" show-icon class="agenda-alert"
          title="该受试者新旧方案并存：已完成/锁库访视冻结在旧版本，未发生访视已切换新版本（见各访视版本标记）。"
        />

        <div class="agenda-scroll">
          <div v-for="group in groups" :key="group.date" class="ag-day">
            <div :class="['ag-date', { today: group.date === today }]">
              {{ fmt(group.date) }}
              <span class="ag-dow">{{ dow(group.date) }}</span>
              <span v-if="group.date === today" class="ag-today">今天</span>
            </div>
            <div
              v-for="v in group.visits" :key="v.id"
              :class="['ag-item', v.visit_state, { skipped: v.status === 'skipped' }]"
              @click="$emit('open', v, selected)"
            >
              <div class="ag-bar" />
              <div class="ag-body">
                <div class="ag-line1">
                  <span class="ag-no">{{ v.visit_no }}</span>
                  <span class="ag-vname">{{ v.name }}</span>
                  <el-tag v-if="v.kind === 'unscheduled'" size="small" effect="plain" type="warning">计划外</el-tag>
                  <el-tag v-if="v.version !== selected.active_version" size="small" type="info" effect="plain">
                    旧版 {{ v.version }}
                  </el-tag>
                  <el-tag v-else size="small" type="success" effect="plain">{{ v.version }}</el-tag>
                  <el-icon v-if="v.locked" class="ag-lock"><Lock /></el-icon>
                </div>
                <div class="ag-line2">
                  <span :class="['visit-chip', v.visit_state]">{{ v.visit_state_label }}</span>
                  <span class="ag-win">窗：前{{ v.window_before }}/后{{ v.window_after }}天</span>
                  <span v-if="v.actual_date" class="num-mono">实际 {{ v.actual_date }}</span>
                  <span class="ag-forms num-mono">关键表单 {{ v.key_form_done }}/{{ v.key_form_total }}</span>
                </div>
              </div>
            </div>
          </div>
        </div>
      </template>
      <div v-else class="agenda-empty">
        <el-icon :size="30"><ArrowLeft /></el-icon>
        <div>请从左侧选择一名受试者查看日程</div>
      </div>
    </div>
  </div>
</template>

<script setup>
import { computed, ref, watch } from 'vue'
import { Lock, ArrowLeft } from '@element-plus/icons-vue'

const props = defineProps({
  subjects: { type: Array, default: () => [] },
  days: { type: Array, default: () => [] },
  today: { type: String, default: '' },
})
defineEmits(['open', 'openSubject'])

const selectedId = ref(null)
watch(
  () => props.subjects,
  (list) => {
    if (list.length && !list.some((s) => s.subject_id === selectedId.value)) {
      selectedId.value = list[0].subject_id
    }
    if (!list.length) selectedId.value = null
  },
  { immediate: true },
)

const selected = computed(() => props.subjects.find((s) => s.subject_id === selectedId.value) || null)

const inRange = computed(() => new Set(props.days.map((d) => d.date)))
const groups = computed(() => {
  if (!selected.value) return []
  const map = new Map()
  for (const v of selected.value.visits) {
    if (!inRange.value.has(v.planned_date)) continue
    if (!map.has(v.planned_date)) map.set(v.planned_date, [])
    map.get(v.planned_date).push(v)
  }
  return [...map.entries()]
    .sort((a, b) => (a[0] < b[0] ? -1 : 1))
    .map(([date, visits]) => ({
      date,
      visits: visits.sort((a, b) => a.order_index - b.order_index),
    }))
})

function fmt(iso) { return iso }
function dow(isoStr) {
  return '周' + ['日', '一', '二', '三', '四', '五', '六'][new Date(isoStr + 'T00:00:00').getDay()]
}
</script>

<style scoped>
.two-pane { display: grid; grid-template-columns: 280px 1fr; min-height: 520px; overflow: hidden; }
.pane-subjects { border-right: 1px solid var(--border); display: flex; flex-direction: column; }
.pane-title { padding: 12px 14px; font-weight: 600; font-size: 13px; border-bottom: 1px solid var(--border); }
.subj-scroll { overflow-y: auto; flex: 1; }
.subj-item {
  width: 100%; text-align: left; background: none; border: 0; border-bottom: 1px solid #f0f3f8;
  padding: 11px 14px; cursor: pointer; display: flex; flex-direction: column; gap: 4px;
}
.subj-item:hover { background: #f7f9fc; }
.subj-item.active { background: var(--brand-50); box-shadow: inset 3px 0 0 var(--brand-500); }
.si-top { display: flex; align-items: center; justify-content: space-between; gap: 6px; }
.si-name { font-weight: 600; font-size: 13px; }
.si-code { font-size: 11px; color: var(--ink-3); }
.si-foot { font-size: 11px; color: var(--ink-2); margin-top: 2px; }
.si-skip { color: var(--status-serious); }
.ver-badge {
  font-size: 10px; padding: 1px 6px; border-radius: 8px; font-weight: 600;
  background: #f3e9fb; color: #7d3aa8; border: 1px solid #dfc6f0;
}
.pane-agenda { display: flex; flex-direction: column; min-width: 0; }
.agenda-head { display: flex; justify-content: space-between; align-items: center; padding: 12px 16px; border-bottom: 1px solid var(--border); }
.agenda-name { font-weight: 700; font-size: 15px; }
.agenda-code { color: var(--ink-3); font-size: 12px; font-weight: 400; margin-left: 8px; }
.agenda-site { font-size: 12px; color: var(--ink-3); margin-top: 2px; }
.agenda-alert { margin: 12px 16px 0; }
.agenda-scroll { overflow-y: auto; padding: 10px 16px 18px; flex: 1; }
.ag-day { margin-bottom: 8px; }
.ag-date { font-size: 13px; font-weight: 600; padding: 8px 4px; color: var(--ink-2); display: flex; gap: 8px; align-items: center; }
.ag-date.today { color: var(--status-critical); }
.ag-dow { font-weight: 400; color: var(--ink-3); font-size: 12px; }
.ag-today { background: var(--status-critical); color: #fff; font-size: 10px; padding: 1px 6px; border-radius: 8px; }
.ag-item {
  display: flex; gap: 0; background: #fff; border: 1px solid var(--border);
  border-radius: 8px; margin-bottom: 8px; cursor: pointer; overflow: hidden;
}
.ag-item:hover { border-color: var(--brand-250); box-shadow: 0 1px 6px rgba(28,92,171,.10); }
.ag-bar { width: 4px; flex: none; background: var(--brand-400); }
.ag-item.done .ag-bar { background: var(--status-good); }
.ag-item.due_today .ag-bar, .ag-item.out_of_window .ag-bar { background: var(--status-critical); }
.ag-item.overdue .ag-bar { background: var(--status-serious); }
.ag-item.in_window .ag-bar { background: var(--status-warning); }
.ag-item.skipped { opacity: .62; }
.ag-item.skipped .ag-bar { background: #aaa; }
.ag-body { padding: 9px 12px; flex: 1; min-width: 0; }
.ag-line1 { display: flex; align-items: center; gap: 8px; flex-wrap: wrap; }
.ag-no { font-weight: 700; font-size: 13px; }
.ag-vname { font-size: 13px; color: var(--ink-1); }
.ag-lock { color: var(--ink-3); font-size: 14px; }
.ag-line2 { display: flex; align-items: center; gap: 12px; margin-top: 6px; font-size: 11px; color: var(--ink-3); flex-wrap: wrap; }
.agenda-empty { margin: auto; text-align: center; color: var(--ink-3); display: flex; flex-direction: column; gap: 10px; align-items: center; }
</style>
