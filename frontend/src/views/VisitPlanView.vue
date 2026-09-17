<template>
  <div v-loading="loading">
    <div class="vp-head">
      <div>
        <h2 class="page-title">访视计划</h2>
        <div class="page-sub">
          排程/窗期按研究中心所在时区显示 · 日期统一 UTC 存储 ·
          完成度按「已完成关键表单数」口径，总览/详情/导出三处一致
        </div>
      </div>
      <div class="vp-head-actions">
        <el-button :icon="Download" @click="exportCsv">导出 CSV</el-button>
        <el-popover placement="bottom-end" :width="420" trigger="click">
          <template #reference>
            <el-button :icon="InfoFilled" plain>口径与方案说明</el-button>
          </template>
          <div class="policy-pop">
            <div class="pp-h">完成度口径</div>
            <p>{{ policy?.completion_policy_text }}</p>
            <div class="pp-h">两种排程口径冲突时以哪个为准</div>
            <p>{{ policy?.anchor_policy_text }}</p>
            <div class="pp-h">方案修订冻结</div>
            <p>{{ policy?.amendment_freeze_text }}</p>
            <div class="pp-h">时区</div>
            <p>{{ policy?.storage_tz_note }}</p>
          </div>
        </el-popover>
      </div>
    </div>

    <!-- 加载失败：明确错误态（不是空白页/“暂无数据”） -->
    <ErrorState v-if="errorMsg" type="warn" title="访视计划加载失败" :message="errorMsg"
                style="margin-top:14px">
      <el-button type="primary" @click="load">重新加载</el-button>
    </ErrorState>

    <template v-else>
      <!-- 跨方案版本并存全局提示 -->
      <el-alert v-if="mixedCount" type="warning" :closable="false" show-icon
                style="margin-top:14px"
                :title="`检测到 ${mixedCount} 名受试者正跨方案版本（旧版访视已冻结、新版访视在执行），甘特行已用橙色底纹与版本角标标出。`" />

      <!-- 筛选 + 视图切换 -->
      <div class="card vp-toolbar">
        <el-select v-model="siteId" placeholder="全部中心" clearable size="default"
                   style="width:190px" @change="load">
          <el-option v-for="s in sites" :key="s.id" :label="s.name" :value="s.id" />
        </el-select>
        <el-input v-model="keyword" placeholder="筛选号/受试者编号" clearable
                  style="width:180px" :prefix-icon="Search" />
        <el-checkbox v-model="onlyMixed">仅看跨方案版本</el-checkbox>
        <el-checkbox v-model="onlyAbnormal">仅看超窗/逾期/今日</el-checkbox>
        <span class="tb-spacer" />
        <el-radio-group v-if="device === 'desktop'" v-model="mode" size="default">
          <el-radio-button value="month">月视图</el-radio-button>
          <el-radio-button value="week">周视图</el-radio-button>
        </el-radio-group>
        <el-button-group>
          <el-button :icon="ArrowLeft" @click="shift(-1)" />
          <el-button @click="goToday">今天</el-button>
          <el-button @click="shift(1)"><el-icon><ArrowRight /></el-icon></el-button>
        </el-button-group>
        <span class="vp-range-label">{{ rangeLabel }}</span>
      </div>

      <!-- KPI -->
      <div class="vp-kpi">
        <div class="kpi-card card">
          <div class="kpi-num">{{ subjects.length }}</div>
          <div class="kpi-label">在范围内受试者</div>
        </div>
        <div class="kpi-card card">
          <div class="kpi-num num-good">{{ dueTodayCount }}</div>
          <div class="kpi-label">今日应随访</div>
        </div>
        <div class="kpi-card card">
          <div class="kpi-num num-serious">{{ abnormalCount }}</div>
          <div class="kpi-label">逾期 / 超窗</div>
        </div>
        <div class="kpi-card card">
          <div class="kpi-num num-warn">{{ mixedCount }}</div>
          <div class="kpi-label">跨方案版本并存</div>
        </div>
        <div class="kpi-card card">
          <div class="kpi-num num-brand">{{ overallRate }}%</div>
          <div class="kpi-label">关键表单完成度（均值）</div>
        </div>
        <div class="kpi-card card">
          <div class="kpi-num">{{ noVisitCount }} / {{ allSkippedCount }}</div>
          <div class="kpi-label">尚无访视 / 全部跳过</div>
        </div>
      </div>

      <!-- 完成度口径明示条 -->
      <div class="basis-bar">
        <el-icon><InfoFilled /></el-icon>
        <span>
          完成度 = 已完成关键表单数 ÷ 关键表单总数（一张表须全部必填项完成并提交才算 1 张；
          只填半张表的访视计 <b>0</b>，不按已填字段数虚算）。本数字由服务端统一计算。
        </span>
      </div>

      <!-- 三种“空”局面的全局分流 -->
      <ErrorState v-if="!loading && !subjects.length" type="empty"
                  title="当前范围内还没有受试者"
                  message="还没有任何受试者进入访视计划。新受试者入组并生成方案访视后会自动出现在这里；可调整上方中心筛选。"
                  style="margin-top:14px">
        <el-button type="primary" @click="$router.push('/subjects')">去受试者菜单登记</el-button>
      </ErrorState>
      <ErrorState v-else-if="!loading && !filtered.length" type="empty"
                  title="没有符合筛选条件的访视安排"
                  message="当前筛选（关键字 / 仅跨版本 / 仅超窗）下没有匹配的受试者，请放宽条件后再看。"
                  style="margin-top:14px" />

      <template v-else>
        <!-- 桌面 / 平板：甘特（平板右侧带当周日程两栏） -->
        <div v-if="device !== 'mobile'" :class="['card vp-canvas', { tablet: device === 'tablet' }]">
          <VisitGantt :subjects="filtered" :days="days" :today-key="todayKey"
                      :mode="effectiveMode" :month-anchor="anchor"
                      @reschedule="onReschedule" @skip="onSkip" />
          <div v-if="device === 'tablet'" class="vp-side">
            <div class="side-h">当周日程（两栏）</div>
            <div class="side-agenda">
              <VisitAgendaList :subjects="filtered" :today-key="todayKey"
                               :from-key="fromKey" :to-key="rangeEndKey"
                               @reschedule="onReschedule" @skip="onSkip" />
            </div>
          </div>
        </div>

        <!-- 手机：竖向日程列表 -->
        <div v-else class="card vp-mobile">
          <VisitAgendaList :subjects="filtered" :today-key="todayKey"
                           :from-key="fromKey" :to-key="rangeEndKey"
                           @reschedule="onReschedule" @skip="onSkip" />
        </div>
      </template>
    </template>

    <VisitActionDialogs ref="dialogs" @changed="load" />
  </div>
</template>

<script setup>
import { computed, onMounted, ref } from 'vue'
import { ElMessage } from 'element-plus'
import {
  ArrowLeft, ArrowRight, Download, InfoFilled, Search,
} from '@element-plus/icons-vue'
import { visitPlanApi, metaApi } from '@/api'
import { useDevice } from '@/composables/useDevice'
import ErrorState from '@/components/ErrorState.vue'
import VisitGantt from '@/components/VisitGantt.vue'
import VisitAgendaList from '@/components/VisitAgendaList.vue'
import VisitActionDialogs from '@/components/VisitActionDialogs.vue'
import {
  addDays, buildMonthDays, buildWeekDays, monthLabel, parseDate, toKey, weekRangeLabel,
} from '@/utils/date'

const device = useDevice()
const dialogs = ref(null)

const loading = ref(false)
const errorMsg = ref('')
const policy = ref(null)
const subjects = ref([])
const sites = ref([])
const todayKey = ref(toKey(new Date()))

const siteId = ref(null)
const keyword = ref('')
const onlyMixed = ref(false)
const onlyAbnormal = ref(false)
const mode = ref('month')
const anchor = ref(new Date())

// 平板固定周视图（两栏日程），桌面可在月/周间切换，手机用竖向列表
const effectiveMode = computed(() =>
  device.value === 'tablet' ? 'week' : mode.value,
)
const days = computed(() =>
  effectiveMode.value === 'week' ? buildWeekDays(anchor.value) : buildMonthDays(anchor.value),
)
const fromKey = computed(() => toKey(days.value[0]))
const rangeEndKey = computed(() => toKey(days.value[days.value.length - 1]))
const rangeLabel = computed(() =>
  effectiveMode.value === 'week' ? weekRangeLabel(days.value) : monthLabel(anchor.value),
)

const filtered = computed(() => {
  const kw = keyword.value.trim().toLowerCase()
  return subjects.value.filter((r) => {
    if (kw && !(`${r.screening_no} ${r.subject_code || ''}`.toLowerCase().includes(kw)))
      return false
    if (onlyMixed.value && !r.mixed_versions) return false
    if (onlyAbnormal.value) {
      const bad = r.visits.some((v) =>
        ['overdue', 'out_of_window', 'due_today'].includes(v.visit_state))
      if (!bad) return false
    }
    return true
  })
})

const mixedCount = computed(() => subjects.value.filter((r) => r.mixed_versions).length)
const noVisitCount = computed(() => subjects.value.filter((r) => r.empty_kind === 'no_visits').length)
const allSkippedCount = computed(() => subjects.value.filter((r) => r.empty_kind === 'all_skipped').length)
const dueTodayCount = computed(() =>
  subjects.value.reduce((n, r) =>
    n + r.visits.filter((v) => v.visit_state === 'due_today').length, 0))
const abnormalCount = computed(() =>
  subjects.value.reduce((n, r) =>
    n + r.visits.filter((v) => ['overdue', 'out_of_window'].includes(v.visit_state)).length, 0))
const overallRate = computed(() => {
  const withForms = subjects.value.filter((r) => r.completion.key_total > 0)
  if (!withForms.length) return '0.0'
  const sum = withForms.reduce((a, r) => a + r.completion.rate, 0)
  return (sum / withForms.length).toFixed(1)
})

async function load() {
  loading.value = true
  errorMsg.value = ''
  try {
    const [gantt, pol, siteList] = await Promise.all([
      visitPlanApi.gantt(siteId.value ? { site_id: siteId.value } : {}),
      visitPlanApi.policy().catch(() => null),
      metaApi.sites().catch(() => []),
    ])
    subjects.value = gantt.subjects
    policy.value = pol
    sites.value = siteList
    todayKey.value = gantt.today
  } catch (e) {
    errorMsg.value = e.message || '网络异常，请稍后重试'
    subjects.value = []
  } finally {
    loading.value = false
  }
}

function shift(n) {
  anchor.value = effectiveMode.value === 'week'
    ? addDays(anchor.value, 7 * n)
    : new Date(anchor.value.getFullYear(), anchor.value.getMonth() + n, 1)
}
function goToday() { anchor.value = parseDate(todayKey.value) }

function onReschedule({ visit, row, newDate }) {
  dialogs.value.openReschedule({
    visit,
    subjectName: row?.masked_name || visit.masked_name || '',
    newDate: newDate || visit.planned_date,
  })
}
function onSkip({ visit }) { dialogs.value.openSkip({ visit }) }

async function exportCsv() {
  try {
    const blob = await visitPlanApi.exportCsv(siteId.value ? { site_id: siteId.value } : {})
    const url = URL.createObjectURL(blob)
    const a = document.createElement('a')
    a.href = url
    a.download = `visit-plan-${todayKey.value}.csv`
    a.click()
    URL.revokeObjectURL(url)
    ElMessage.success('已导出 CSV（完成度与本页/详情页同源一致）')
  } catch (e) {
    // blob 响应的错误体需要额外解析
    if (e.raw?.response?.data instanceof Blob) {
      try {
        const txt = await e.raw.response.data.text()
        const j = JSON.parse(txt)
        return ElMessage.error(j?.error?.message || '导出失败')
      } catch { /* fallthrough */ }
    }
    ElMessage.error(e.message || '导出失败')
  }
}

onMounted(load)
</script>

<style scoped>
.vp-head { display: flex; justify-content: space-between; align-items: flex-start; gap: 12px; flex-wrap: wrap; }
.vp-head-actions { display: flex; gap: 8px; }
.vp-toolbar {
  margin-top: 14px; padding: 12px 14px;
  display: flex; align-items: center; gap: 10px; flex-wrap: wrap;
}
.tb-spacer { flex: 1; }
.vp-range-label { font-weight: 600; font-size: 13px; color: var(--ink-2); min-width: 130px; }

.vp-kpi { display: grid; grid-template-columns: repeat(6, 1fr); gap: 12px; margin-top: 14px; }
.kpi-card { padding: 12px 14px; }
.kpi-num { font-size: 24px; font-weight: 700; }
.kpi-label { font-size: 12px; color: var(--ink-3); margin-top: 2px; }
.num-good { color: var(--status-good); }
.num-serious { color: var(--status-critical); }
.num-warn { color: var(--status-warning); }
.num-brand { color: var(--brand-600); }

.basis-bar {
  margin-top: 12px; display: flex; gap: 8px; align-items: flex-start;
  background: var(--status-info-bg); border: 1px solid #cfe0f6;
  border-radius: 8px; padding: 9px 12px; font-size: 12.5px; color: #274b76; line-height: 1.7;
}
.basis-bar .el-icon { margin-top: 3px; flex: 0 0 auto; }

.vp-canvas { margin-top: 14px; padding: 10px; }
.vp-canvas.tablet { display: grid; grid-template-columns: minmax(0, 1fr) 300px; gap: 12px; }
.vp-side { border-left: 1px solid var(--border); padding-left: 12px; min-width: 0; }
.side-h { font-weight: 600; font-size: 13px; margin-bottom: 8px; color: var(--ink-2); }
.side-agenda { max-height: 560px; overflow-y: auto; padding-right: 4px; }
.vp-mobile { margin-top: 14px; padding: 12px; }

.policy-pop { font-size: 12.5px; color: var(--ink-2); line-height: 1.7; max-height: 60vh; overflow-y: auto; }
.pp-h { font-weight: 700; color: var(--ink-1); margin: 8px 0 2px; }
.policy-pop p { margin: 0 0 6px; }

@media (max-width: 1180px) {
  .vp-kpi { grid-template-columns: repeat(3, 1fr); }
}
@media (max-width: 640px) {
  .vp-kpi { grid-template-columns: repeat(2, 1fr); }
  .vp-range-label { display: none; }
}
</style>
