<template>
  <div class="gantt-scroll table-scroll" @dragover.prevent>
    <div class="gantt" :style="gridStyle">
      <!-- 表头：角标 + 日期列 -->
      <div class="gt-corner">受试者 / 访视</div>
      <div class="gt-head-track">
        <div v-for="(d, i) in days" :key="i"
             :class="['gt-day-head', { weekend: isWeekend(d), today: isToday(d), outside: !inMonth(d) }]"
             :style="cellStyle">
          <div class="gt-weekday">{{ weekdayShort(d) }}</div>
          <div class="gt-date">{{ d.getDate() }}</div>
        </div>
      </div>

      <!-- 每个受试者一行：左标签 + 跨列轨道（落点格与访视覆盖层） -->
      <template v-for="(row) in subjects" :key="row.subject_id">
        <div :class="['gt-label', { 'mixed-row': row.mixed_versions }]">
          <div class="gt-name">
            <router-link :to="`/visit-plans/subjects/${row.subject_id}`" class="gt-link">
              {{ row.masked_name }}
            </router-link>
            <el-tag v-if="row.mixed_versions" size="small" type="danger" effect="dark"
                    class="gt-vtag" :title="`跨方案版本：${row.mixed_versions.labels.join(' / ')}`">
              {{ row.mixed_versions.old_label }}+{{ row.mixed_versions.new_label }}
            </el-tag>
          </div>
          <div class="gt-sub">{{ row.screening_no }} · {{ row.site_code }}</div>
          <div v-if="row.empty_kind === 'no_visits'" class="gt-empty-tag">
            <el-icon><Box /></el-icon> 尚无任何访视安排
          </div>
          <div v-else-if="row.empty_kind === 'all_skipped'" class="gt-empty-tag skipped">
            <el-icon><Hide /></el-icon> 访视已全部跳过
          </div>
          <el-progress v-else :percentage="row.completion.rate" :stroke-width="6"
                       :status="row.completion.rate === 100 ? 'success' : ''"
                       class="gt-progress" />
        </div>

        <div :class="['gt-track', { 'mixed-row': row.mixed_versions }]">
          <!-- 落点格 -->
          <div v-for="(d, i) in days" :key="i"
               :class="['gt-cell', { weekend: isWeekend(d), today: isToday(d),
                        outside: !inMonth(d), 'drop-hi': dropKey === toKey(d) }]"
               :style="cellStyle"
               @dragover.prevent="onDragOver(d)" @dragleave="dropKey = ''"
               @drop.prevent="onDrop(d, row)" />

          <!-- 名义日（随机化口径）虚线刻度 -->
          <template v-for="v in row.visits" :key="'n' + v.id">
            <div v-if="v.divergence_days !== 0 && idxOf(v.nominal_date) >= 0"
                 class="gt-nominal" :style="tickStyle(idxOf(v.nominal_date))"
                 :title="`随机化口径名义日 ${v.nominal_date}；现行执行口径 ${v.planned_date}（差 ${v.divergence_days} 天）`" />
          </template>
          <!-- 窗口条 -->
          <template v-for="v in row.visits" :key="'w' + v.id">
            <div v-if="windowOf(v)" :class="['gt-window', v.visit_state]"
                 :style="barStyle(windowOf(v))" />
          </template>
          <!-- 访视块 -->
          <template v-for="v in row.visits" :key="v.id">
            <div v-if="chipPos(v)" class="gt-chip-wrap" :style="chipPos(v)"
                 :title="chipTitle(v, row)">
              <el-dropdown trigger="click" @command="(cmd) => onCommand(cmd, v, row)">
                <div :class="['gt-chip', v.visit_state, {
                              locked: v.locked, skipped: v.status === 'skipped',
                              unscheduled: v.kind === 'unscheduled', draggable: v.can_edit }]"
                     :draggable="v.can_edit"
                     @dragstart="onDragStart($event, v, row)" @dragend="dropKey = ''">
                  <span class="gt-chip-no">{{ v.visit_no }}</span>
                  <span v-if="mode === 'week'" class="gt-chip-name">{{ v.name }}</span>
                  <el-icon v-if="v.locked" class="gt-lock"><Lock /></el-icon>
                  <span v-if="v.kind === 'unscheduled'" class="gt-u">◆</span>
                  <span v-if="v.version_label" class="gt-ver">{{ v.version_label }}</span>
                </div>
                <template #dropdown>
                  <el-dropdown-menu>
                    <el-dropdown-item command="reschedule" :disabled="!v.can_edit">
                      改期{{ v.can_edit ? '' : '（已冻结不可改）' }}
                    </el-dropdown-item>
                    <el-dropdown-item command="skip" :disabled="!v.can_skip">跳过访视</el-dropdown-item>
                    <el-dropdown-item command="detail">打开受试者日程 →</el-dropdown-item>
                  </el-dropdown-menu>
                </template>
              </el-dropdown>
            </div>
          </template>
        </div>
      </template>
    </div>
  </div>
</template>

<script setup>
import { computed, ref } from 'vue'
import { useRouter } from 'vue-router'
import { Lock } from '@element-plus/icons-vue'
import { parseDate, toKey, weekdayShort } from '@/utils/date'

const props = defineProps({
  subjects: { type: Array, required: true },
  days: { type: Array, required: true },
  todayKey: { type: String, required: true },
  mode: { type: String, default: 'month' },
  monthAnchor: { type: Date, required: true },
})
const emit = defineEmits(['reschedule', 'skip'])

const router = useRouter()
const dropKey = ref('')
let dragPayload = null

const colW = computed(() => (props.mode === 'week' ? 132 : 34))
const gridStyle = computed(() => ({
  gridTemplateColumns: `210px minmax(${props.days.length * colW.value}px, 1fr)`,
}))
const cellStyle = computed(() => ({ width: `${colW.value}px`, flex: `0 0 ${colW.value}px` }))

const day0 = computed(() => props.days[0])

function idxOf(key) {
  if (!key) return -1
  const n = Math.round((parseDate(key) - day0.value) / 86400000)
  return n >= 0 && n < props.days.length ? n : -1
}
function leftPct(i) { return (i / props.days.length) * 100 }
function spanPct(n) { return (n / props.days.length) * 100 }

function isWeekend(d) { return d.getDay() === 0 || d.getDay() === 6 }
function isToday(d) { return toKey(d) === props.todayKey }
function inMonth(d) { return d.getMonth() === props.monthAnchor.getMonth() }

function windowOf(v) {
  if (v.status === 'skipped' || v.kind === 'unscheduled') return null
  const i = idxOf(v.planned_date)
  if (i < 0) return null
  const start = Math.max(0, i - v.window_before)
  const end = Math.min(props.days.length - 1, i + v.window_after)
  return { start, span: end - start + 1 }
}

// 同一天多块堆叠车道
const lanes = computed(() => {
  const out = {}
  for (const row of props.subjects) {
    const used = {}
    for (const v of row.visits) {
      const i = idxOf(v.planned_date)
      if (i < 0) continue
      let lane = 0
      while (used[`${i}:${lane}`]) lane += 1
      used[`${i}:${lane}`] = true
      out[v.id] = lane
    }
  }
  return out
})

function chipPos(v) {
  const i = idxOf(v.planned_date)
  if (i < 0) return null
  const lane = lanes.value[v.id] || 0
  const width = props.mode === 'week' ? 124 : 30
  return {
    left: `calc(${leftPct(i)}% + 2px)`,
    width: `${width}px`,
    top: `${22 + lane * 22}px`,
  }
}
function barStyle(w) {
  return {
    left: `calc(${leftPct(w.start)}% + 2px)`,
    width: `calc(${spanPct(w.span)}% - 4px)`,
  }
}
function tickStyle(i) {
  return { left: `calc(${leftPct(i)}% + ${colW.value / 2 - 1}px)` }
}

function chipTitle(v, row) {
  const parts = [
    `${row.masked_name} · ${v.name}（${v.visit_no}）`,
    `现行计划：${v.planned_date}（窗口 前${v.window_before}/后${v.window_after}）`,
  ]
  if (v.divergence_days !== 0)
    parts.push(`随机化口径名义日：${v.nominal_date}（差异 ${v.divergence_days} 天）`)
  if (v.actual_date) parts.push(`实际访视：${v.actual_date}`)
  parts.push(`状态：${v.visit_state_label}`)
  parts.push(`完成度：${v.completion.key_done}/${v.completion.key_total} 关键表单（${v.completion.rate}%）`)
  if (v.version_label) parts.push(`方案版本：${v.version_label}`)
  if (v.locked) parts.push('已锁库：计划日期与表单冻结，不可改期/跳过')
  if (v.insert_reason) parts.push(`计划外原因：${v.insert_reason}`)
  return parts.join('\n')
}

function onDragStart(e, v, row) {
  if (!v.can_edit) { e.preventDefault(); return }
  dragPayload = { visit: v, row }
  e.dataTransfer.effectAllowed = 'move'
  try { e.dataTransfer.setData('text/plain', String(v.id)) } catch { /* firefox */ }
}
function onDragOver(d) { dropKey.value = toKey(d) }
function onDrop(d) {
  const key = toKey(d)
  dropKey.value = ''
  if (dragPayload && key !== dragPayload.visit.planned_date) {
    emit('reschedule', { ...dragPayload, newDate: key })
  }
  dragPayload = null
}
function onCommand(cmd, v, row) {
  if (cmd === 'reschedule') emit('reschedule', { visit: v, row })
  else if (cmd === 'skip') emit('skip', { visit: v })
  else if (cmd === 'detail') router.push(`/visit-plans/subjects/${row.subject_id}`)
}
</script>

<style scoped>
.gantt-scroll { overflow-x: auto; padding-bottom: 8px; }
.gantt {
  display: grid;
  border: 1px solid var(--border);
  border-radius: 8px;
  background: var(--surface-card);
  min-width: max-content;
}
.gt-corner {
  background: #f7f9fc; border-bottom: 1px solid var(--border);
  border-right: 1px solid var(--border);
  padding: 8px 10px; font-size: 12px; color: var(--ink-2); font-weight: 600;
  display: flex; align-items: center;
}
.gt-head-track {
  display: flex; border-bottom: 1px solid var(--border);
  background: #f7f9fc;
}
.gt-day-head {
  flex: 0 0 auto; text-align: center; padding: 4px 0;
  font-size: 11px; color: var(--ink-3);
  border-right: 1px solid #eef1f6;
}
.gt-day-head .gt-date { font-size: 13px; color: var(--ink-1); font-weight: 600; }
.gt-day-head.weekend { background: #f1f4f9; }
.gt-day-head.today { background: var(--brand-50); }
.gt-day-head.today .gt-date { color: var(--brand-700); }
.gt-day-head.outside .gt-date { color: #c2c9d4; }

.gt-label {
  background: var(--surface-card);
  border-bottom: 1px solid var(--border);
  border-right: 1px solid var(--border);
  padding: 6px 10px; min-height: 64px;
}
.gt-label.mixed-row { background: #fff7ec; }
.gt-name { display: flex; align-items: center; gap: 6px; font-weight: 600; font-size: 13px; }
.gt-link { color: var(--brand-600); text-decoration: none; }
.gt-link:hover { text-decoration: underline; }
.gt-vtag { transform: scale(0.85); transform-origin: left center; }
.gt-sub { font-size: 11px; color: var(--ink-3); margin: 2px 0 4px; }
.gt-progress { width: 120px; }
.gt-empty-tag {
  display: inline-flex; align-items: center; gap: 4px;
  font-size: 11px; color: var(--ink-3); margin-top: 2px;
}
.gt-empty-tag.skipped { color: #8a93a3; }

.gt-track {
  position: relative; display: flex; min-height: 64px;
  border-bottom: 1px solid var(--border);
}
.gt-track.mixed-row { background: #fffdf8; }
.gt-cell {
  flex: 0 0 auto; border-right: 1px solid #f1f3f7; position: relative;
}
.gt-cell.weekend { background: #fafbfd; }
.gt-cell.today { background: var(--brand-50); }
.gt-cell.outside { opacity: 0.5; }
.gt-cell.drop-hi {
  background: var(--brand-100) !important;
  outline: 2px dashed var(--brand-400); outline-offset: -2px; z-index: 3;
}

.gt-window { position: absolute; height: 6px; border-radius: 3px; top: 52px; background: #cdd8e6; z-index: 1; }
.gt-window.in_window, .gt-window.due_today { background: var(--brand-250); }
.gt-window.overdue { background: #e8a98b; }
.gt-window.out_of_window { background: #ec9d9d; }
.gt-nominal {
  position: absolute; top: 0; bottom: 6px; width: 0;
  border-left: 2px dashed #b79a4a; z-index: 1;
}
.gt-chip-wrap { position: absolute; z-index: 2; }
.gt-chip {
  display: inline-flex; align-items: center; gap: 3px;
  height: 20px; padding: 0 5px; border-radius: 5px;
  font-size: 11px; line-height: 20px; cursor: pointer;
  white-space: nowrap; max-width: 100%;
  border: 1px solid transparent; user-select: none;
}
.gt-chip.draggable:active { cursor: grabbing; }
.gt-chip-no { font-weight: 700; }
.gt-chip-name { overflow: hidden; text-overflow: ellipsis; }
.gt-chip.upcoming { background: #eef1f6; color: #46505f; }
.gt-chip.in_window { background: var(--status-warning-bg); color: #6d4c00; }
.gt-chip.due_today { background: var(--status-critical); color: #fff; }
.gt-chip.overdue { background: var(--status-serious-bg); color: #9c451f; }
.gt-chip.out_of_window { background: var(--status-critical-bg); color: #a52020; font-weight: 700; }
.gt-chip.done { background: var(--status-good-bg); color: #0b6b2c; }
.gt-chip.missed { background: #ece7f7; color: #5d4a93; }
.gt-chip.skipped {
  background: repeating-linear-gradient(45deg, #f2f3f6, #f2f3f6 4px, #e7e9ee 4px, #e7e9ee 8px);
  color: #8a93a3;
}
.gt-chip.unscheduled { outline: 2px dashed #184f95; outline-offset: -2px; background: #e9f1fc; color: #184f95; }
.gt-chip.locked { box-shadow: inset 0 0 0 1px #b9851f; }
.gt-lock { font-size: 11px; }
.gt-u { font-size: 9px; }
.gt-ver {
  font-size: 9px; background: rgba(0,0,0,0.12); border-radius: 3px;
  padding: 0 3px; margin-left: 1px;
}
</style>
