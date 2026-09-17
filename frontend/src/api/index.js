import http from './http'

export const authApi = {
  login: (username, password) => http.post('/api/auth/login', { username, password }),
  me: () => http.get('/api/auth/me'),
}

export const dashboardApi = {
  get: () => http.get('/api/dashboard'),
}

export const subjectApi = {
  list: (params = {}) => http.get('/api/subjects', { params }),
  detail: (id) => http.get(`/api/subjects/${id}`),
  create: (payload) => http.post('/api/subjects', payload),
  transition: (id, payload) => http.post(`/api/subjects/${id}/transition`, payload),
  reveal: (id, reason) => http.post(`/api/subjects/${id}/reveal`, { reason }),
}

export const metaApi = {
  sites: () => http.get('/api/sites'),
  statuses: () => http.get('/api/meta/statuses'),
}

export const numberApi = {
  audits: (params = {}) => http.get('/api/number-audits', { params }),
}

export const visitPlanApi = {
  gantt: (params = {}) => http.get('/api/visit-plans/gantt', { params }),
  policy: () => http.get('/api/visit-plans/policy'),
  subjectVisits: (subjectId) => http.get(`/api/visit-plans/subjects/${subjectId}/visits`),
  reschedule: (visitId, payload) =>
    http.post(`/api/visit-plans/visits/${visitId}/reschedule`, payload),
  skip: (visitId, reason) =>
    http.post(`/api/visit-plans/visits/${visitId}/skip`, { reason }),
  insertUnscheduled: (subjectId, payload) =>
    http.post(`/api/visit-plans/subjects/${subjectId}/unscheduled-visits`, payload),
  publishAmendment: (payload) =>
    http.post('/api/visit-plans/amendments/publish', payload),
  // 导出需带鉴权头：用 blob 拉取后本地触发下载
  exportCsv: (params = {}) =>
    http.get('/api/visit-plans/export.csv', { params, responseType: 'blob' }),
}
