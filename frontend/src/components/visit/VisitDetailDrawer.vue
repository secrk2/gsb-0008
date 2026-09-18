<template>
  <el-drawer
    :model-value="modelValue"
    title="访视详情"
    direction="rtl"
    size="46%"
    :z-index="1200"
    @update:model-value="$emit('update:modelValue', $event)"
  >
    <div v-loading="loading" style="padding: 0 4px">
      <ErrorState v-if="errorMsg" type="warn" title="访视详情加载失败" :message="errorMsg">
        <el-button type="primary" @click="load">重试</el-button>
      </ErrorState>

      <template v-else-if="d">
        <!-- 新旧方案并存醒目提示 -->
        <el-alert
          v-if="d.mixed_versions"
          type="warning" show-icon :closable="false" class="detail-banner"
          title="⚠ 该受试者身上新旧方案并存"
          description="方案修订发布前已完成 / 已跳过 / 已锁库的访视冻结在旧版本原样保留；修订后尚未发生的访视已切换到新版本。请按每个访视上标注的版本号执行与核查，不要混用两版要求。"
        />

        <div class="card detail-card">
          <div class="dc-head">
            <div>
              <div class="dc-title">
                {{ d.visit.visit_no }} {{ d.visit.name }}
                <el-tag size="small" :type="d.visit.kind === 'unscheduled' ? 'warning' : 'info'" effect="plain">
                  {{ d.visit.kind_label }}
                </el-tag>
                <el-tag
                  size="small"
                  :type="d.visit.version === d.active_version ? 'success' : 'danger'"
                  effect="plain"
                >
                  {{ d.visit.version === d.active_version ? '当前版本' : `旧版冻结 · ${d.visit.version}` }}
                </el-tag>
                <el-tag v-if="d.visit.locked" size="small" type="danger" effect="dark">
                  <el-icon style="vertical-align:-2px"><Lock /></el-icon> 已锁库
                </el-tag>
              </div>
              <div class="dc-sub num-mono">
                {{ d.masked_name }} · {{ d.subject_code || d.screening_no }} · {{ d.site_name }}
              </div>
            </div>
            <span :class="['visit-chip', d.visit.visit_state, 'dc-state']">
              ● {{ d.visit.visit_state_label }}
            </span>
          </div>

          <div class="dc-grid">
            <div><label>计划日期（中心本地）</label><b class="num-mono">{{ d.visit.planned_date }}</b></div>
            <div><label>实际访视日期</label><b class="num-mono">{{ d.visit.actual_date || '—' }}</b></div>
            <div><label>随访窗</label><b>前 {{ d.visit.window_before }} / 后 {{ d.visit.window_after }} 天</b></div>
            <div><label>相对锚点</label><b>第 {{ d.visit.offset_days }} 天 · {{ d.visit.anchor_mode_label }}</b></div>
            <div><label>随机化日期</label><b class="num-mono">{{ d.randomization_date || '—' }}</b></div>
            <div><label>中心时区</label><b>{{ d.timezone }}</b></div>
          </div>
        </div>

        <!-- 锚点口径明示 -->
        <div class="card detail-card">
          <h4>计划日期推算口径</h4>
          <el-alert type="info" :closable="false" show-icon>
            <template #title>
              <div><b>研究统一口径：{{ d.policy_label }}</b></div>
              <div style="font-size:12px; margin-top:3px">本访视依据：{{ d.visit.anchor?.base_label || '—' }}
                <span v-if="d.visit.anchor?.base_date" class="num-mono">（{{ d.visit.anchor.base_date }}）</span>
              </div>
            </template>
          </el-alert>
          <el-alert
            v-if="d.visit.anchor?.conflict"
            type="warning" show-icon :closable="false" style="margin-top:10px"
            :title="`两种口径推算结果不一致：已按研究口径采用当前计划日；${d.visit.anchor.alternative_label}为 ${d.visit.anchor.alternative_date}。请以页面标注为准，无需自行猜测。`"
          />
          <div v-if="d.visit.pinned" class="pinned-note">
            <el-icon><Top /></el-icon> 该访视曾被手动改期，计划日已钉住；后续链式重算不会覆盖本人工决定（方案再修订时除外）。
          </div>
        </div>

        <!-- 完成度口径 + 关键表单 -->
        <div class="card detail-card">
          <h4>完成度（关键表单口径）</h4>
          <el-alert type="success" :closable="false" class="basis-alert" :title="d.completion_basis" />
          <div class="form-sum num-mono">
            本访视关键表单
            <b>{{ d.visit.key_form_done }}/{{ d.visit.key_form_total }}</b>
            （{{ d.visit.completion_percent }}%）
          </div>
          <el-table :data="d.visit.forms" size="small" style="margin-top:8px">
            <el-table-column prop="name" label="关键表单（CRF）" min-width="150" />
            <el-table-column label="状态" width="120">
              <template #default="{ row }">
                <el-tag
                  size="small"
                  :type="row.status === 'complete' ? 'success' : row.status === 'incomplete' ? 'warning' : 'info'"
                  effect="plain"
                >{{ row.status_label }}</el-tag>
              </template>
            </el-table-column>
            <el-table-column label="已填字段" width="110">
              <template #default="{ row }" class="num-mono">
                <span class="num-mono">{{ row.filled_fields }}/{{ row.total_fields }}</span>
              </template>
            </el-table-column>
          </el-table>
          <div class="half-note">
            注：状态为「填写中（未提交）」的表单即使已填部分字段，在本平台完成度中也计为 <b>0</b>，
            不会按字段数折算成半张表。
          </div>
        </div>

        <!-- 操作 -->
        <div class="card detail-card">
          <h4>访视操作</h4>
          <div class="action-row">
            <el-button type="primary" plain :icon="Calendar"
                       :disabled="d.visit.locked || d.visit.status === 'done' || d.visit.status === 'skipped'"
                       @click="$emit('reschedule', d.visit)">
              拖拽/手动改期
            </el-button>
            <el-button v-if="d.visit.status !== 'skipped'" type="warning" plain :icon="VideoPause"
                       :disabled="d.visit.locked || d.visit.status === 'done'"
                       @click="askReason('skip')">
              跳过访视
            </el-button>
            <el-button v-else type="success" plain :icon="VideoPlay" :disabled="d.visit.locked"
                       @click="askReason('restore')">
              恢复访视
            </el-button>
            <el-button
              :type="d.visit.locked ? 'info' : 'danger'" plain
              :icon="Lock"
              @click="askReason(d.visit.locked ? 'unlock' : 'lock')"
            >
              {{ d.visit.locked ? '申请解锁' : '锁库' }}
            </el-button>
          </div>
          <div v-if="d.visit.locked" class="lock-note">
            锁库后计划日期、实际日期与表单数据全部冻结，任何修改都需先解锁并留痕；链式重算也不会改动本访视。
          </div>
          <el-button text type="primary" style="margin-top:8px"
                     @click="$emit('openSubject', d.subject_id)">
            查看受试者链路与全部访视 →
          </el-button>
        </div>

        <!-- 排程留痕 -->
        <div class="card detail-card">
          <h4>排程留痕（{{ d.audits.length }}）</h4>
          <el-timeline style="margin-top:8px">
            <el-timeline-item
              v-for="a in d.audits" :key="a.id"
              :timestamp="fmt(a.created_at)" placement="top"
              :type="a.out_of_window ? 'danger' : 'primary'"
            >
              <div style="font-weight:600">
                {{ a.action_label }}
                <span v-if="a.visit_no" class="num-mono">· {{ a.visit_no }}</span>
                <el-tag v-if="a.out_of_window" size="small" type="danger" effect="plain" style="margin-left:6px">超窗 PD</el-tag>
              </div>
              <div v-if="a.old_date || a.new_date" class="num-mono" style="font-size:12px; color:var(--ink-2); margin-top:2px">
                <template v-if="a.old_date">{{ a.old_date }}</template>
                <template v-else>—</template>
                → {{ a.new_date || '—' }}
              </div>
              <div v-if="a.reason" style="font-size:12px; color:var(--ink-2); margin-top:2px">原因：{{ a.reason }}</div>
              <div v-if="a.detail" style="font-size:12px; color:var(--ink-3); margin-top:2px">{{ a.detail }}</div>
              <div style="font-size:11px; color:var(--ink-3); margin-top:2px">操作人：{{ a.operator_name }}</div>
            </el-timeline-item>
          </el-timeline>
        </div>
      </template>
    </div>
  </el-drawer>
</template>

<script setup>
import { ref, watch } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import {
  Lock, Calendar, VideoPause, VideoPlay, Top,
} from '@element-plus/icons-vue'
import { visitPlanApi } from '@/api'
import ErrorState from '@/components/ErrorState.vue'

const props = defineProps({
  modelValue: { type: Boolean, default: false },
  visitId: { type: [Number, String], default: null },
})
const emit = defineEmits(['update:modelValue', 'changed', 'reschedule', 'openSubject'])

const d = ref(null)
const loading = ref(false)
const errorMsg = ref('')

async function load() {
  if (!props.visitId) return
  loading.value = true
  errorMsg.value = ''
  try {
    d.value = await visitPlanApi.detail(props.visitId)
  } catch (e) {
    d.value = null
    errorMsg.value = e.message || '加载失败'
  } finally {
    loading.value = false
  }
}
watch(() => props.modelValue, (open) => { if (open && props.visitId) load() })
watch(() => props.visitId, (id) => { if (id && props.modelValue) load() })

function fmt(t) { return t ? new Date(t).toLocaleString('zh-CN', { hour12: false }) : '—' }

async function askReason(kind) {
  const isLock = kind === 'lock' || kind === 'unlock'
  const title = { skip: '跳过访视', restore: '恢复访视', lock: '锁库', unlock: '申请解锁' }[kind]
  const tip = {
    skip: '跳过后该访视标记为未执行（不计入完成度分母），下游访视计划日期将链式重算。',
    restore: '恢复后该访视重新计入完成度，下游访视计划日期将链式重算。',
    lock: '锁库将冻结该访视的计划/实际日期与表单，之后不可改期或跳过。',
    unlock: '解锁需填写理由并留痕，解锁后方可继续修改。',
  }[kind]
  let answer
  try {
    answer = await ElMessageBox.prompt(tip, title, {
      confirmButtonText: '确认',
      cancelButtonText: '取消',
      inputType: 'textarea',
      inputPlaceholder: '请填写原因（不少于 5 个字），将写入留痕',
      inputValidator: (v) => (v && v.trim().length >= 5) || '原因不少于 5 个字',
    })
  } catch {
    return
  }
  try {
    if (kind === 'skip') {
      const r = await visitPlanApi.skip(d.value.visit.id, answer.value.trim())
      ElMessage.success(r.message)
    } else if (kind === 'restore') {
      const r = await visitPlanApi.restore(d.value.visit.id, answer.value.trim())
      ElMessage.success(r.message)
    } else {
      const r = await visitPlanApi.lock(d.value.visit.id, {
        locked: kind === 'lock', reason: answer.value.trim(),
      })
      ElMessage.success(r.message)
    }
    emit('changed')
    load()
  } catch (e) {
    ElMessage.error(e.message || '操作失败')
  }
}
</script>

<style scoped>
.detail-banner { border-radius: 8px; margin-bottom: 12px; }
.detail-card { padding: 14px 16px; margin-bottom: 12px; }
.detail-card h4 { margin: 0 0 10px; font-size: 14px; }
.dc-head { display: flex; justify-content: space-between; gap: 12px; align-items: flex-start; }
.dc-title { font-size: 17px; font-weight: 700; display: flex; align-items: center; gap: 8px; flex-wrap: wrap; }
.dc-sub { font-size: 12px; color: var(--ink-3); margin-top: 4px; }
.dc-state { font-size: 13px; padding: 4px 12px; }
.dc-grid {
  display: grid; grid-template-columns: 1fr 1fr; gap: 10px 18px; margin-top: 14px;
  font-size: 13px;
}
.dc-grid label { display: block; color: var(--ink-3); font-size: 11px; margin-bottom: 2px; }
.basis-alert { margin-bottom: 8px; }
.form-sum { font-size: 13px; color: var(--ink-2); }
.form-sum b { font-size: 16px; color: var(--brand-700); margin: 0 4px; }
.half-note { font-size: 12px; color: var(--ink-3); margin-top: 8px; line-height: 1.7; }
.pinned-note, .lock-note {
  margin-top: 10px; font-size: 12px; color: var(--status-warning);
  background: var(--status-warning-bg); border-radius: 6px; padding: 8px 10px;
  display: flex; gap: 6px; align-items: flex-start;
}
.lock-note { color: #a52020; background: var(--status-critical-bg); }
.action-row { display: flex; gap: 10px; flex-wrap: wrap; }
@media (max-width: 640px) {
  .dc-grid { grid-template-columns: 1fr; }
}
</style>
