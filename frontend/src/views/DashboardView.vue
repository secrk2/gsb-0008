<template>
  <div v-loading="loading">
    <div style="display:flex; align-items:flex-end; justify-content:space-between; gap:12px; flex-wrap:wrap">
      <div>
        <h2 class="page-title">入组作战台</h2>
        <div class="page-sub">
          多中心入组进度与访视风险一屏总览 · 数据时间 {{ fmtTime(data?.generated_at) }}
        </div>
      </div>
      <el-button :icon="Refresh" @click="load" :loading="loading">刷新</el-button>
    </div>

    <!-- 加载失败 / 离线错误态（明确，不是空白页） -->
    <div v-if="error" class="card state-block" style="margin-top:16px">
      <div class="state-icon forbidden"><el-icon><WarningFilled /></el-icon></div>
      <div class="state-title">作战台数据加载失败</div>
      <div class="state-desc">{{ error }}</div>
      <el-button type="primary" @click="load">重新加载</el-button>
    </div>

    <template v-else-if="data">
      <!-- KPI 行：红点聚合 -->
      <div class="grid-kpi" style="margin-top:16px">
        <div class="card kpi-card">
          <div class="kpi-label"><el-icon><Document /></el-icon>累计筛选登记</div>
          <div class="kpi-value num-mono">{{ totalScreened }}</div>
          <div class="kpi-foot">{{ data.sites.length }} 家中心合计</div>
        </div>
        <div class="card kpi-card good">
          <div class="kpi-label"><el-icon><CircleCheck /></el-icon>成功入组</div>
          <div class="kpi-value num-mono">{{ totalEnrolled }}</div>
          <div class="kpi-foot">总体入组转化率 {{ overallEnrollRate }}%</div>
        </div>
        <div class="card kpi-card alert">
          <div class="kpi-label">
            <el-icon><AlarmClock /></el-icon>今日应随访
            <span v-if="data.alerts.today" class="red-dot">{{ data.alerts.today }}</span>
          </div>
          <div class="kpi-value num-mono">{{ data.alerts.today }}</div>
          <div class="kpi-foot">需在今日完成窗内随访</div>
        </div>
        <div class="card kpi-card alert">
          <div class="kpi-label">
            <el-icon><Warning /></el-icon>逾期 / 超窗红点
            <span v-if="riskTotal" class="red-dot">{{ riskTotal }}</span>
          </div>
          <div class="kpi-value num-mono">
            <span style="color:var(--status-serious)">{{ data.alerts.overdue }}</span>
            <span style="color:var(--ink-3); font-size:16px"> / </span>
            <span>{{ data.alerts.out_of_window }}</span>
          </div>
          <div class="kpi-foot">逾期（窗内）/ 已超窗，需立即处置</div>
        </div>
      </div>

      <!-- 总漏斗 + 状态分布 -->
      <div class="grid-2" style="margin-top:16px">
        <div class="card section-card">
          <h3><el-icon><DataAnalysis /></el-icon>总体入组漏斗
            <span style="font-weight:400; color:var(--ink-3); font-size:12px">筛选 → 入组 → 在研 → 完成</span>
          </h3>
          <div ref="funnelEl" style="height: 300px"></div>
        </div>
        <div class="card section-card">
          <h3><el-icon><PieChart /></el-icon>受试者状态分布</h3>
          <div style="display:flex; flex-direction:column; gap:10px; margin-top:4px">
            <div v-for="s in statusRows" :key="s.value" style="display:grid; grid-template-columns:84px 1fr 40px; align-items:center; gap:10px">
              <StatusTag :status="s.value" />
              <div class="funnel-bar-track">
                <div :style="{ width: pct(s.count) + '%', height:'100%', borderRadius:'5px', background: s.color }" />
              </div>
              <div class="num-mono" style="text-align:right; color:var(--ink-2)">{{ s.count }}</div>
            </div>
          </div>
          <div style="margin-top:14px; padding:10px 12px; background:var(--status-critical-bg); border-radius:8px; font-size:12px; color:#8f2323; display:flex; gap:8px; align-items:flex-start">
            <el-icon style="margin-top:2px"><WarningFilled /></el-icon>
            <span>
              风险聚合：今日 <b>{{ data.alerts.today }}</b> 项应随访、
              <b style="color:var(--status-serious)">{{ data.alerts.overdue }}</b> 项逾期、
              <b>{{ data.alerts.out_of_window }}</b> 项已超窗；超窗访视须按方案走 PD 评估，不得静默处理。
            </span>
          </div>
        </div>
      </div>

      <!-- 各中心入组进度 -->
      <h3 style="margin:22px 0 4px; font-size:15px; display:flex; align-items:center; gap:8px">
        <el-icon><OfficeBuilding /></el-icon>各中心入组进度
      </h3>
      <div class="grid-sites">
        <div v-for="s in data.sites" :key="s.site.id" class="card site-funnel-card">
          <div class="site-head">
            <div>
              <div class="site-name">{{ s.site.name }}</div>
              <div class="site-meta">{{ s.site.code }} · {{ s.site.city }} · PI {{ s.site.pi_name }}</div>
            </div>
            <div class="num-mono" style="font-size:18px; font-weight:700">
              {{ s.enrolled }}<span style="color:var(--ink-3); font-size:12px">/{{ s.target }}</span>
            </div>
          </div>
          <el-progress
            :percentage="targetPct(s)"
            :stroke-width="10"
            :color="targetPct(s) >= 100 ? 'var(--status-good)' : 'var(--brand-400)'"
          />
          <div style="display:grid; grid-template-columns:1fr 1fr; gap:6px 12px; font-size:12px; color:var(--ink-2); margin-top:2px">
            <span>筛选登记 <b class="num-mono">{{ s.screened }}</b></span>
            <span>入组转化率 <b class="num-mono">{{ s.enrollment_rate }}%</b></span>
            <span>在研 <b class="num-mono" style="color:var(--status-good)">{{ s.active }}</b></span>
            <span>完成率 <b class="num-mono">{{ s.completion_rate }}%</b></span>
            <span>筛选失败 <b class="num-mono">{{ s.screen_failed }}</b></span>
            <span>完成 <b class="num-mono">{{ s.completed }}</b></span>
            <span style="color:var(--status-serious)">脱落 <b class="num-mono">{{ s.dropped }}</b></span>
            <span style="color:#7d3aa8">中止 <b class="num-mono">{{ s.terminated }}</b></span>
            <span style="color:var(--status-critical)">剔除 <b class="num-mono">{{ s.removed }}</b></span>
            <span>目标达成 <b class="num-mono">{{ targetPct(s) }}%</b></span>
          </div>
        </div>
      </div>

      <!-- 今日应随访 -->
      <div class="card section-card" style="margin-top:18px">
        <h3>
          <el-icon color="var(--status-critical)"><AlarmClock /></el-icon>今日应随访清单
          <span class="red-dot">{{ data.today_visits.length }}</span>
        </h3>
        <VisitTable :visits="data.today_visits" :show-site="showSiteCol" emphasize="today" :empty-text="'今日没有计划内随访，节奏良好。'" />
      </div>

      <!-- 逾期 / 超窗 -->
      <div class="grid-2" style="margin-top:16px">
        <div class="card section-card">
          <h3>
            <el-icon color="var(--status-serious)"><Timer /></el-icon>逾期（仍在窗内）
            <span class="red-dot soft">{{ data.overdue_visits.length }}</span>
          </h3>
          <VisitTable :visits="data.overdue_visits" :show-site="showSiteCol" emphasize="overdue"
                      :empty-text="'暂无逾期访视。'" />
        </div>
        <div class="card section-card">
          <h3>
            <el-icon color="var(--status-critical)"><WarningFilled /></el-icon>已超窗（窗后仍未完成）
            <span class="red-dot">{{ data.out_of_window_visits.length }}</span>
          </h3>
          <VisitTable :visits="data.out_of_window_visits" :show-site="showSiteCol" emphasize="oow"
                      :empty-text="'暂无超窗访视。'" />
        </div>
      </div>
    </template>
  </div>
</template>

<script setup>
import { computed, nextTick, onBeforeUnmount, onMounted, ref, watch } from 'vue'
import * as echarts from 'echarts'
import {
  Refresh, Document, CircleCheck, AlarmClock, Warning, DataAnalysis,
  PieChart, OfficeBuilding, Timer, WarningFilled,
} from '@element-plus/icons-vue'
import { dashboardApi } from '@/api'
import { useAuthStore } from '@/stores/auth'
import StatusTag from '@/components/StatusTag.vue'
import VisitTable from '@/components/VisitTable.vue'

const auth = useAuthStore()
const loading = ref(false)
const error = ref('')
const data = ref(null)
const funnelEl = ref(null)
let chart = null
let ro = null

const showSiteCol = computed(() => auth.isDm)

const totalScreened = computed(() => data.value?.funnel_total?.[0]?.count ?? 0)
const totalEnrolled = computed(() => data.value?.funnel_total?.[1]?.count ?? 0)
const overallEnrollRate = computed(() =>
  totalScreened.value ? Math.round((totalEnrolled.value / totalScreened.value) * 1000) / 10 : 0
)
const riskTotal = computed(() => (data.value?.alerts.overdue || 0) + (data.value?.alerts.out_of_window || 0))

const STATUS_COLORS = {
  screening: '#3987e5', enrolled: '#0ca30c', completed: '#8a93a3',
  dropped: '#ec835a', terminated: '#8e44ad', screen_failed: '#999999', removed: '#d03b3b',
}
const statusRows = computed(() => {
  const c = data.value?.subject_status_counts || {}
  return [
    { value: 'screening', count: c.screening || 0, color: STATUS_COLORS.screening },
    { value: 'enrolled', count: c.enrolled || 0, color: STATUS_COLORS.enrolled },
    { value: 'completed', count: c.completed || 0, color: STATUS_COLORS.completed },
    { value: 'dropped', count: c.dropped || 0, color: STATUS_COLORS.dropped },
    { value: 'terminated', count: c.terminated || 0, color: STATUS_COLORS.terminated },
    { value: 'screen_failed', count: c.screen_failed || 0, color: STATUS_COLORS.screen_failed },
    { value: 'removed', count: c.removed || 0, color: STATUS_COLORS.removed },
  ]
})
function pct(count) {
  const max = Math.max(1, ...statusRows.value.map((r) => r.count))
  return Math.round((count / max) * 100)
}
function targetPct(s) { return Math.min(999, Math.round((s.enrolled / Math.max(1, s.target)) * 100)) }
function fmtTime(t) { return t ? new Date(t).toLocaleString('zh-CN', { hour12: false }) : '—' }

async function load() {
  loading.value = true
  error.value = ''
  try {
    data.value = await dashboardApi.get()
    await nextTick()
    renderFunnel()
  } catch (e) {
    data.value = null
    error.value = e.message || '请求失败，请检查网络后重试'
  } finally {
    loading.value = false
  }
}

const FUNNEL_COLORS = ['#86b6ef', '#3987e5', '#1c5cab', '#104281'] // 已校验 ordinal 蓝色阶
function renderFunnel() {
  if (!funnelEl.value || !data.value) return
  if (!chart) chart = echarts.init(funnelEl.value)
  const stages = data.value.funnel_total
  chart.setOption({
    color: FUNNEL_COLORS,
    tooltip: {
      trigger: 'item',
      formatter: (p) => `${p.name}：<b>${p.value}</b> 人`,
      backgroundColor: '#fff', borderColor: '#e3e8f0', textStyle: { color: '#1a2230' },
    },
    series: [{
      type: 'funnel',
      left: '8%', right: '8%', top: 10, bottom: 10,
      minSize: '26%',
      gap: 2, // 2px 表面间隔
      sort: 'descending',
      label: {
        show: true, position: 'inside', formatter: '{b} {c}',
        color: '#fff', fontWeight: 600, fontSize: 13,
      },
      labelLine: { show: false },
      itemStyle: { borderColor: '#fff', borderWidth: 0, borderRadius: [4, 4, 4, 4] },
      data: stages.map((s, i) => ({
        name: s.label, value: s.count,
        itemStyle: { color: FUNNEL_COLORS[i] },
      })),
    }],
  })
}

function onResize() { chart?.resize() }

onMounted(() => {
  load()
  window.addEventListener('resize', onResize)
  if (funnelEl.value) {
    ro = new ResizeObserver(() => chart?.resize())
    ro.observe(funnelEl.value)
  }
})
onBeforeUnmount(() => {
  window.removeEventListener('resize', onResize)
  ro?.disconnect()
  chart?.dispose()
})
watch(() => data.value, () => nextTick(renderFunnel))
</script>
