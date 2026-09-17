import { defineStore } from 'pinia'

export const useAuthStore = defineStore('auth', {
  state: () => ({
    token: localStorage.getItem('suyuan_token') || '',
    user: JSON.parse(localStorage.getItem('suyuan_user') || 'null'),
  }),
  getters: {
    isLoggedIn: (s) => !!s.token,
    isInvestigator: (s) => s.user?.role === 'investigator',
    isDm: (s) => s.user?.role === 'dm',
    isMonitor: (s) => s.user?.role === 'monitor',
  },
  actions: {
    setSession(token, user) {
      this.token = token
      this.user = user
      localStorage.setItem('suyuan_token', token)
      localStorage.setItem('suyuan_user', JSON.stringify(user))
    },
    clear() {
      this.token = ''
      this.user = null
      localStorage.removeItem('suyuan_token')
      localStorage.removeItem('suyuan_user')
    },
  },
})
