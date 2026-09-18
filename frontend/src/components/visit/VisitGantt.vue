<template>
  <div class="gantt-wrap card">
    <div class="gantt-scroll">
      <div class="gantt" :style="ganttStyle">
        <!-- 表头：受试者角 -->
        <div class="gantt-corner">
          受试者 / 完成度
          <span class="col-hint">{{ view === 'month' ? '月视图' : '周视图' }} · 拖拽访视条可改期</span>
        </div>
        <div
          v-for="day in days" :key="day.date"
          :class="['gantt-day-head', { mute: !day.in_range, today: day.date === today }]"
        >
          <span class="dow">{{ dow(day.date) }}</span>
          <span class="dom">{{ Number(day.date.slice(8)) }}</span>
          <span v-if="day.date === today" class="today-flag">今</span>
        </div>

        <!-- 每个受试者一行 -->
        <template v-for="s in subjects" :key="s.subject_id">
          <div class="gantt-row-head">
            <div class="gh-name">
              <span class="gh-mask">{{ s.masked_name }}</span>
              <span
                v-if="s.mixed_versions"
                class="ver-badge mixed"
                title="该受试者同时存在新旧两个方案版本"
              >新旧方案并存</span>
            </div>
            <div class="gh-code num-mono">{{ s.subject_code || s.screening_no }} · {{ s.site_name }}</div>
            <div class="gh-prog">
              <el-progress :percentage="s.completion_percent" :stroke-width="6" :show-text="false" />
              <span class="gh-pct num-mono">{{ s.completion_percent }}%（{{ s.completion_label }}）</span>
            </div>
            <div v-if="s.skipped_count" class="gh-skip">已跳过 {{ s.skipped_count }}</div>
          </div>

          <!-- 轨道 + 今日列 -->
          <div
            class="gantt-track"
            :style="{ gridColumn: `2 / span ${days.length}` }"
          >
            <div class="track-lane" />
            <div
              v-for="(day, di) in days" :key="day.date"
              :class="['drop-cell', { today: day.date === today, mute: !day.in_range }]"
              :style="{ left: `calc(${di} * var(--day-col))`, width: 'var(--day-col)' }"
              @dragover.prevent="onDragOver($event, day.date)"
              @dragleave="hoverDate = ''"
              @drop.prevent="onDrop($event, day.date)"
            />
            <div
              v-if="todayCol >= 0"
              class="today-line"
              :style="{ left: `calc(${todayCol} * var(--day-col) + var(--day-col) / 2)` }"
            />

            <!-- 访视条 -->
            <template v-for="b in barsFor(s)" :key="b.visit.id">
              <div
                :class="[
                  'vbar', b.visit.visit_state,
                  { locked: b.visit.locked, unscheduled: b.visit.kind === 'unscheduled',
                    skipped: b.visit.status === 'skipped', oldver: b.visit.version !== s.active_version },
                ]"
                :style="{ left: barLeft(b), width: 'var(--day-col)' }"
                :draggable="b.visit.can_edit && b.visit.status !== 'done' && b.visit.status !== 'skipped'"
                @dragstart="onDragStart($event, b.visit, s)"
                @dragend="hoverDate = ''"
                @click="$emit('open', b.visit, s)"
                :title="barTitle(b.visit, s)"
              >
                <span class="vbar-no">{{ b.visit.visit_no }}</span>
                <el-icon v-if="b.visit.locked" class="vbar-lock"><Lock /></el-icon>
                <span class="vbar-win" :style="winStyle(b)" />
              </div>
            </template>
          </div>
        </template>
      </div>
    </div>

    <!-- 图例 -->
    <div class="gantt-legend">
      <span><i class="lg scheduled" />未到窗</span>
      <span><i class="lg in_window" />窗内</span>
      <span><i class="lg due_today" />今日</span>
      <span><i class="lg overdue" />逾期</span>
      <span><i class="lg out_of_window" />超窗</span>
      <span><i class="lg done" />已完成</span>
      <span><i class="lg skipped" />已跳过</span>
      <span><i class="lg unscheduled" />计划外</span>
      <span><i class="lg oldver" />旧版冻结</span>
      <span><el-icon><Lock /></el-icon> 锁库</span>
      <span class="legend-hint">半透明条体=随访窗范围；旧版访视冻结原样，不可拖动</span>
    </div>
  </div>
</template>

<script setup>
import { computed, ref } from 'vue'
import { Lock } from '@element-plus/icons-vue'

const props = defineProps({
  subjects: { type: Array, default: () => [] },
  days: { type: Array, default: () => [] },
  today: { type: String, default: '' },
  view: { type: String, default: 'month' },
})
const emit = defineEmits(['open', 'reschedule'])

const hoverDate = ref('')
let dragging = null

function dow(isoStr) {
  return ['日', '一', '二', '三', '四', '五', '六'][new Date(isoStr + 'T00:00:00').getDay()]
}

const indexByDate = computed(() => {
  const m = new Map()
  props.days.forEach((d, i) => m.set(d.date, i))
  return m
})

const todayCol = computed(() => indexByDate.value.get(props.today) ?? -1)

const ganttStyle = computed(() => {
  const col = props.view === 'week' ? '64px' : '30px'
  return {
    gridTemplateColumns: `220px repeat(${props.days.length}, ${col})`,
    '--day-col': col,
  }
})

function barsFor(s) {
  const out = []
  const laneByDate = new Map()
  for (const visit of [...s.visits].sort((a, b) => a.order_index - b.order_index)) {
    const idx = indexByDate.value.get(visit.planned_date)
    if (idx === undefined) continue
    const lane = laneByDate.get(visit.planned_date) || 0
    laneByDate.set(visit.planned_date, lane + 1)
    out.push({ visit, idx, lane })
  }
  return out
}
function barLeft(b) {
  return `calc(${b.idx} * var(--day-col))`
}
function barTitle(v, s) {
  return `${s.subject_code || s.screening_no} · ${v.visit_no} ${v.name}\n计划 ${v.planned_date}（前${v.window_before}/后${v.window_after}天）\n${v.visit_state_label} · ${v.version}${v.locked ? ' · 已锁库' : ''}`
}
function winStyle(b) {
  // 窗期色带：左伸 window_before（不越过轨道起点），宽度覆盖 前+当天+后
  const wb = Math.min(b.visit.window_before, b.idx)
  return {
    left: `calc(-${wb} * var(--day-col))`,
    width: `calc(${1 + wb + b.visit.window_after} * var(--day-col))`,
  }
}

function onDragStart(e, visit, s) {
  dragging = { visit, s }
  e.dataTransfer.effectAllowed = 'move'
  e.dataTransfer.setData('text/plain', String(visit.id))
}
function onDragOver(e, date) {
  if (dragging) {
    e.dataTransfer.dropEffect = 'move'
    hoverDate.value = date
  }
}
function onDrop(e, date) {
  e.preventDefault()
  hoverDate.value = ''
  if (!dragging) return
  const { visit, s } = dragging
  dragging = null
  if (date === visit.planned_date) return
  emit('reschedule', visit, s, date)
}
</script>

<style scoped>
.gantt-wrap { padding: 0; overflow: hidden; }
.gantt-scroll { overflow-x: auto; }
.gantt {
  display: grid;
  min-width: max-content;
  --day-col: 30px;
}
.gantt-corner {
  position: sticky; left: 0; z-index: 5;
  background: #f7f9fc; border-right: 1px solid var(--border);
  border-bottom: 1px solid var(--border);
  padding: 8px 12px; font-size: 12px; font-weight: 600; color: var(--ink-2);
  display: flex; flex-direction: column; gap: 2px;
}
.col-hint { font-weight: 400; color: var(--ink-3); font-size: 11px; }
.gantt-day-head {
  border-bottom: 1px solid var(--border);
  border-right: 1px solid #eef1f6;
  height: 46px; display: flex; flex-direction: column; align-items: center;
  justify-content: center; font-size: 11px; color: var(--ink-3); position: relative;
}
.gantt-day-head .dom { font-size: 13px; font-weight: 600; color: var(--ink-1); }
.gantt-day-head.mute { background: #fafbfd; }
.gantt-day-head.mute .dom { color: #c2c9d4; }
.gantt-day-head.today { background: var(--brand-50); }
.today-flag {
  position: absolute; top: 2px; right: 2px;
  background: var(--status-critical); color: #fff; font-size: 9px;
  border-radius: 3px; padding: 0 3px;
}
.gantt-row-head {
  position: sticky; left: 0; z-index: 4;
  background: #fff; border-right: 1px solid var(--border);
  border-bottom: 1px solid #eef1f6;
  padding: 8px 12px; min-width: 0;
}
.gh-name { display: flex; align-items: center; gap: 6px; }
.gh-mask { font-weight: 600; font-size: 13px; white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
.gh-code { font-size: 11px; color: var(--ink-3); margin-top: 2px; }
.gh-prog { display: flex; align-items: center; gap: 8px; margin-top: 6px; }
.gh-prog :deep(.el-progress) { flex: 1; }
.gh-pct { font-size: 11px; color: var(--ink-2); white-space: nowrap; }
.gh-skip { font-size: 11px; color: var(--status-serious); margin-top: 2px; }
.ver-badge {
  font-size: 10px; padding: 1px 6px; border-radius: 8px; white-space: nowrap; font-weight: 600;
}
.ver-badge.mixed { background: #f3e9fb; color: #7d3aa8; border: 1px solid #dfc6f0; }

.gantt-track { position: relative; height: 48px; border-bottom: 1px solid #eef1f6; overflow: hidden; }
.track-lane { position: absolute; inset: 0; }
.drop-cell { position: absolute; top: 0; bottom: 0; }
.drop-cell.mute { background: #fafbfd; }
.drop-cell.today { background: color-mix(in srgb, var(--brand-50) 55%, transparent); }
.drop-cell:hover { background: color-mix(in srgb, var(--brand-100) 60%, transparent); }
.today-line {
  position: absolute; top: 0; bottom: 0; width: 2px;
  background: var(--status-critical); opacity: .55; z-index: 2; pointer-events: none;
}

.vbar {
  position: absolute; top: 12px; height: 24px; z-index: 3;
  border-radius: 6px; cursor: grab; display: flex; align-items: center;
  padding: 0 4px; gap: 3px; border: 1px solid transparent; user-select: none;
  min-width: 26px;
}
.vbar:active { cursor: grabbing; }
.vbar-no { font-size: 10px; font-weight: 700; white-space: nowrap; }
.vbar-lock { font-size: 11px; }
.vbar-win {
  position: absolute; top: 50%; transform: translateY(-50%);
  height: 10px; border-radius: 5px; opacity: .28; z-index: -1;
}
.vbar.scheduled { background: #eef1f5; color: #5a6574; border-color: #d9dee7; }
.vbar.scheduled .vbar-win { background: #9aa6b6; }
.vbar.in_window { background: var(--status-warning-bg); color: #6d4c00; border-color: #ecd78d; }
.vbar.in_window .vbar-win { background: var(--status-warning); }
.vbar.due_today { background: var(--status-critical); color: #fff; }
.vbar.due_today .vbar-win { background: var(--status-critical); }
.vbar.overdue { background: var(--status-serious-bg); color: #9c451f; border-color: #f0c4ab; }
.vbar.overdue .vbar-win { background: var(--status-serious); }
.vbar.out_of_window { background: var(--status-critical-bg); color: #a52020; border-color: #f1b7b7; }
.vbar.out_of_window .vbar-win { background: var(--status-critical); }
.vbar.done { background: var(--status-good-bg); color: #0b6b2c; border-color: #b8e3b8; cursor: pointer; }
.vbar.done .vbar-win { background: var(--status-good); }
.vbar.skipped {
  background: repeating-linear-gradient(45deg, #f1f1f1, #f1f1f1 5px, #e6e6e6 5px, #e6e6e6 10px);
  color: #888; border-color: #ddd; text-decoration: line-through;
}
.vbar.unscheduled { outline: 2px dashed var(--brand-400); outline-offset: -1px; }
.vbar.oldver { border-style: dotted; }
.vbar.locked { cursor: not-allowed; }
.vbar.dragging { opacity: .5; }

.gantt-legend {
  display: flex; flex-wrap: wrap; gap: 14px; align-items: center;
  padding: 10px 14px; border-top: 1px solid var(--border);
  font-size: 11px; color: var(--ink-2);
}
.gantt-legend span { display: inline-flex; align-items: center; gap: 5px; }
.lg { width: 12px; height: 12px; border-radius: 3px; display: inline-block; }
.lg.scheduled { background: #eef1f5; border: 1px solid #d9dee7; }
.lg.in_window { background: var(--status-warning-bg); border: 1px solid #ecd78d; }
.lg.due_today { background: var(--status-critical); }
.lg.overdue { background: var(--status-serious-bg); border: 1px solid #f0c4ab; }
.lg.out_of_window { background: var(--status-critical-bg); border: 1px solid #f1b7b7; }
.lg.done { background: var(--status-good-bg); border: 1px solid #b8e3b8; }
.lg.skipped { background: repeating-linear-gradient(45deg,#f1f1f1,#f1f1f1 4px,#e6e6e6 4px,#e6e6e6 8px); }
.lg.unscheduled { outline: 2px dashed var(--brand-400); }
.lg.oldver { border: 2px dotted #999; background: #fff; }
.legend-hint { color: var(--ink-3); margin-left: auto; }
</style>
