// 纯日历日工具。后端日期串为 'YYYY-MM-DD'，语义是研究中心当地日历日。
// 关键：不能 new Date('YYYY-MM-DD')（会按 UTC 零点解析，负时区显示成前一天），
// 一律拆解为本地 Date；所有网格/窗期算术只在日历日上做（天然不受夏令时影响）。

export function parseDate(s) {
  if (!s) return null
  if (s instanceof Date) return s
  const [y, m, d] = String(s).slice(0, 10).split('-').map(Number)
  return new Date(y, m - 1, d)
}

export function toKey(d) {
  if (!d) return ''
  const y = d.getFullYear()
  const m = String(d.getMonth() + 1).padStart(2, '0')
  const day = String(d.getDate()).padStart(2, '0')
  return `${y}-${m}-${day}`
}

export function addDays(d, n) {
  const x = new Date(d)
  x.setDate(x.getDate() + n)
  return x
}

export function diffDays(aKey, bKey) {
  // aKey - bKey（天）
  return Math.round((parseDate(aKey) - parseDate(bKey)) / 86400000)
}

export function startOfWeek(d) {
  // 周一为一周起点
  const x = new Date(d)
  const dow = (x.getDay() + 6) % 7
  return addDays(x, -dow)
}

export function buildWeekDays(anchor) {
  const start = startOfWeek(parseDate(anchor))
  return Array.from({ length: 7 }, (_, i) => addDays(start, i))
}

export function buildMonthDays(anchor) {
  // 返回包含该月的 6 行 × 7 列（42 天）日历网格
  const d = parseDate(anchor)
  const first = new Date(d.getFullYear(), d.getMonth(), 1)
  const gridStart = startOfWeek(first)
  return Array.from({ length: 42 }, (_, i) => addDays(gridStart, i))
}

export function sameDay(aKey, bKey) {
  return aKey && bKey && String(aKey).slice(0, 10) === String(bKey).slice(0, 10)
}

export function monthLabel(d) {
  return `${d.getFullYear()} 年 ${d.getMonth() + 1} 月`
}

export function weekRangeLabel(days) {
  const a = days[0]
  const b = days[days.length - 1]
  return `${a.getMonth() + 1}月${a.getDate()}日 – ${b.getMonth() + 1}月${b.getDate()}日`
}

export function weekdayShort(d) {
  return ['一', '二', '三', '四', '五', '六', '日'][(d.getDay() + 6) % 7]
}

export function fmtDate(s) {
  return s ? String(s).slice(0, 10) : '—'
}

export function fmtDateTimeLocal(s) {
  if (!s) return '—'
  return String(s).replace('T', ' ').slice(0, 16)
}
