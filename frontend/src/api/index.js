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
  get: (params = {}) => http.get('/api/visit-plan', { params }),
  detail: (id) => http.get(`/api/visits/${id}`),
  reschedule: (id, payload) => http.post(`/api/visits/${id}/reschedule`, payload),
  skip: (id, reason) => http.post(`/api/visits/${id}/skip`, { reason }),
  restore: (id, reason) => http.post(`/api/visits/${id}/restore`, { reason }),
  unscheduled: (payload) => http.post('/api/visit-plan/unscheduled', payload),
  lock: (id, payload) => http.post(`/api/visits/${id}/lock`, payload),
  revision: (payload) => http.post('/api/visit-plan/revision', payload),
  versionTemplate: (version) => http.get(`/api/protocol-versions/${version}/template`),
  exportCsv: (params = {}) =>
    http.get('/api/visit-plan/export', { params, responseType: 'blob' }),
}
