<template>
  <div v-loading="loading">
    <div style="display:flex; align-items:center; gap:10px; flex-wrap:wrap">
      <el-button :icon="ArrowLeft" text @click="$router.push('/subjects')">返回列表</el-button>
      <h2 class="page-title" style="font-size:18px">受试者链路</h2>
    </div>

    <ErrorState v-if="forbidden" type="forbidden" title="越权访问已拦截" :message="forbidden" style="margin-top:16px">
      <el-button type="primary" @click="$router.push('/subjects')">返回受试者列表</el-button>
    </ErrorState>
    <ErrorState v-else-if="notFound" type="empty" title="受试者不存在" :message="notFound" style="margin-top:16px">
      <el-button type="primary" @click="$router.push('/subjects')">返回受试者列表</el-button>
    </ErrorState>
    <ErrorState v-else-if="errorMsg" type="warn" title="详情加载失败" :message="errorMsg" style="margin-top:16px">
      <el-button type="primary" @click="load">重试</el-button>
    </ErrorState>

    <template v-else-if="subject">
      <!-- 头部：脱敏身份卡 -->
      <div class="card" style="margin-top:12px; padding:18px 20px; display:flex; gap:18px; align-items:center; flex-wrap:wrap">
        <el-avatar :size="54" style="background:var(--brand-500); font-size:22px">
          {{ subject.display_name.slice(0, 1) }}
        </el-avatar>
        <div style="flex:1; min-width:220px">
          <div style="display:flex; align-items:center; gap:10px; flex-wrap:wrap">
            <span style="font-size:20px; font-weight:700">{{ subject.display_name }}</span>
            <StatusTag :status="subject.status" :label-map="labelMap" />
            <el-tag size="small" effect="plain">{{ subject.site_name }}（{{ subject.site_code }}）</el-tag>
          </div>
          <div style="color:var(--ink-3); font-size:12px; margin-top:5px">
            筛选号 {{ subject.screening_no }}
            <template v-if="subject.subject_code"> · 受试者编号 {{ subject.subject_code }}</template>
            · 姓名已按 GCP 脱敏，仅本中心研究者可申请查看全名
          </div>
        </div>
        <div style="display:flex; flex-direction:column; gap:8px; align-items:flex-end">
          <el-button v-if="subject.can_reveal" type="danger" plain :icon="View" @click="openReveal">
            申请查看全名
          </el-button>
          <el-tooltip v-else content="仅本中心研究者可查看全名（数据管理员/监查员无权）" placement="top">
            <el-button type="info" plain disabled :icon="View">查看全名（无权限）</el-button>
          </el-tooltip>
        </div>
      </div>

      <!-- reveal 临时结果 -->
      <el-alert v-if="revealed" type="warning" :closable="true" style="margin-top:12px" @close="revealed = null">
        <template #title>
          <span>本次授权查看：受试者全名 <b class="reveal-name">{{ revealed.full_name }}</b>（仅本次会话临时显示，离开页面即失效）。{{ revealed.message }}</span>
        </template>
      </el-alert>

      <!-- 状态机 -->
      <div class="card section-card" style="margin-top:16px">
        <h3><el-icon><Share /></el-icon>状态机与状态操作
          <span style="font-weight:400; color:var(--ink-3); font-size:12px">非法回退将被系统拦截并说明原因</span>
        </h3>

        <StateMachine :status="subject.status" />

        <div style="display:flex; gap:10px; flex-wrap:wrap; margin-top:14px">
          <el-button v-for="a in actionButtons" :key="a.value"
                     :type="a.btnType" :plain="a.plain"
                     :disabled="!subject.allowed_actions.includes(a.value)"
                     @click="openTransition(a)">
            {{ a.label }}
          </el-button>
          <span v-if="!subject.allowed_actions.length" style="color:var(--ink-3); font-size:13px">
            当前为终态（{{ labelMap[subject.status] }}），不允许任何状态变更或回退。
          </span>
        </div>
      </div>

      <!-- 页签 -->
      <div class="card" style="margin-top:16px">
        <el-tabs v-model="tab" style="padding: 6px 16px 16px">
          <!-- 基本信息 -->
          <el-tab-pane label="基本信息" name="info">
            <dl class="info-desc">
              <dt>所属中心</dt><dd>{{ subject.site_name }}（{{ subject.site_code }}）</dd>
              <dt>筛选号</dt><dd class="num-mono">{{ subject.screening_no }}</dd>
              <dt>受试者编号</dt><dd class="num-mono">{{ subject.subject_code || '入组时分配' }}</dd>
              <dt>脱敏姓名</dt><dd>{{ subject.display_name }}</dd>
              <dt>性别</dt><dd>{{ subject.gender }}</dd>
              <dt>出生日期</dt><dd class="num-mono">{{ subject.birth_date || '—' }}</dd>
              <dt>联系电话</dt><dd class="num-mono">{{ subject.phone_masked || '—' }}（脱敏）</dd>
              <dt>筛选日期</dt><dd class="num-mono">{{ subject.screen_date }}</dd>
              <dt>入组日期</dt><dd class="num-mono">{{ subject.enroll_date || '—' }}</dd>
              <dt>完成日期</dt><dd class="num-mono">{{ subject.completion_date || '—' }}</dd>
              <dt>终止日期</dt><dd class="num-mono">{{ subject.end_date || '—' }}</dd>
            </dl>
          </el-tab-pane>

          <!-- 访视计划 -->
          <el-tab-pane :label="`访视计划（${subject.visits.length}）`" name="visits">
            <el-alert
              v-if="subject.mixed_versions"
              type="warning" :closable="false" show-icon style="margin-bottom:12px"
              title="⚠ 该受试者新旧方案并存：已完成/已跳过/锁库访视冻结在旧版本，未发生访视已切换新版本（见版本列）。"
            />
            <el-alert type="success" :closable="false" style="margin-bottom:12px"
                      :title="subject.completion_basis" />
            <div class="visit-completion">
              <span>访视关键表单总完成度</span>
              <el-progress :percentage="subject.completion_percent" :stroke-width="12"
                           style="flex:1; max-width:320px" />
              <b class="num-mono">{{ subject.completion_percent }}%（{{ subject.completion_label }}）</b>
              <el-button type="primary" link @click="$router.push({ path: '/visit-plan', query: { subject: subject.id } })">在访视计划中查看甘特/改期 →</el-button>
            </div>
            <el-alert type="info" :closable="false" style="margin:10px 0"
                      :title="`排程口径：${subject.policy_label}`" />
            <div class="table-scroll">
              <el-table :data="subject.visits" size="small"
                        :row-class-name="(r) => r.row.locked ? 'locked-row' : ''">
                <el-table-column prop="visit_no" label="访视" width="68" />
                <el-table-column prop="name" label="名称" min-width="120" />
                <el-table-column label="版本" width="92">
                  <template #default="{ row }">
                    <el-tag size="small"
                            :type="row.version === subject.active_version ? 'success' : 'danger'"
                            effect="plain">
                      {{ row.version === subject.active_version ? '当前' : '旧版' }} {{ row.version }}
                    </el-tag>
                  </template>
                </el-table-column>
                <el-table-column label="类型" width="80">
                  <template #default="{ row }">
                    <el-tag size="small" :type="row.kind === 'unscheduled' ? 'warning' : 'info'" effect="plain">
                      {{ row.kind_label }}
                    </el-tag>
                  </template>
                </el-table-column>
                <el-table-column label="计划日期" width="106">
                  <template #default="{ row }">
                    <span class="num-mono">{{ row.planned_date }}</span>
                    <el-icon v-if="row.pinned" title="手动改期已钉住" color="var(--status-warning)" style="vertical-align:-2px">
                      <Top />
                    </el-icon>
                  </template>
                </el-table-column>
                <el-table-column label="随访窗" width="100">
                  <template #default="{ row }">前{{ row.window_before }}/后{{ row.window_after }}</template>
                </el-table-column>
                <el-table-column label="状态" width="104">
                  <template #default="{ row }">
                    <span :class="['visit-chip', row.visit_state]">● {{ row.visit_state_label }}</span>
                  </template>
                </el-table-column>
                <el-table-column label="实际日期" width="104">
                  <template #default="{ row }"><span class="num-mono">{{ row.actual_date || '—' }}</span></template>
                </el-table-column>
                <el-table-column label="关键表单" width="84">
                  <template #default="{ row }">
                    <span class="num-mono">{{ row.key_form_done }}/{{ row.key_form_total }}</span>
                  </template>
                </el-table-column>
                <el-table-column label="锁/锚点" width="90">
                  <template #default="{ row }">
                    <el-tag v-if="row.locked" size="small" type="danger" effect="dark">锁库</el-tag>
                    <el-tooltip v-else :content="row.anchor_mode_label" placement="top">
                      <el-tag size="small" effect="plain">{{ row.anchor_mode === 'randomization' ? '随机化' : '上次实际' }}</el-tag>
                    </el-tooltip>
                  </template>
                </el-table-column>
              </el-table>
            </div>
            <div v-if="subject.visits.some((v) => v.anchor?.conflict)"
                 class="conflict-note">
              <el-icon><WarningFilled /></el-icon>
              部分访视的「随机化方案日」与「上次实际访视日推算日」不一致，已按研究统一口径
              （{{ subject.policy_label }}）取值，备选日期见访视详情，请勿自行猜测。
            </div>
          </el-tab-pane>

          <!-- 状态留痕 -->
          <el-tab-pane :label="`状态留痕（${subject.histories.length}）`" name="history">
            <el-timeline style="margin-top:10px">
              <el-timeline-item v-for="h in subject.histories" :key="h.id"
                                :timestamp="fmtTime(h.created_at)" placement="top"
                                :type="h.to_status === 'removed' ? 'danger' : 'primary'">
                <div style="font-weight:600">
                  {{ h.action_label }}：
                  <span v-if="h.from_status_label">{{ h.from_status_label }} →</span>
                  {{ h.to_status_label }}
                </div>
                <div v-if="h.reason" class="audit-reason">原因/说明：{{ h.reason }}</div>
                <div style="font-size:12px; color:var(--ink-3); margin-top:2px">操作人：{{ h.operator_name }}</div>
              </el-timeline-item>
            </el-timeline>
          </el-tab-pane>

          <!-- 号码留痕 -->
          <el-tab-pane :label="`号码留痕（${subject.number_audits.length}）`" name="numbers">
            <el-alert type="info" :closable="false" style="margin-bottom:12px"
                      title="号码按「中心前缀 + 顺序号」分配；作废号码推进游标、永不再分配，所有分配/作废操作在此留痕。" />
            <el-table :data="subject.number_audits" size="small"
                      :row-class-name="(r) => r.row.status === 'voided' ? 'void-row' : ''">
              <el-table-column prop="kind_label" label="号码类型" width="100" />
              <el-table-column prop="number" label="号码" width="120">
                <template #default="{ row }"><b class="num-mono">{{ row.number }}</b></template>
              </el-table-column>
              <el-table-column label="状态" width="110">
                <template #default="{ row }">
                  <el-tag :type="row.status === 'voided' ? 'danger' : 'success'" size="small">
                    {{ row.status_label }}
                  </el-tag>
                </template>
              </el-table-column>
              <el-table-column prop="reason" label="原因/说明" min-width="220" />
              <el-table-column prop="operator_name" label="操作人" width="100" />
              <el-table-column label="时间" width="160">
                <template #default="{ row }">{{ fmtTime(row.created_at) }}</template>
              </el-table-column>
            </el-table>
          </el-tab-pane>

          <!-- 全名查看留痕 -->
          <el-tab-pane :label="`全名查看记录（${subject.pii_view_logs.length}）`" name="pii">
            <el-alert type="warning" :closable="false" style="margin-bottom:12px"
                      title="依据 GCP 最小必要原则，受试者全名默认脱敏；每一次解除脱敏都记录操作人、时间与理由，可供稽查/监查溯源。" />
            <el-table :data="subject.pii_view_logs" size="small" :empty-text="'暂无全名查看记录'">
              <el-table-column prop="viewer_name" label="查看人" width="110" />
              <el-table-column prop="viewer_username" label="账号" width="120" />
              <el-table-column prop="reason" label="查看理由" min-width="260" />
              <el-table-column label="查看时间" width="170">
                <template #default="{ row }">{{ fmtTime(row.created_at) }}</template>
              </el-table-column>
            </el-table>
          </el-tab-pane>
        </el-tabs>
      </div>
    </template>

    <!-- 状态变更弹窗（含原因 + 二次确认） -->
    <el-dialog v-model="transitionVisible" :title="`确认执行：${activeAction?.label || ''}`" width="500px">
      <el-alert v-if="activeAction" :type="activeAction.danger ? 'error' : 'warning'" :closable="false" style="margin-bottom:14px">
        <template #title>
          <div>{{ activeAction.confirmText }}</div>
          <div v-if="activeAction.value === 'enroll'" style="margin-top:4px; font-size:12px">
            入组后系统将分配受试者编号（{{ subject?.site_code }}-顺序号），列表姓名将自动转为「缩写+编号」脱敏展示。
          </div>
        </template>
      </el-alert>
      <el-form label-width="86px">
        <el-form-item v-if="reasonRequired" label="变更原因" required>
          <el-input v-model="transitionReason" type="textarea" :rows="3" maxlength="200" show-word-limit
                    placeholder="请填写原因（将写入稽查轨迹，必填）" />
        </el-form-item>
        <el-form-item label="二次确认">
          <el-checkbox v-model="transitionConfirm">我已知晓该状态变更将被留痕，且终态不可回退</el-checkbox>
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="transitionVisible = false">取消</el-button>
        <el-button :type="activeAction?.danger ? 'danger' : 'primary'" :loading="transitioning" @click="submitTransition">
          确认执行
        </el-button>
      </template>
    </el-dialog>

    <!-- 非法状态回退拦截说明弹窗 -->
    <el-dialog v-model="illegalVisible" title="操作已被拦截" width="480px">
      <div style="display:flex; gap:12px; align-items:flex-start">
        <el-icon :size="26" color="var(--status-critical)" style="margin-top:2px"><CircleCloseFilled /></el-icon>
        <div>
          <div style="font-weight:600; margin-bottom:6px">系统拒绝了本次状态变更</div>
          <div style="color:var(--ink-2); line-height:1.8; font-size:13px">{{ illegalMessage }}</div>
        </div>
      </div>
      <template #footer>
        <el-button type="primary" @click="illegalVisible = false">我知道了</el-button>
      </template>
    </el-dialog>

    <!-- 查看全名弹窗（二次确认 + 理由） -->
    <el-dialog v-model="revealVisible" title="受试者全名查看授权" width="500px">
      <el-alert type="error" :closable="false" style="margin-bottom:14px">
        <template #title>
          受试者姓名属于受保护个人信息（PII）。本次查看将记录<b>操作人、时间、理由</b>到稽查轨迹，监查与稽查可随时溯源，请仅在必要时查看。
        </template>
      </el-alert>
      <el-form label-width="86px">
        <el-form-item label="受试者">
          <span>{{ subject?.display_name }}（{{ subject?.screening_no }}）</span>
        </el-form-item>
        <el-form-item label="查看理由" required>
          <el-input v-model="revealReason" type="textarea" :rows="3" maxlength="200" show-word-limit
                    placeholder="请说明查看全名的业务理由（不少于 5 个字），例如：SDV 源数据核查核对病历" />
        </el-form-item>
        <el-form-item label="二次确认">
          <el-checkbox v-model="revealConfirm">我确认本次查看出于合规业务需要，并同意留痕</el-checkbox>
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="revealVisible = false">取消</el-button>
        <el-button type="danger" :loading="revealing" :disabled="!canSubmitReveal" @click="submitReveal">
          确认查看并留痕
        </el-button>
      </template>
    </el-dialog>
  </div>
</template>

<script setup>
import { computed, onMounted, ref } from 'vue'
import { useRoute } from 'vue-router'
import { ElMessage } from 'element-plus'
import {
  ArrowLeft, View, Share, CircleCloseFilled, Top, WarningFilled,
} from '@element-plus/icons-vue'
import { subjectApi } from '@/api'
import StatusTag from '@/components/StatusTag.vue'
import ErrorState from '@/components/ErrorState.vue'
import StateMachine from '@/components/StateMachine.vue'

const route = useRoute()
const loading = ref(false)
const subject = ref(null)
const labelMap = ref({})
const errorMsg = ref('')
const forbidden = ref('')
const notFound = ref('')
const tab = ref('info')

const ACTION_DEFS = {
  enroll: { label: '入组', btnType: 'primary', plain: false, danger: false,
    confirmText: '确认该受试者完成筛选并正式入组？入组后将分配受试者编号，姓名进入脱敏展示。' },
  screen_fail: { label: '标记筛选失败', btnType: 'info', plain: true, danger: false, reason: true,
    confirmText: '确认标记筛选失败？该状态为终态，不能再入组，需填写失败原因。' },
  complete: { label: '完成研究', btnType: 'success', plain: false, danger: false,
    confirmText: '确认受试者已完成全部计划访视、完成研究？完成后为终态，不可回退。' },
  dropout: { label: '标记脱落', btnType: 'warning', plain: true, danger: false, reason: true,
    confirmText: '确认标记脱落？脱落为终态，须填写脱落原因（如失访、撤回知情同意）。' },
  terminate: { label: '中止研究', btnType: 'warning', plain: false, danger: true, reason: true,
    confirmText: '确认中止该受试者研究？中止为终态，须填写原因（如 SAE、研究者判断）。' },
  remove: { label: '剔除', btnType: 'danger', plain: false, danger: true, reason: true,
    confirmText: '确认剔除？剔除用于误纳等方案规定情形，为终态，必须填写依据并留痕。' },
}
const actionButtons = [
  { value: 'enroll', ...ACTION_DEFS.enroll },
  { value: 'screen_fail', ...ACTION_DEFS.screen_fail },
  { value: 'complete', ...ACTION_DEFS.complete },
  { value: 'dropout', ...ACTION_DEFS.dropout },
  { value: 'terminate', ...ACTION_DEFS.terminate },
  { value: 'remove', ...ACTION_DEFS.remove },
]

async function load() {
  loading.value = true
  errorMsg.value = forbidden.value = notFound.value = ''
  try {
    subject.value = await subjectApi.detail(route.params.id)
    const meta = await import('@/api').then((m) => m.metaApi.statuses()).catch(() => null)
    if (meta) labelMap.value = Object.fromEntries(meta.statuses.map((x) => [x.value, x.label]))
  } catch (e) {
    subject.value = null
    if (e.status === 403) forbidden.value = e.message
    else if (e.status === 404) notFound.value = e.message
    else errorMsg.value = e.message
  } finally {
    loading.value = false
  }
}
function fmtTime(t) { return t ? new Date(t).toLocaleString('zh-CN', { hour12: false }) : '—' }

// ---------------- 状态变更 ----------------
const transitionVisible = ref(false)
const transitioning = ref(false)
const activeAction = ref(null)
const transitionReason = ref('')
const transitionConfirm = ref(false)
const illegalVisible = ref(false)
const illegalMessage = ref('')
const reasonRequired = computed(() => !!activeAction.value?.reason)

function openTransition(a) {
  activeAction.value = a
  transitionReason.value = ''
  transitionConfirm.value = false
  transitionVisible.value = true
}
async function submitTransition() {
  if (reasonRequired.value && transitionReason.value.trim().length < 5) {
    ElMessage.warning('请填写变更原因（不少于 5 个字）')
    return
  }
  if (!transitionConfirm.value) {
    ElMessage.warning('请勾选二次确认')
    return
  }
  transitioning.value = true
  try {
    const res = await subjectApi.transition(subject.value.id, {
      action: activeAction.value.value,
      reason: transitionReason.value.trim() || null,
    })
    ElMessage.success(res.message)
    transitionVisible.value = false
    await load()
    tab.value = 'history'
  } catch (e) {
    transitionVisible.value = false
    if (e.status === 409 || e.status === 400) {
      // 非法状态回退：明确拦截原因
      illegalMessage.value = e.message
      illegalVisible.value = true
    } else if (e.status === 403) {
      illegalMessage.value = e.message
      illegalVisible.value = true
    } else {
      ElMessage.error(e.message || '操作失败')
    }
  } finally {
    transitioning.value = false
  }
}

// ---------------- 查看全名 ----------------
const revealVisible = ref(false)
const revealing = ref(false)
const revealReason = ref('')
const revealConfirm = ref(false)
const revealed = ref(null)
const canSubmitReveal = computed(() => revealReason.value.trim().length >= 5 && revealConfirm.value)

function openReveal() {
  revealReason.value = ''
  revealConfirm.value = false
  revealVisible.value = true
}
async function submitReveal() {
  if (!canSubmitReveal.value) return
  revealing.value = true
  try {
    const res = await subjectApi.reveal(subject.value.id, revealReason.value.trim())
    revealed.value = res
    revealVisible.value = false
    ElMessage.success('全名已临时显示，本次查看已留痕')
    await load()
    tab.value = 'pii'
  } catch (e) {
    if (e.status === 403) {
      revealVisible.value = false
      illegalMessage.value = e.message
      illegalVisible.value = true
    } else {
      ElMessage.error(e.message || '查看失败')
    }
  } finally {
    revealing.value = false
  }
}

onMounted(load)
</script>

<style scoped>
:deep(.void-row) { background: var(--status-critical-bg) !important; }
:deep(.void-row td) { color: #a52020; }
:deep(.locked-row) { background: #f7f8fa !important; }
:deep(.locked-row td) { color: var(--ink-3); }
.visit-completion { display: flex; align-items: center; gap: 12px; font-size: 13px; flex-wrap: wrap; }
.visit-completion b { color: var(--brand-700); font-size: 15px; }
.conflict-note {
  margin-top: 10px; font-size: 12px; color: var(--status-warning);
  display: flex; gap: 6px; align-items: flex-start; line-height: 1.7;
}
</style>
