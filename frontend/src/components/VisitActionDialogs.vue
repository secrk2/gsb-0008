<template>
  <!-- 超窗改期：二次确认 + 强制原因 -->
  <el-dialog v-model="rescheduleVisible" :title="res.title || '确认改期'" width="520px"
             :close-on-click-modal="false">
    <el-alert :type="res.outOfWindow ? 'error' : 'info'" :closable="false" style="margin-bottom:14px">
      <template #title>
        <div v-if="res.outOfWindow">
          落点 <b>{{ res.newDate }}</b> 已超出访视窗口（计划 {{ res.visit?.planned_date }}，
          允许 前{{ res.visit?.window_before }}/后{{ res.visit?.window_after }} 天）。
          超窗改期构成<b>方案偏离</b>，必须二次确认并填写原因，系统将写入稽查轨迹。
        </div>
        <div v-else>
          落点在随访窗口内（计划 {{ res.visit?.planned_date }}，
          前{{ res.visit?.window_before }}/后{{ res.visit?.window_after }} 天）。
        </div>
      </template>
    </el-alert>
    <el-form label-width="92px">
      <el-form-item label="受试者">
        <span>{{ res.subjectName }} · {{ res.visit?.name }}（{{ res.visit?.visit_no }}）</span>
      </el-form-item>
      <el-form-item label="改期后日期">
        <el-date-picker v-model="res.newDate" type="date" value-format="YYYY-MM-DD"
                        :clearable="false" style="width:100%" @change="onDateChange" />
      </el-form-item>
      <el-form-item v-if="res.outOfWindow" label="改期原因" required>
        <el-input v-model="res.reason" type="textarea" :rows="3" maxlength="200" show-word-limit
                  placeholder="请填写超窗原因（不少于 5 个字），如：受试者探亲无法按期返院，经PI评估后延后" />
      </el-form-item>
      <el-form-item v-else label="说明（可选）">
        <el-input v-model="res.reason" type="textarea" :rows="2" maxlength="200" show-word-limit
                  placeholder="窗内改期可简要说明，留痕备查" />
      </el-form-item>
      <el-form-item v-if="res.outOfWindow" label="二次确认">
        <el-checkbox v-model="res.confirm">我已知晓本次超窗构成方案偏离，确认改期并同意留痕</el-checkbox>
      </el-form-item>
    </el-form>
    <template #footer>
      <el-button @click="rescheduleVisible = false">取消</el-button>
      <el-button :type="res.outOfWindow ? 'danger' : 'primary'" :loading="submitting"
                 :disabled="res.outOfWindow && (!canSubmitReschedule)" @click="submitReschedule">
        {{ res.outOfWindow ? '确认超窗改期并留痕' : '确认改期' }}
      </el-button>
    </template>
  </el-dialog>

  <!-- 跳过访视 -->
  <el-dialog v-model="skipVisible" title="跳过访视" width="500px" :close-on-click-modal="false">
    <el-alert type="warning" :closable="false" style="margin-bottom:14px"
              title="跳过的访视不会被删除，仍保留在方案序列中；后续访视计划按链式口径重算。已完成/已锁库访视不可跳过。" />
    <el-form label-width="92px">
      <el-form-item label="访视">
        <span>{{ skip.visit?.name }}（{{ skip.visit?.visit_no }}）· 计划 {{ skip.visit?.planned_date }}</span>
      </el-form-item>
      <el-form-item label="跳过原因" required>
        <el-input v-model="skip.reason" type="textarea" :rows="3" maxlength="200" show-word-limit
                  placeholder="请填写跳过原因（不少于 5 个字），将写入稽查轨迹" />
      </el-form-item>
    </el-form>
    <template #footer>
      <el-button @click="skipVisible = false">取消</el-button>
      <el-button type="warning" :loading="submitting"
                 :disabled="skip.reason.trim().length < 5" @click="submitSkip">
        确认跳过并留痕
      </el-button>
    </template>
  </el-dialog>

  <!-- 插入计划外访视 -->
  <el-dialog v-model="insertVisible" title="插入计划外访视" width="520px" :close-on-click-modal="false">
    <el-alert type="info" :closable="false" style="margin-bottom:14px"
              title="计划外访视（如安全性加诊）将作为固定锚点插入，其后尚未发生的方案访视自动链式顺延；已完成/已锁库访视不受影响。" />
    <el-form label-width="92px">
      <el-form-item label="访视日期" required>
        <el-date-picker v-model="ins.theDate" type="date" value-format="YYYY-MM-DD"
                        :clearable="false" style="width:100%" />
      </el-form-item>
      <el-form-item label="访视名称" required>
        <el-input v-model="ins.name" maxlength="64" show-word-limit
                  placeholder="如：计划外·安全性复查" />
      </el-form-item>
      <el-form-item label="插入原因" required>
        <el-input v-model="ins.reason" type="textarea" :rows="3" maxlength="200" show-word-limit
                  placeholder="请说明插入计划外访视的医学原因（不少于 5 个字）" />
      </el-form-item>
    </el-form>
    <template #footer>
      <el-button @click="insertVisible = false">取消</el-button>
      <el-button type="primary" :loading="submitting" :disabled="!canInsert" @click="submitInsert">
        插入并链式顺延
      </el-button>
    </template>
  </el-dialog>
</template>

<script setup>
import { computed, reactive, ref } from 'vue'
import { ElMessage } from 'element-plus'
import { visitPlanApi } from '@/api'
import { parseDate, toKey, addDays } from '@/utils/date'

const emit = defineEmits(['changed'])

const submitting = ref(false)
const rescheduleVisible = ref(false)
const skipVisible = ref(false)
const insertVisible = ref(false)

const res = reactive({
  visit: null, subjectName: '', newDate: '', reason: '',
  confirm: false, outOfWindow: false, title: '',
})
const skip = reactive({ visit: null, subjectId: null, reason: '' })
const ins = reactive({ subjectId: null, theDate: '', name: '', reason: '' })

const canSubmitReschedule = computed(
  () => res.reason.trim().length >= 5 && res.confirm && !!res.newDate,
)
const canInsert = computed(
  () => ins.theDate && ins.name.trim().length >= 2 && ins.reason.trim().length >= 5,
)

function isOutOfWindow(visit, newKey) {
  const planned = parseDate(visit.planned_date)
  const lo = toKey(addDays(planned, -visit.window_before))
  const hi = toKey(addDays(planned, visit.window_after))
  return newKey < lo || newKey > hi
}

function openReschedule({ visit, subjectName, newDate }) {
  const key = newDate || visit.planned_date
  Object.assign(res, {
    visit, subjectName, newDate: key, reason: '', confirm: false,
    outOfWindow: isOutOfWindow(visit, key),
    title: key === visit.planned_date ? '访视改期' : '拖拽改期确认',
  })
  rescheduleVisible.value = true
}

function onDateChange(key) {
  if (!res.visit) return
  res.outOfWindow = isOutOfWindow(res.visit, key)
  if (!res.outOfWindow) res.confirm = false
}

async function submitReschedule() {
  if (res.outOfWindow && !canSubmitReschedule.value) return
  submitting.value = true
  try {
    const out = await visitPlanApi.reschedule(res.visit.id, {
      new_date: res.newDate,
      reason: res.reason.trim() || null,
      confirm_out_of_window: res.outOfWindow,
    })
    ElMessage.success(out.message)
    rescheduleVisible.value = false
    emit('changed')
  } catch (e) {
    if (e.code === 'OUT_OF_WINDOW_CONFIRM') {
      res.outOfWindow = true
      ElMessage.warning('该落点超出窗口，请填写原因并二次确认')
    } else {
      ElMessage.error(e.message || '改期失败')
    }
  } finally {
    submitting.value = false
  }
}

function openSkip({ visit }) {
  Object.assign(skip, { visit, subjectId: visit.subject_id, reason: '' })
  skipVisible.value = true
}

async function submitSkip() {
  if (skip.reason.trim().length < 5) return
  submitting.value = true
  try {
    const out = await visitPlanApi.skip(skip.visit.id, skip.reason.trim())
    ElMessage.success(out.message)
    skipVisible.value = false
    emit('changed')
  } catch (e) {
    ElMessage.error(e.message || '跳过失败')
  } finally {
    submitting.value = false
  }
}

function openInsert({ subjectId, theDate }) {
  Object.assign(ins, {
    subjectId, theDate: theDate || '', name: '', reason: '',
  })
  insertVisible.value = true
}

async function submitInsert() {
  if (!canInsert.value) return
  submitting.value = true
  try {
    const out = await visitPlanApi.insertUnscheduled(ins.subjectId, {
      the_date: ins.theDate,
      name: ins.name.trim(),
      reason: ins.reason.trim(),
    })
    ElMessage.success(out.message)
    insertVisible.value = false
    emit('changed')
  } catch (e) {
    ElMessage.error(e.message || '插入失败')
  } finally {
    submitting.value = false
  }
}

defineExpose({ openReschedule, openSkip, openInsert })
</script>
