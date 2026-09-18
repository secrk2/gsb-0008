<template>
  <el-dialog
    :model-value="modelValue"
    title="发布方案修订（切版）"
    width="880px"
    top="6vh"
    @update:model-value="$emit('update:modelValue', $event)"
    @open="onOpen"
  >
    <el-alert type="warning" :closable="false" show-icon style="margin-bottom:14px">
      <template #title>
        修订发布后：<b>已完成 / 已跳过 / 已锁库</b> 的访视冻结在旧版本原样不动；
        <b>尚未发生</b>（计划日晚于生效日）的访视自动切换到新版本并按新偏移/窗口重算；
        新版删除的访视若尚未发生将被移除，新增访视会为受试者补建。同一受试者新旧并存时界面会醒目标记。
      </template>
    </el-alert>

    <el-form label-width="104px" v-loading="loading">
      <div class="rev-grid">
        <el-form-item label="新版本号" required>
          <el-input v-model="form.version" placeholder="如 v1.2" />
        </el-form-item>
        <el-form-item label="生效日期" required>
          <el-date-picker v-model="form.effective_date" type="date" value-format="YYYY-MM-DD"
                          :disabled-date="disablePast" style="width:100%" />
        </el-form-item>
      </div>
      <el-form-item label="修订标题" required>
        <el-input v-model="form.title" maxlength="128" show-word-limit />
      </el-form-item>
      <el-form-item label="修订说明" required>
        <el-input v-model="form.change_note" type="textarea" :rows="2" maxlength="500" show-word-limit
                  placeholder="说明本次修订内容（不少于 5 个字），将写入受试者留痕" />
      </el-form-item>

      <div class="tpl-bar">
        <b>新版访视模板（{{ form.visits.length }}）</b>
        <el-button size="small" :icon="Plus" @click="addVisit">新增访视</el-button>
      </div>
      <el-table :data="form.visits" size="small" border max-height="340">
        <el-table-column label="访视号" width="90">
          <template #default="{ row }"><el-input v-model="row.visit_no" size="small" /></template>
        </el-table-column>
        <el-table-column label="名称" width="150">
          <template #default="{ row }"><el-input v-model="row.name" size="small" /></template>
        </el-table-column>
        <el-table-column label="顺序" width="78">
          <template #default="{ row }"><el-input-number v-model="row.order_index" :min="1" :step="10" size="small" controls-position="right" style="width:100%" /></template>
        </el-table-column>
        <el-table-column label="相对天数" width="92">
          <template #default="{ row }"><el-input-number v-model="row.offset_days" :step="7" size="small" controls-position="right" style="width:100%" /></template>
        </el-table-column>
        <el-table-column label="锚点" width="150">
          <template #default="{ row }">
            <el-select v-model="row.anchor_mode" size="small" style="width:100%">
              <el-option label="相对随机化日" value="randomization" />
              <el-option label="相对上次实际访视" value="previous_actual" />
            </el-select>
          </template>
        </el-table-column>
        <el-table-column label="窗前/后" width="120">
          <template #default="{ row }">
            <div style="display:flex; gap:4px; align-items:center">
              <el-input-number v-model="row.window_before" :min="0" :max="90" size="small" controls-position="right" style="width:52px" />
              <el-input-number v-model="row.window_after" :min="0" :max="90" size="small" controls-position="right" style="width:52px" />
            </div>
          </template>
        </el-table-column>
        <el-table-column label="关键表单（每行 key|名称|字段数）" min-width="220">
          <template #default="{ row }">
            <el-input v-model="row.forms_text" type="textarea" :rows="2" size="small"
                      placeholder="lab|实验室检查|12" />
          </template>
        </el-table-column>
        <el-table-column label="操作" width="64" fixed="right">
          <template #default="{ $index }">
            <el-button size="small" type="danger" link :icon="Delete" @click="form.visits.splice($index, 1)" />
          </template>
        </el-table-column>
      </el-table>
      <div class="tpl-hint">
        关键表单每行一条，格式 <code>form_key|表单名称|字段总数</code>；留空访视将不挂关键表单（完成度分母不含）。
      </div>
    </el-form>

    <template #footer>
      <el-button @click="$emit('update:modelValue', false)">取消</el-button>
      <el-button type="warning" :loading="publishing" :disabled="!canPublish" @click="publish">
        发布并对在研受试者切版
      </el-button>
    </template>
  </el-dialog>
</template>

<script setup>
import { computed, reactive, ref } from 'vue'
import { ElMessage } from 'element-plus'
import { Plus, Delete } from '@element-plus/icons-vue'
import { visitPlanApi } from '@/api'

const props = defineProps({ modelValue: { type: Boolean, default: false } })
const emit = defineEmits(['update:modelValue', 'published'])

const loading = ref(false)
const publishing = ref(false)
const form = reactive({
  version: '', title: '', change_note: '', effective_date: '',
  based_on: 'v1.1',
  visits: [],
})

function disablePast(d) {
  const today = new Date()
  today.setHours(0, 0, 0, 0)
  return d.getTime() < today.getTime()
}

async function onOpen() {
  loading.value = true
  try {
    const tpl = await visitPlanApi.versionTemplate('v1.1')
    form.based_on = tpl.version
    form.visits = tpl.visits.map((v) => ({
      visit_no: v.visit_no,
      name: v.name,
      order_index: v.order_index,
      offset_days: v.offset_days,
      anchor_mode: v.anchor_mode,
      window_before: v.window_before,
      window_after: v.window_after,
      forms_text: (v.forms || [])
        .map((f) => `${f.form_key}|${f.name}|${f.total_fields}`).join('\n'),
    }))
    form.version = ''
    form.title = ''
    form.change_note = ''
    form.effective_date = ''
  } catch (e) {
    ElMessage.error(e.message || '当前模板加载失败')
  } finally {
    loading.value = false
  }
}

function addVisit() {
  const order = (form.visits.reduce((m, v) => Math.max(m, v.order_index || 0), 0) + 10)
  form.visits.push({
    visit_no: '', name: '', order_index: order, offset_days: 0,
    anchor_mode: 'randomization', window_before: 3, window_after: 3, forms_text: '',
  })
}

function parseForms(text) {
  const out = []
  for (const raw of (text || '').split('\n')) {
    const line = raw.trim()
    if (!line) continue
    const parts = line.split('|').map((x) => x.trim())
    if (parts.length < 2 || !parts[0]) continue
    out.push({
      form_key: parts[0],
      name: parts[1] || parts[0],
      is_key: true,
      total_fields: Math.max(0, parseInt(parts[2], 10) || 0),
    })
  }
  return out
}

const canPublish = computed(() => {
  if (!form.version.trim() || !form.title.trim() || form.change_note.trim().length < 5
      || !form.effective_date || !form.visits.length) return false
  return form.visits.every((v) => v.visit_no.trim() && v.name.trim())
})

async function publish() {
  const nos = form.visits.map((v) => v.visit_no.trim())
  if (new Set(nos).size !== nos.length) {
    ElMessage.warning('访视号不能重复')
    return
  }
  publishing.value = true
  try {
    const res = await visitPlanApi.revision({
      version: form.version.trim(),
      title: form.title.trim(),
      change_note: form.change_note.trim(),
      effective_date: form.effective_date,
      visits: form.visits
        .map((v) => ({
          visit_no: v.visit_no.trim(),
          name: v.name.trim(),
          order_index: Number(v.order_index),
          offset_days: Number(v.offset_days),
          anchor_mode: v.anchor_mode,
          window_before: Number(v.window_before),
          window_after: Number(v.window_after),
          forms: parseForms(v.forms_text),
        }))
        .sort((a, b) => a.order_index - b.order_index),
    })
    ElMessage.success(res.message)
    emit('update:modelValue', false)
    emit('published', res)
  } catch (e) {
    ElMessage.error(e.message || '发布失败')
  } finally {
    publishing.value = false
  }
}
</script>

<style scoped>
.rev-grid { display: grid; grid-template-columns: 1fr 1fr; gap: 0 16px; }
.tpl-bar { display: flex; justify-content: space-between; align-items: center; margin: 6px 0 8px; }
.tpl-hint { font-size: 12px; color: var(--ink-3); margin-top: 8px; line-height: 1.7; }
.tpl-hint code { background: #eef1f5; padding: 0 5px; border-radius: 4px; }
</style>
