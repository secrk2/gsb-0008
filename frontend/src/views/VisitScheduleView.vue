<template>
  <div v-loading="loading">
    <div style="display:flex; align-items:center; gap:10px; flex-wrap:wrap">
      <el-button :icon="ArrowLeft" text @click="$router.push('/visit-plans')">返回访视计划</el-button>
      <h2 class="page-title" style="font-size:18px">受试者访视日程</h2>
    </div>

    <ErrorState v-if="forbidden" type="forbidden" title="越权访问已拦截" :message="forbidden"
                style="margin-top:16px">
      <el-button type="primary" @click="$router.push('/visit-plans')">返回访视计划</el-button>
    </ErrorState>
    <ErrorState v-else-if="notFound" type="empty" title="受试者不存在" :message="notFound"
                style="margin-top:16px">
      <el-button type="primary" @click="$router.push('/visit-plans')">返回访视计划</el-button>
    </ErrorState>
    <ErrorState v-else-if="errorMsg" type="warn" title="访视日程加载失败" :message="errorMsg"
                style="margin-top:16px">
      <el-button type="primary" @click="load">重试</el-button>
    </ErrorState>

    <template v-else-if="data">
      <!-- 身份 + 完成度 -->
      <div class="card subj-head">
        <div>
          <div class="sh-name">
            <router-link :to="`/subjects/${data.subject_id}`" class="sh-link">
              {{ data.masked_name }}
            </router-link>
            <el-tag size="small" effect="plain">{{ data.site_name }}（{{ data.site_code }}）</el-tag>
            <el-tag size="small" type="info">{{ data.subject_status_label }}</el-tag>
            <el-tag v-if="data.enroll_date" size="small" type="success" effect="plain">
              随机化/入组 {{ data.enroll_date }}
            </el-tag>
          </div>
          <div class="sh-sub">筛选号 {{ data.screening_no }} · 时区 {{ data.site_timezone }}</div>
        </div>
        <div class="sh-comp">
          <div class="sh-rate num-mono">{{ data.completion.rate }}%</div>
          <div class="sh-rate-sub">
            关键表单 {{ data.completion.key_done }}/{{ data.completion.key_total }} 张
          </div>
          <el-tooltip placement="topEnd">
            <template #content>
              <div style="max-width:260px; line-height:1.7">
                若改按“已提交字段数”计算为 {{ data.completion.field_rate }}%
                （{{ data.completion.field_submitted }}/{{ data.completion.field_total }} 字段），
                该口径会把只填半张表的访视也算成有进度，本平台不采用；
                正式完成度一律以关键表单个为准。
              </div>
            </template>
            <el-link type="primary" :underline="false" style="font-size:12px">
              字段口径对照为 {{ data.completion.field_rate }}%（不采用）ⓘ
            </el-link>
          </el-tooltip>
        </div>
      </div>

      <!-- 跨方案版本并存：显眼横幅 -->
      <el-alert v-if="data.mixed_versions" type="error" show-icon :closable="false"
                style="margin-top:14px" class="mixed-alert">
        <template #title>
          <b>该受试者正跨方案版本随访：</b>
          已完成的 {{ data.mixed_versions.frozen_visit_nos.join('、') || '早期访视' }}
          冻结在 {{ data.mixed_versions.old_label }} 原样保留；尚未发生的访视已切换到
          {{ data.mixed_versions.new_label }}。新旧两版的相对天数/窗口可能不同，
          请以各访视上的版本角标为准，勿按单一版本推算。
        </template>
      </el-alert>

      <!-- 口径条 -->
      <div class="basis-bar">
        <el-icon><InfoFilled /></el-icon>
        <span>
          <b>排程口径：</b>名义计划日＝随机化日期＋方案相对天数（金色虚线）；
          发生改期/跳过/计划外访视后，现行计划日改按上一次实际访视日链式重算（彩色访视块）。
          <b>完成度：</b>按已完成关键表单数计算。
        </span>
        <el-popover placement="bottom-end" :width="400" trigger="click">
          <template #reference><el-button size="small" text type="primary">完整口径说明</el-button></template>
          <div class="policy-pop">
            <div class="pp-h">完成度</div><p>{{ policy?.completion_policy_text }}</p>
            <div class="pp-h">排程口径</div><p>{{ policy?.anchor_policy_text }}</p>
            <div class="pp-h">修订冻结</div><p>{{ policy?.amendment_freeze_text }}</p>
          </div>
        </el-popover>
      </div>

      <!-- 操作行 -->
      <div class="act-row">
        <h3 style="margin:0">访视日程（{{ data.visits.length }}）</h3>
        <div>
          <el-button type="primary" plain :icon="Plus" :disabled="!data.can_edit"
                     @click="openInsert">插入计划外访视</el-button>
        </div>
      </div>

      <!-- 空态 1：尚无任何访视 -->
      <ErrorState v-if="data.empty_kind === 'no_visits'" type="empty"
                  title="该受试者尚无任何访视安排"
                  message="受试者还没有生成任何方案访视（可能尚未入组/随机化）。入组后系统将按方案相对天数自动生成 V0 起的访视计划；如确有医学需要，可在上方插入计划外访视。"
                  style="margin-top:12px" />
      <!-- 空态 2：访视被全部跳过 -->
      <ErrorState v-else-if="data.empty_kind === 'all_skipped'" type="empty"
                  title="该受试者的访视已全部跳过"
                  message="该受试者的全部方案访视都处于“已跳过”状态（方案允许的跳过，不是失访）。请在下方排程留痕中核对每次跳过的原因；如等待行政结案，请尽快完成脱落/中止等状态处理。"
                  style="margin-top:12px" />

      <template v-else>
        <!-- 访视卡片时间线 -->
        <div class="visit-timeline">
          <div v-for="v in data.visits" :key="v.id" :class="['v-card', 'card', { skipped: v.status === 'skipped', locked: v.locked }]">
            <div class="vc-main">
              <div class="vc-left">
                <div class="vc-no">
                  <span class="num-mono">{{ v.visit_no }}</span>
                  <el-tag size="small" effect="plain">{{ v.version_label || '—' }}</el-tag>
                  <el-tag v-if="v.kind === 'unscheduled'" size="small" type="primary" effect="dark">计划外</el-tag>
                  <el-tag v-if="v.locked" size="small" type="warning" effect="dark">
                    <el-icon style="vertical-align:-1px"><Lock /></el-icon> 已锁库
                  </el-tag>
                </div>
                <div class="vc-name">{{ v.name }}</div>
                <div class="vc-dates">
                  <span>现行计划 <b class="num-mono">{{ v.planned_date }}</b></span>
                  <span class="vc-window">窗 前{{ v.window_before }}/后{{ v.window_after }} 天</span>
                  <span v-if="v.actual_date">实际 <b class="num-mono">{{ v.actual_date }}</b></span>
                  <span v-if="v.day_offset !== null" class="vc-day">相对随机化 {{ fmtSigned(v.day_offset) }} 天</span>
                </div>
                <div v-if="v.divergence_days !== 0" class="vc-diverge">
                  随机化口径名义日 {{ v.nominal_date }}（与现行计划差 {{ v.divergence_days }} 天，
                  由改期/计划外访视链式重算产生）
                </div>
                <div v-if="v.insert_reason" class="vc-reason">计划外原因：{{ v.insert_reason }}</div>
              </div>
              <div class="vc-right">
                <span :class="['visit-chip', v.visit_state]">● {{ v.visit_state_label }}</span>
                <div class="vc-comp">
                  <el-progress type="circle" :width="56" :percentage="v.completion.rate"
                               :status="v.completion.rate === 100 ? 'success' : ''" />
                  <div class="vc-comp-sub num-mono">
                    {{ v.completion.key_done }}/{{ v.completion.key_total }} 关键表单
                  </div>
                </div>
                <div class="vc-ops">
                  <el-button size="small" :disabled="!v.can_edit"
                             @click="openReschedule(v)">改期</el-button>
                  <el-button size="small" type="warning" plain :disabled="!v.can_skip"
                             @click="openSkip(v)">跳过</el-button>
                </div>
              </div>
            </div>

            <!-- 关键表单明细 -->
            <div class="vc-forms">
              <div class="vcf-h">关键表单完成明细（完成度按表单个计，半张表不计完成）</div>
              <div class="vcf-grid">
                <div v-for="f in v.forms" :key="f.form_code" :class="['form-pill', f.status]">
                  <span class="fp-name">{{ f.form_name }}</span>
                  <span class="fp-state">{{ f.status_label }}</span>
                  <span v-if="f.status !== 'formula'" class="fp-fields num-mono">
                    {{ f.submitted_fields }}/{{ f.field_total }} 字段
                  </span>
                </div>
                <div v-if="!v.forms.length" class="vcf-empty">该访视暂无表单目录</div>
              </div>
            </div>
          </div>
        </div>
      </template>

      <!-- 排程留痕 -->
      <div class="card audit-card">
        <h3>排程与锁库留痕（{{ data.audits.length }}）</h3>
        <el-alert type="info" :closable="false" style="margin-bottom:10px"
                  title="所有改期（含超窗强制原因）、跳过、计划外访视、链式重算、修订切换、锁库均只追加留痕，不可删除或改写。时间按研究中心所在时区显示。" />
        <el-timeline>
          <el-timeline-item v-for="a in data.audits" :key="a.id" :timestamp="a.created_at"
                            placement="top"
                            :type="a.action.includes('out_of_window') ? 'danger' : 'primary'">
            <div style="font-weight:600">{{ a.action_label }}</div>
            <div v-if="a.old_date || a.new_date" class="num-mono" style="font-size:12px; margin:2px 0">
              {{ a.old_date || '—' }} → {{ a.new_date || '—' }}
            </div>
            <div v-if="a.reason" style="font-size:12.5px">原因：{{ a.reason }}</div>
            <div v-if="a.detail" style="font-size:12px; color:var(--ink-3); margin-top:2px">{{ a.detail }}</div>
            <div style="font-size:12px; color:var(--ink-3); margin-top:2px">操作人：{{ a.operator_name }}</div>
          </el-timeline-item>
        </el-timeline>
      </div>
    </template>

    <VisitActionDialogs ref="dialogs" @changed="load" />
  </div>
</template>

<script setup>
import { onMounted, ref } from 'vue'
import { useRoute } from 'vue-router'
import { ArrowLeft, InfoFilled, Lock, Plus } from '@element-plus/icons-vue'
import { visitPlanApi } from '@/api'
import ErrorState from '@/components/ErrorState.vue'
import VisitActionDialogs from '@/components/VisitActionDialogs.vue'

const route = useRoute()
const dialogs = ref(null)
const loading = ref(false)
const data = ref(null)
const policy = ref(null)
const errorMsg = ref('')
const forbidden = ref('')
const notFound = ref('')

async function load() {
  loading.value = true
  errorMsg.value = forbidden.value = notFound.value = ''
  try {
    const [d, pol] = await Promise.all([
      visitPlanApi.subjectVisits(route.params.id),
      visitPlanApi.policy().catch(() => null),
    ])
    data.value = d
    policy.value = pol
  } catch (e) {
    data.value = null
    if (e.status === 403) forbidden.value = e.message
    else if (e.status === 404) notFound.value = e.message
    else errorMsg.value = e.message
  } finally {
    loading.value = false
  }
}

function fmtSigned(n) { return n > 0 ? `+${n}` : `${n}` }
function openReschedule(v) {
  dialogs.value.openReschedule({ visit: v, subjectName: data.value.masked_name })
}
function openSkip(v) { dialogs.value.openSkip({ visit: v }) }
function openInsert() {
  dialogs.value.openInsert({ subjectId: data.value.subject_id, theDate: data.value.today })
}

onMounted(load)
</script>

<style scoped>
.subj-head {
  margin-top:12px; padding:16px 18px;
  display:flex; justify-content:space-between; align-items:center; gap:16px; flex-wrap:wrap;
}
.sh-name { display:flex; align-items:center; gap:8px; font-size:18px; font-weight:700; flex-wrap:wrap; }
.sh-link { color:var(--brand-600); text-decoration:none; }
.sh-link:hover { text-decoration:underline; }
.sh-sub { color:var(--ink-3); font-size:12px; margin-top:6px; }
.sh-comp { text-align:right; }
.sh-rate { font-size:30px; font-weight:700; color:var(--brand-600); line-height:1; }
.sh-rate-sub { font-size:12px; color:var(--ink-3); margin:4px 0 2px; }

.mixed-alert { border-width:2px; }
.basis-bar {
  margin-top:12px; display:flex; gap:8px; align-items:center;
  background:var(--status-info-bg); border:1px solid #cfe0f6; border-radius:8px;
  padding:9px 12px; font-size:12.5px; color:#274b76; line-height:1.7;
}
.basis-bar > span { flex:1; }
.act-row { display:flex; justify-content:space-between; align-items:center; margin:18px 0 10px; }

.visit-timeline { display:flex; flex-direction:column; gap:12px; }
.v-card { padding:14px 16px; }
.v-card.skipped { opacity:0.92; background: repeating-linear-gradient(0deg, #fbfbfc, #fbfbfc 14px, #f6f7f9 14px, #f6f7f9 28px), #fff; }
.v-card.locked { border-color:#d9b56a; box-shadow:0 0 0 1px #ecd9a6 inset; }
.vc-main { display:flex; justify-content:space-between; gap:16px; flex-wrap:wrap; }
.vc-left { min-width:240px; flex:1; }
.vc-no { display:flex; align-items:center; gap:8px; font-size:16px; font-weight:700; }
.vc-name { font-weight:600; margin:6px 0; }
.vc-dates { display:flex; gap:14px; flex-wrap:wrap; font-size:12.5px; color:var(--ink-2); }
.vc-window { color:var(--ink-3); }
.vc-day { color:var(--ink-3); }
.vc-diverge { font-size:12px; color:#8a6d2a; margin-top:6px; }
.vc-reason { font-size:12px; color:var(--brand-700); margin-top:6px; }
.vc-right { display:flex; flex-direction:column; align-items:flex-end; gap:8px; }
.vc-comp { display:flex; flex-direction:column; align-items:center; gap:2px; }
.vc-comp-sub { font-size:11px; color:var(--ink-3); }
.vc-ops { display:flex; gap:6px; }

.vc-forms { margin-top:12px; border-top:1px dashed var(--border); padding-top:10px; }
.vcf-h { font-size:12px; color:var(--ink-3); margin-bottom:8px; }
.vcf-grid { display:flex; flex-direction:column; gap:6px; }
.form-pill {
  display:flex; align-items:center; gap:12px;
  border:1px solid var(--border); border-radius:7px; padding:6px 10px; font-size:12.5px;
  background:#fcfdfe;
}
.form-pill .fp-name { flex:1; font-weight:600; }
.form-pill .fp-state { color:var(--ink-3); }
.form-pill.complete { border-color:#bfe3bf; background:var(--status-good-bg); }
.form-pill.complete .fp-state { color:#0b6b2c; font-weight:600; }
.form-pill.in_progress { border-color:#ecd7a6; background:var(--status-warning-bg); }
.form-pill.in_progress .fp-state { color:#8a6400; font-weight:600; }
.form-pill.formula { background:#f3f0fa; border-color:#ddd3f0; }
.vcf-empty { font-size:12px; color:var(--ink-3); }

.audit-card { margin-top:18px; padding:14px 18px; }
.policy-pop { font-size:12.5px; color:var(--ink-2); line-height:1.7; }
.pp-h { font-weight:700; color:var(--ink-1); margin:6px 0 2px; }
.policy-pop p { margin:0 0 6px; }

@media (max-width:640px) {
  .vc-right { align-items:flex-start; }
  .sh-comp { text-align:left; }
}
</style>
