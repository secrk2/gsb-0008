<template>
  <el-dialog
    :model-value="modelValue"
    :title="outOfWindow ? '超窗改期 · 二次确认' : '确认访视改期'"
    width="520px"
    @update:model-value="$emit('update:modelValue', $event)"
    @close="reset"
  >
    <div v-if="visit && subject" class="rs-body">
      <el-alert
        :type="outOfWindow ? 'error' : 'info'" :closable="false" show-icon style="margin-bottom:14px">
        <template #title>
          <div>
            {{ subject.masked_name }} · {{ visit.visit_no }} {{ visit.name }}
            <el-tag size="small" :type="visit.version === subject.active_version ? 'success' : 'info'" effect="plain" style="margin-left:6px">
              {{ visit.version }}
            </el-tag>
          </div>
          <div style="margin-top:6px">
            原计划日期 <b class="num-mono">{{ visit.planned_date }}</b> →
            新日期 <b class="num-mono" :class="{ oow: outOfWindow }">{{ targetDate }}</b>
          </div>
          <div style="margin-top:4px; font-size:12px">
            随访窗范围：<span class="num-mono">{{ winStart }}</span> ~
            <span class="num-mono">{{ winEnd }}</span>
            （前 {{ visit.window_before }} 天 / 后 {{ visit.window_after }} 天）
          </div>
        </template>
      </el-alert>

      <el-alert
        v-if="outOfWindow" type="error" :closable="false" show-icon style="margin-bottom:14px">
        <template #title>
          落点 <b>{{ targetDate }}</b> 已超出随访窗。本次改期将作为<b>方案偏离（PD）</b>记录，
          必须填写原因并勾选确认；下游访视计划日期会按锚点规则链式重算，已锁库访视不受影响。
        </template>
      </el-alert>

      <el-form label-width="92px">
        <el-form-item label="新计划日期" required>
          <el-date-picker
            v-model="picked" type="date" value-format="YYYY-MM-DD"
            :clearable="false" style="width: 100%"
          />
        </el-form-item>
        <el-form-item label="改期原因" required>
          <el-input
            v-model="reason" type="textarea" :rows="3" maxlength="200" show-word-limit
            :placeholder="outOfWindow
              ? '超窗改期为方案偏离，必须填写原因（不少于 5 个字），将写入留痕'
              : '请填写改期原因（不少于 5 个字），将写入留痕'"
          />
        </el-form-item>
        <el-form-item v-if="outOfWindow" label="二次确认" required>
          <el-checkbox v-model="confirmOow">
            我确认该访视需在窗外日期进行，知悉这构成方案偏离并已通知研究者/PI 评估
          </el-checkbox>
        </el-form-item>
        <el-form-item v-if="visit.locked" label=" ">
          <el-text type="danger">该访视已锁库，无法改期（请先走解锁审批）。</el-text>
        </el-form-item>
      </el-form>
    </div>

    <template #footer>
      <el-button @click="$emit('update:modelValue', false)">取消</el-button>
      <el-button
        :type="outOfWindow ? 'danger' : 'primary'"
        :loading="submitting" :disabled="!canSubmit"
        @click="submit"
      >
        {{ outOfWindow ? '确认超窗改期并留痕' : '确认改期' }}
      </el-button>
    </template>
  </el-dialog>
</template>

<script setup>
import { computed, ref, watch } from 'vue'
import { ElMessage } from 'element-plus'
import { visitPlanApi } from '@/api'

const props = defineProps({
  modelValue: { type: Boolean, default: false },
  visit: { type: Object, default: null },
  subject: { type: Object, default: null },
  initialDate: { type: String, default: '' },
})
const emit = defineEmits(['update:modelValue', 'done'])

const picked = ref('')
const reason = ref('')
const confirmOow = ref(false)
const submitting = ref(false)

const targetDate = computed(() => picked.value || props.initialDate)

watch(
  () => props.modelValue,
  (open) => {
    if (open) reset()
  },
)
function reset() {
  picked.value = props.initialDate || props.visit?.planned_date || ''
  reason.value = ''
  confirmOow.value = false
}

function addDays(isoStr, n) {
  const [y, m, d] = isoStr.split('-').map(Number)
  const dt = new Date(Date.UTC(y, m - 1, d + n))
  return dt.toISOString().slice(0, 10)
}
const winStart = computed(() => props.visit ? addDays(props.visit.planned_date, -props.visit.window_before) : '')
const winEnd = computed(() => props.visit ? addDays(props.visit.planned_date, props.visit.window_after) : '')
const outOfWindow = computed(() => {
  if (!targetDate.value || !props.visit) return false
  return targetDate.value < winStart.value || targetDate.value > winEnd.value
})
const canSubmit = computed(() => {
  if (!targetDate.value || props.visit?.locked) return false
  if (reason.value.trim().length < 5) return false
  if (outOfWindow.value && !confirmOow.value) return false
  return true
})

async function submit() {
  submitting.value = true
  try {
    const res = await visitPlanApi.reschedule(props.visit.id, {
      new_date: targetDate.value,
      reason: reason.value.trim(),
      confirm_out_of_window: outOfWindow.value,
    })
    ElMessage.success(res.message)
    emit('update:modelValue', false)
    emit('done')
  } catch (e) {
    // 后端判定超窗未确认（理论上前端已拦截），用其文案提示
    ElMessage.error(e.message || '改期失败')
  } finally {
    submitting.value = false
  }
}
</script>

<style scoped>
.oow { color: var(--status-critical); }
.rs-body :deep(.el-form-item__content) { align-items: flex-start; }
</style>
