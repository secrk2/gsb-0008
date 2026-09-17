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
