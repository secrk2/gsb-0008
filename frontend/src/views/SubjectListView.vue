<template>
  <div>
    <div style="display:flex; align-items:flex-end; justify-content:space-between; gap:12px; flex-wrap:wrap">
      <div>
        <h2 class="page-title">受试者</h2>
        <div class="page-sub">筛选登记 → 编号分配 → 入组 → 完成 / 脱落 / 中止 / 剔除，全链路留痕</div>
      </div>
      <el-button v-if="canCreate" type="primary" :icon="Plus" @click="openCreate">筛选登记</el-button>
      <el-button :icon="Tickets" @click="openNumberBook">号码台账</el-button>
    </div>

    <!-- 筛选条：小屏自动换行 -->
    <div class="card" style="margin-top:14px; padding:12px 14px; display:flex; gap:10px; flex-wrap:wrap; align-items:center">
      <el-select v-if="auth.isDm" v-model="filters.site_id" placeholder="全部中心" clearable
                 style="width:210px" @change="load">
        <el-option v-for="s in sites" :key="s.id" :label="`${s.name}（${s.code}）`" :value="s.id" />
      </el-select>
      <el-radio-group v-model="filters.status" @change="load" size="default">
        <el-radio-button label="">全部</el-radio-button>
        <el-radio-button v-for="s in statuses" :key="s.value" :label="s.value">
          {{ s.label }}<span v-if="s.terminal">　</span>
        </el-radio-button>
      </el-radio-group>
      <el-input v-model="filters.keyword" placeholder="按筛选号/受试者编号检索" clearable
                style="width:230px" @keyup.enter="load" @clear="load">
        <template #prefix><el-icon><Search /></el-icon></template>
      </el-input>
      <el-button :icon="Search" @click="load">查询</el-button>
      <span style="flex:1" />
      <span style="font-size:12px; color:var(--ink-3)">共 {{ rows.length }} 名受试者（姓名按 GCP 脱敏展示）</span>
    </div>

    <ErrorState v-if="forbidden" type="forbidden" title="越权访问已拦截" :message="forbidden"
                style="margin-top:16px">
      <el-button type="primary" @click="resetSiteFilter">回到本中心数据</el-button>
    </ErrorState>
    <ErrorState v-else-if="errorMsg" type="warn" title="列表加载失败" :message="errorMsg" style="margin-top:16px">
      <el-button type="primary" @click="load">重试</el-button>
    </ErrorState>

    <div v-else class="card" style="margin-top:14px">
      <div class="table-scroll">
        <el-table :data="rows" v-loading="loading" style="width:100%" :row-class-name="rowClass">
          <el-table-column label="受试者（脱敏）" min-width="200">
            <template #default="{ row }">
              <div style="font-weight:600">{{ row.display_name }}</div>
              <div style="font-size:11px; color:var(--ink-3)">{{ row.screening_no }}<template v-if="row.subject_code"> · 编号 {{ row.subject_code }}</template></div>
            </template>
          </el-table-column>
          <el-table-column v-if="auth.isDm" prop="site_name" label="所属中心" min-width="170" />
          <el-table-column prop="gender" label="性别" width="64" />
          <el-table-column label="当前状态" width="104">
            <template #default="{ row }"><StatusTag :status="row.status" :label-map="statusLabelMap" /></template>
          </el-table-column>
          <el-table-column label="筛选日期" width="110">
            <template #default="{ row }"><span class="num-mono">{{ fmt(row.screen_date) }}</span></template>
          </el-table-column>
          <el-table-column label="入组日期" width="110">
            <template #default="{ row }"><span class="num-mono">{{ fmt(row.enroll_date) }}</span></template>
          </el-table-column>
          <el-table-column label="下次访视" min-width="150">
            <template #default="{ row }">
              <template v-if="row.next_visit_date">
                <span class="num-mono">{{ fmt(row.next_visit_date) }}</span>
                <el-tag v-if="row.next_visit_state" :type="visitTagType(row.next_visit_state)" size="small" effect="plain" style="margin-left:6px">
                  {{ visitLabel(row.next_visit_state) }}
                </el-tag>
              </template>
              <span v-else style="color:var(--ink-3)">—</span>
            </template>
          </el-table-column>
          <el-table-column label="操作" width="110" fixed="right">
            <template #default="{ row }">
              <el-button link type="primary" @click="goDetail(row)">链路详情</el-button>
            </template>
          </el-table-column>
          <template #empty>
            <div style="padding: 30px; color:var(--ink-3)">没有符合条件的受试者</div>
          </template>
        </el-table>
      </div>
    </div>

    <!-- 筛选登记弹窗 -->
    <el-dialog v-model="createVisible" title="筛选登记（自动分配筛选号）" width="480px">
      <el-alert type="info" :closable="false" style="margin-bottom:14px"
                title="提交后系统按「中心前缀-S顺序号」分配筛选号；若号码作废，永不复用并保留痕迹。" />
      <el-form :model="createForm" label-width="86px" :rules="createRules" ref="createFormRef">
        <el-form-item v-if="auth.isDm" label="研究中心" prop="site_id">
          <el-select v-model="createForm.site_id" placeholder="请选择中心" style="width:100%">
            <el-option v-for="s in sites" :key="s.id" :label="s.name" :value="s.id" />
          </el-select>
        </el-form-item>
        <el-form-item label="姓名" prop="full_name">
          <el-input v-model="createForm.full_name" placeholder="受试者真实姓名（入组后列表自动脱敏）" />
        </el-form-item>
        <el-form-item label="性别" prop="gender">
          <el-radio-group v-model="createForm.gender">
            <el-radio label="男">男</el-radio>
            <el-radio label="女">女</el-radio>
          </el-radio-group>
        </el-form-item>
        <el-form-item label="出生日期" prop="birth_date">
          <el-date-picker v-model="createForm.birth_date" type="date" value-format="YYYY-MM-DD" style="width:100%" />
        </el-form-item>
        <el-form-item label="手机号" prop="phone">
          <el-input v-model="createForm.phone" placeholder="用于随访联系" />
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="createVisible = false">取消</el-button>
        <el-button type="primary" :loading="creating" @click="submitCreate">确认登记并分配筛选号</el-button>
      </template>
    </el-dialog>
    <!-- 号码台账弹窗 -->
    <el-dialog v-model="bookVisible" title="号码台账（分配 / 作废留痕）" width="760px">
      <el-alert type="info" :closable="false" style="margin-bottom:12px"
                title="所有筛选号与受试者编号的分配、作废均在此留痕；作废号码锁定游标、永不再分配。" />
      <div style="display:flex; gap:10px; margin-bottom:12px; flex-wrap:wrap">
        <el-select v-if="auth.isDm" v-model="bookSiteId" placeholder="全部中心" clearable style="width:200px" @change="loadBook">
          <el-option v-for="s in sites" :key="s.id" :label="s.name" :value="s.id" />
        </el-select>
        <el-radio-group v-model="bookStatus" @change="loadBook">
          <el-radio-button label="">全部</el-radio-button>
          <el-radio-button label="assigned">已分配</el-radio-button>
          <el-radio-button label="voided">已作废</el-radio-button>
        </el-radio-group>
      </div>
      <div class="table-scroll">
        <el-table :data="bookRows" v-loading="bookLoading" size="small" max-height="420"
                  :row-class-name="(r) => r.row.status === 'voided' ? 'void-row' : ''">
          <el-table-column v-if="auth.isDm" prop="site_name" label="中心" min-width="160" />
          <el-table-column prop="kind_label" label="类型" width="90" />
          <el-table-column prop="number" label="号码" width="110">
            <template #default="{ row }"><b class="num-mono">{{ row.number }}</b></template>
          </el-table-column>
          <el-table-column label="状态" width="90">
            <template #default="{ row }">
              <el-tag :type="row.status === 'voided' ? 'danger' : 'success'" size="small">{{ row.status_label }}</el-tag>
            </template>
          </el-table-column>
          <el-table-column prop="reason" label="原因/说明" min-width="220" show-overflow-tooltip />
          <el-table-column prop="operator_name" label="操作人" width="90" />
        </el-table>
      </div>
    </el-dialog>
  </div>
</template>

<script setup>
import { computed, onMounted, reactive, ref } from 'vue'
import { useRouter } from 'vue-router'
import { ElMessage } from 'element-plus'
import { Plus, Search, Tickets } from '@element-plus/icons-vue'
import { metaApi, numberApi, subjectApi } from '@/api'
import { useAuthStore } from '@/stores/auth'
import StatusTag from '@/components/StatusTag.vue'
import ErrorState from '@/components/ErrorState.vue'

const auth = useAuthStore()
const router = useRouter()
const canCreate = computed(() => auth.isInvestigator || auth.isDm)

const loading = ref(false)
const rows = ref([])
const sites = ref([])
const statuses = ref([])
const statusLabelMap = ref({})
const errorMsg = ref('')
const forbidden = ref('')

const filters = reactive({ status: '', site_id: null, keyword: '' })

const VISIT_LABELS = {
  due_today: '今日应随访', overdue: '逾期', out_of_window: '已超窗',
  in_window: '窗内', upcoming: '未到窗', done: '已完成',
}
const VISIT_TAG = {
  due_today: 'danger', overdue: 'warning', out_of_window: 'danger',
  in_window: 'warning', upcoming: 'info', done: 'success',
}
const visitLabel = (s) => VISIT_LABELS[s] || s
const visitTagType = (s) => VISIT_TAG[s] || 'info'
const fmt = (d) => d || '—'
function rowClass({ row }) { return row.status === 'removed' ? 'row-removed' : '' }

async function load() {
  loading.value = true
  errorMsg.value = ''
  forbidden.value = ''
  try {
    const params = {}
    if (filters.status) params.status = filters.status
    if (filters.site_id) params.site_id = filters.site_id
    if (filters.keyword.trim()) params.keyword = filters.keyword.trim()
    rows.value = await subjectApi.list(params)
  } catch (e) {
    rows.value = []
    if (e.status === 403) forbidden.value = e.message
    else errorMsg.value = e.message
  } finally {
    loading.value = false
  }
}
function resetSiteFilter() {
  filters.site_id = null
  load()
}
function goDetail(row) { router.push({ name: 'subject-detail', params: { id: row.id } }) }

// ---------------- 筛选登记 ----------------
const createVisible = ref(false)
const creating = ref(false)
const createFormRef = ref()
const createForm = reactive({ site_id: null, full_name: '', gender: '男', birth_date: '', phone: '' })
const createRules = {
  site_id: [{ required: true, message: '请选择研究中心', trigger: 'change' }],
  full_name: [{ required: true, message: '请输入姓名', trigger: 'blur' }, { min: 2, max: 32, message: '长度 2-32', trigger: 'blur' }],
  gender: [{ required: true, message: '请选择性别', trigger: 'change' }],
  birth_date: [{ required: true, message: '请选择出生日期', trigger: 'change' }],
  phone: [{ required: true, message: '请输入手机号', trigger: 'blur' }],
}
function openCreate() {
  Object.assign(createForm, {
    site_id: auth.user?.site_id || sites.value[0]?.id || null,
    full_name: '', gender: '男', birth_date: '', phone: '',
  })
  createVisible.value = true
}
async function submitCreate() {
  await createFormRef.value.validate(async (valid) => {
    if (!valid) return
    creating.value = true
    try {
      const res = await subjectApi.create({ ...createForm })
      ElMessage.success(`登记成功，筛选号 ${res.screening_no} 已分配`)
      createVisible.value = false
      await load()
      router.push({ name: 'subject-detail', params: { id: res.id } })
    } catch (e) {
      ElMessage.error(e.message || '登记失败')
    } finally {
      creating.value = false
    }
  })
}

// ---------------- 号码台账 ----------------
const bookVisible = ref(false)
const bookLoading = ref(false)
const bookRows = ref([])
const bookSiteId = ref(null)
const bookStatus = ref('')
function openNumberBook() {
  bookSiteId.value = auth.isDm ? null : auth.user.site_id
  bookStatus.value = ''
  bookVisible.value = true
  loadBook()
}
async function loadBook() {
  bookLoading.value = true
  try {
    const params = {}
    if (bookSiteId.value) params.site_id = bookSiteId.value
    if (bookStatus.value) params.status = bookStatus.value
    bookRows.value = await numberApi.audits(params)
  } catch (e) {
    ElMessage.error(e.message || '号码台账加载失败')
  } finally {
    bookLoading.value = false
  }
}

onMounted(async () => {
  try {
    const [s, m] = await Promise.all([metaApi.sites(), metaApi.statuses()])
    sites.value = s
    statuses.value = m.statuses
    statusLabelMap.value = Object.fromEntries(m.statuses.map((x) => [x.value, x.label]))
  } catch { /* 列表自身会显示错误态 */ }
  load()
})
</script>

<style scoped>
:deep(.row-removed) { color: var(--ink-3); }
:deep(.row-removed td) { text-decoration: line-through; text-decoration-color: #c9cdd4; }
:deep(.void-row) { background: var(--status-critical-bg) !important; }
:deep(.void-row td) { color: #a52020; }
</style>
