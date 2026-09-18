<template>
  <div>
    <div class="vp-head">
      <div>
        <h2 class="page-title">访视计划</h2>
        <div class="page-sub">
          方案相对天数排程 · 窗口期推算 · 修订冻结 · {{ data?.site_name || '加载中…' }}
        </div>
      </div>
      <div class="vp-actions">
        <el-radio-group v-model="viewMode" size="small" @change="plan.setView(viewMode)">
          <el-radio-button value="month">月视图</el-radio-button>
          <el-radio-button value="week">周视图</el-radio-button>
        </el-radio-group>
        <el-button-group>
          <el-button :icon="ArrowLeft" @click="plan.prev()" />
          <el-button @click="plan.today()">今天</el-button>
          <el-button @click="plan.next()">下<el-icon class="el-icon--right"><ArrowRight /></el-icon></el-button>
        </el-button-group>
        <el-select
          :model-value="plan.siteId.value" size="small" style="width:180px"
          placeholder="全部中心" clearable @change="plan.setSite($event)"
        >
          <el-option v-for="s in sites" :key="s.id" :label="s.name" :value="s.id" />
        </el-select>
        <el-button :icon="Download" :loading="exporting" @click="doExport">导出 CSV</el-button>
        <el-button type="primary" plain :icon="Plus" @click="openUnscheduled">插入计划外访视</el-button>
        <el-button v-if="auth.isDm" type="warning" plain :icon="DocumentChecked" @click="revisionVisible = true">
          发布方案修订
        </el-button>
      </div>
    </div>

    <div v-loading="plan.loading.value" class="vp-body">
      <!-- 错误态：加载失败（区别于空态） -->
      <ErrorState
        v-if="plan.errorMsg.value"
        type="warn" title="访视计划加载失败"
        :message="plan.errorMsg.value + '  可能是网络/服务异常或登录态失效，请检查网络后重试；若持续失败请联系系统管理员。'"
      >
        <el-button type="primary" @click="plan.load()">重新加载</el-button>
      </ErrorState>

      <template v-else-if="data">
        <!-- 单受试者聚焦 -->
        <div v-if="focusChip" class="focus-chip">
          <el-icon><Aim /></el-icon>
          正在查看单受试者访视：<b>{{ focusChip }}</b>
          <el-button size="small" text :icon="Close" @click="clearFocus">返回全部受试者</el-button>
        </div>

        <!-- 口径与时区横幅 -->
        <el-alert type="info" :closable="false" show-icon class="vp-banner">
          <template #title>
            <div class="banner-line">
              <el-icon><InfoFilled /></el-icon>
              <b>排程口径：</b>{{ data.policy_label }}
              <el-divider direction="vertical" />
              <b>方案版本：</b>当前生效 {{ data.current_version }}
              <el-divider direction="vertical" />
              <b>时区：</b>{{ data.timezone }}（日期按 UTC 存储、按中心时区展示，本地今日 {{ data.today_local }}）
            </div>
            <div class="banner-line basis">{{ data.completion_basis }}</div>
          </template>
        </el-alert>

        <!-- 全局新旧版本并存提示 -->
        <el-alert
          v-if="mixedSubjects.length"
          type="warning" show-icon :closable="false" class="vp-banner"
          :title="`有 ${mixedSubjects.length} 名受试者处于新旧方案并存状态：其已完成/已跳过/锁库访视冻结旧版，未发生访视已切换新版（甘特图中以「旧版冻结」虚线框与版本标签标记）。`"
        />

        <!-- 空态 1：尚无任何访视 -->
        <ErrorState
          v-if="data.empty_reason === 'no_visits'"
          type="empty" title="当前范围内尚无任何访视安排"
          message="访视会在受试者入组（随机化）后，按当前生效方案版本自动生成。请先完成入组，或调整上方中心/时间范围；筛选中的受试者尚不会生成访视。"
        >
          <el-button type="primary" @click="$router.push('/subjects')">前往受试者入组</el-button>
        </ErrorState>

        <!-- 空态 2：访视被全部跳过 -->
        <ErrorState
          v-else-if="data.empty_reason === 'all_skipped'"
          type="warn" title="访视已被全部跳过"
          message="当前范围内受试者的每一次访视都已「跳过」，因此没有待执行或已完成的访视可显示。如属误操作，可在受试者链路中恢复相应访视，计划日期将按锚点规则重新链式计算；若受试者确已终止研究，请在受试者菜单核对其状态。"
        >
          <el-button type="primary" @click="$router.push('/subjects')">前往受试者核对</el-button>
        </ErrorState>

        <!-- 三种宽度布局 -->
        <template v-else>
          <VisitGantt
            v-if="plan.layout.value === 'desktop'"
            :subjects="data.subjects" :days="data.days" :today="data.today_local"
            :view="data.view"
            @open="openDetail"
            @reschedule="onRequestReschedule"
          />
          <VisitTablet
            v-else-if="plan.layout.value === 'tablet'"
            :subjects="data.subjects" :days="data.days" :today="data.today_local"
            @open="openDetail"
            @open-subject="goSubject"
          />
          <VisitMobile
            v-else
            :subjects="data.subjects" :days="data.days" :today="data.today_local"
            @open="openDetail"
          />
        </template>
      </template>
    </div>

    <!-- 改期弹窗 -->
    <RescheduleDialog
      v-model="rescheduleVisible"
      :visit="activeVisit" :subject="activeSubject" :initial-date="rescheduleDate"
      @done="onPlanChanged"
    />

    <!-- 访视详情抽屉 -->
    <VisitDetailDrawer
      v-model="detailVisible"
      :visit-id="activeVisit?.id"
      @changed="onPlanChanged"
      @reschedule="onDetailReschedule"
      @open-subject="goSubject"
    />

    <!-- 插入计划外访视 -->
    <el-dialog v-model="unscheduledVisible" title="插入计划外访视" width="500px">
      <el-form label-width="96px">
        <el-form-item label="受试者" required>
          <el-select v-model="unscheduled.subject_id" filterable placeholder="选择受试者" style="width:100%">
            <el-option
              v-for="s in enrollableSubjects" :key="s.subject_id"
              :label="`${s.masked_name}（${s.subject_code || s.screening_no}）`"
              :value="s.subject_id"
            />
          </el-select>
        </el-form-item>
        <el-form-item label="访视名称" required>
          <el-input v-model="unscheduled.name" maxlength="64" show-word-limit
                    placeholder="如：计划外·发热急诊评估" />
        </el-form-item>
        <el-form-item label="计划日期" required>
          <el-date-picker v-model="unscheduled.date" type="date" value-format="YYYY-MM-DD"
                          :clearable="false" style="width:100%" />
        </el-form-item>
        <el-form-item label="随访窗">
          <div style="display:flex; align-items:center; gap:6px">
            前 <el-input-number v-model="unscheduled.window_before" :min="0" :max="60" size="small" />
            后 <el-input-number v-model="unscheduled.window_after" :min="0" :max="60" size="small" /> 天
          </div>
        </el-form-item>
        <el-form-item label="插入原因" required>
          <el-input v-model="unscheduled.reason" type="textarea" :rows="3" maxlength="200"
                    show-word-limit placeholder="必须填写原因（不少于 5 个字），将写入留痕" />
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="unscheduledVisible = false">取消</el-button>
        <el-button type="primary" :loading="unscheduledBusy" :disabled="!canAddUnscheduled" @click="submitUnscheduled">
          插入并重算下游
        </el-button>
      </template>
    </el-dialog>

    <!-- 方案修订发布（DM） -->
    <RevisionDialog v-model="revisionVisible" @published="onPlanChanged" />
  </div>
</template>

<script setup>
import { computed, onMounted, reactive, ref } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { ElMessage } from 'element-plus'
import {
  ArrowLeft, ArrowRight, Download, Plus, DocumentChecked, InfoFilled, Close,
} from '@element-plus/icons-vue'
import { metaApi, visitPlanApi } from '@/api'
import { useAuthStore } from '@/stores/auth'
import { useVisitPlan } from '@/composables/useVisitPlan'
import ErrorState from '@/components/ErrorState.vue'
import VisitGantt from '@/components/visit/VisitGantt.vue'
import VisitTablet from '@/components/visit/VisitTablet.vue'
import VisitMobile from '@/components/visit/VisitMobile.vue'
import RescheduleDialog from '@/components/visit/RescheduleDialog.vue'
import VisitDetailDrawer from '@/components/visit/VisitDetailDrawer.vue'
import RevisionDialog from '@/components/visit/RevisionDialog.vue'

const router = useRouter()
const route = useRoute()
const auth = useAuthStore()
const plan = useVisitPlan()
const data = plan.data
const viewMode = plan.view

const sites = ref([])
const focusChip = computed(() => {
  const id = plan.subjectId.value
  if (!id || !data.value) return null
  return data.value.subjects[0]?.masked_name || `受试者 #${id}`
})

const detailVisible = ref(false)
const rescheduleVisible = ref(false)
const activeVisit = ref(null)
const activeSubject = ref(null)
const rescheduleDate = ref('')

const unscheduledVisible = ref(false)
const unscheduledBusy = ref(false)
const unscheduled = reactive({
  subject_id: null, name: '', date: '', window_before: 3, window_after: 3, reason: '',
})
const revisionVisible = ref(false)
const exporting = ref(false)

const mixedSubjects = computed(() => (data.value?.subjects || []).filter((s) => s.mixed_versions))
const enrollableSubjects = computed(() =>
  (data.value?.subjects || []).filter((s) => s.subject_code))

const canAddUnscheduled = computed(() =>
  unscheduled.subject_id && unscheduled.name.trim().length >= 2
  && unscheduled.date && unscheduled.reason.trim().length >= 5)

onMounted(async () => {
  const q = route.query.subject
  if (q) plan.subjectId.value = Number(q)
  plan.load()
  try {
    sites.value = await metaApi.sites()
  } catch {
    sites.value = []
  }
})

function clearFocus() {
  plan.subjectId.value = null
  router.replace({ name: 'visit-plan' })
  plan.load()
}

function openDetail(visit, subject) {
  activeVisit.value = visit
  activeSubject.value = subject
  detailVisible.value = true
}
function goSubject(id) {
  router.push(`/subjects/${id}`)
}

function onRequestReschedule(visit, subject, date) {
  activeVisit.value = visit
  activeSubject.value = subject
  rescheduleDate.value = date
  rescheduleVisible.value = true
}
function onDetailReschedule(visit) {
  // 详情抽屉里发起改期：以当前计划日为初始值
  activeVisit.value = visit
  activeSubject.value = data.value?.subjects.find((s) => s.subject_id === visit.subject_id) || activeSubject.value
  rescheduleDate.value = visit.planned_date
  detailVisible.value = false
  rescheduleVisible.value = true
}
function onPlanChanged() {
  plan.load()
}

function openUnscheduled() {
  Object.assign(unscheduled, {
    subject_id: null, name: '', date: data.value?.today_local || '',
    window_before: 3, window_after: 3, reason: '',
  })
  unscheduledVisible.value = true
}
async function submitUnscheduled() {
  if (!canAddUnscheduled.value) return
  unscheduledBusy.value = true
  try {
    const r = await visitPlanApi.unscheduled({ ...unscheduled })
    ElMessage.success(r.message)
    unscheduledVisible.value = false
    plan.load()
  } catch (e) {
    ElMessage.error(e.message || '插入失败')
  } finally {
    unscheduledBusy.value = false
  }
}

async function doExport() {
  exporting.value = true
  try {
    const blob = await visitPlanApi.exportCsv(plan.siteId.value ? { site_id: plan.siteId.value } : {})
    const url = URL.createObjectURL(blob)
    const a = document.createElement('a')
    a.href = url
    a.download = `visit-plan-${data.value?.today_local || ''}.csv`
    a.click()
    URL.revokeObjectURL(url)
  } catch (e) {
    ElMessage.error(e.message || '导出失败')
  } finally {
    exporting.value = false
  }
}
</script>

<style scoped>
.vp-head { display: flex; justify-content: space-between; align-items: flex-end; gap: 12px; flex-wrap: wrap; }
.vp-actions { display: flex; align-items: center; gap: 8px; flex-wrap: wrap; }
.vp-body { margin-top: 14px; min-height: 300px; }
.vp-banner { margin-bottom: 12px; }
.focus-chip {
  display: flex; align-items: center; gap: 8px;
  background: var(--brand-50); border: 1px solid var(--brand-250);
  color: var(--brand-700); border-radius: 8px; padding: 8px 14px;
  margin-bottom: 12px; font-size: 13px;
}
.banner-line { display: flex; align-items: center; gap: 6px; flex-wrap: wrap; font-size: 12.5px; }
.banner-line.basis { margin-top: 4px; color: var(--ink-2); line-height: 1.7; }
@media (max-width: 640px) {
  .vp-actions { width: 100%; }
  .vp-actions .el-select { flex: 1; width: auto !important; }
}
</style>
