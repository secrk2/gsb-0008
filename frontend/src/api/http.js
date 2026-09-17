import axios from 'axios'
import { ElMessage } from 'element-plus'
import router from '@/router'
import { useAuthStore } from '@/stores/auth'

const http = axios.create({ baseURL: '/', timeout: 15000 })

http.interceptors.request.use((config) => {
  const auth = useAuthStore()
  if (auth.token) config.headers.Authorization = `Bearer ${auth.token}`
  return config
})

// 统一解包 + 统一错误形态（后端错误体：{error:{code,message}}）
http.interceptors.response.use(
  (resp) => resp.data,
  (error) => {
    const auth = useAuthStore()
    const status = error.response?.status
    const data = error.response?.data
    const message =
      data?.error?.message ||
      (typeof data?.detail === 'string' ? data.detail : null) ||
      error.message ||
      '网络异常，请稍后重试'

    if (status === 401) {
      auth.clear()
      if (router.currentRoute.value.name !== 'login') {
        ElMessage.error('登录态已失效，请重新登录')
        router.push({ name: 'login' })
      }
    }
    // 403 越权等错误由页面接管展示（明确错误态），不弹全局 toast 打断
    return Promise.reject({ status, code: data?.error?.code, message, raw: error })
  }
)

export default http
