import { computed, onMounted, onUnmounted, ref } from 'vue'
import { visitPlanApi } from '@/api'

// 三端断点：>1180 桌面甘特 / 641~1180 平板两栏 / <=640 手机竖列
export function useBreakpoint() {
  const width = ref(window.innerWidth)
  const onResize = () => { width.value = window.innerWidth }
  onMounted(() => window.addEventListener('resize', onResize))
  onUnmounted(() => window.removeEventListener('resize', onResize))
  const layout = computed(() =>
    width.value > 1180 ? 'desktop' : width.value > 640 ? 'tablet' : 'mobile'
  )
  return { width, layout }
}

function iso(d) {
  if (!d) return ''
  return typeof d === 'string' ? d.slice(0, 10) : d
}

function shiftMonth(dateStr, delta) {
  const [y, m, dd] = dateStr.split('-').map(Number)
  const base = new Date(y, m - 1 + delta, 1)
  return `${base.getFullYear()}-${String(base.getMonth() + 1).padStart(2, '0')}-01`
}

function shiftWeek(dateStr, delta) {
  const [y, m, d] = dateStr.split('-').map(Number)
  const base = new Date(Date.UTC(y, m - 1, d + delta * 7))
  return base.toISOString().slice(0, 10)
}

export function useVisitPlan() {
  const loading = ref(false)
  const errorMsg = ref('')
  const data = ref(null)
  const view = ref('month')
  const anchor = ref(new Date().toISOString().slice(0, 10))
  const siteId = ref(null)
  const subjectId = ref(null)
  const { layout } = useBreakpoint()

  async function load() {
    loading.value = true
    errorMsg.value = ''
    try {
      data.value = await visitPlanApi.get({
        view: view.value,
        anchor: anchor.value,
        ...(siteId.value ? { site_id: siteId.value } : {}),
        ...(subjectId.value ? { subject_id: subjectId.value } : {}),
      })
    } catch (e) {
      data.value = null
      errorMsg.value = e.message || '访视计划加载失败'
    } finally {
      loading.value = false
    }
  }

  function setView(v) {
    view.value = v
    load()
  }
  function setSite(id) {
    siteId.value = id || null
    load()
  }
  function prev() {
    anchor.value = view.value === 'month'
      ? shiftMonth(anchor.value, -1)
      : shiftWeek(anchor.value, -1)
    load()
  }
  function next() {
    anchor.value = view.value === 'month'
      ? shiftMonth(anchor.value, 1)
      : shiftWeek(anchor.value, 1)
    load()
  }
  function today() {
    anchor.value = new Date().toISOString().slice(0, 10)
    load()
  }

  // ---- 派生：把访视按日期分组 ----
  const visitsById = computed(() => {
    const m = new Map()
    for (const s of data.value?.subjects || []) {
      for (const v of s.visits) m.set(v.id, { ...v, subject: s })
    }
    return m
  })

  const emptyState = computed(() => {
    if (!data.value) return null
    if (data.value.empty_reason === 'no_visits') {
      return {
        type: 'empty',
        icon: 'Calendar',
        title: '当前范围内的受试者尚无任何访视安排',
        desc: '访视会在受试者入组（随机化）后，按当前生效方案版本自动生成。'
          + '请先在「受试者」菜单完成入组，或调整上方的中心/时间范围筛选后再查看。',
      }
    }
    if (data.value.empty_reason === 'all_skipped') {
      return {
        type: 'warn',
        icon: 'CircleRemove',
        title: '当前范围内受试者的访视已被全部跳过',
        desc: '这些受试者的每一次访视都处于「已跳过」状态，因此甘特图上没有待执行或已完成的访视。'
          + '如系误操作，可进入受试者访视详情「恢复」相应访视，恢复后计划日期将按锚点规则重新链式计算。',
      }
    }
    return null
  })

  return {
    loading, errorMsg, data, view, anchor, siteId, subjectId, layout,
    load, setView, setSite, prev, next, today, visitsById, emptyState, iso,
  }
}
