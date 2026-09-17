import { onBeforeUnmount, onMounted, ref } from 'vue'

/**
 * 弱网/离线检测：
 * - online/offline 事件即时切换；
 * - 每 30s 主动探活 /api/health（捕获“假在线”：Wi-Fi 连着但后端不通）；
 * - 恢复联网后由调用方决定如何处理（手动重试，避免离线期间操作歧义）。
 */
export function useConnectivity() {
  const online = ref(navigator.onLine)
  const serverUp = ref(true)
  const restoredAt = ref(null)
  let timer = null

  function setOffline() {
    online.value = false
    serverUp.value = false
  }

  async function probe() {
    if (!navigator.onLine) {
      online.value = false
      return
    }
    online.value = true
    try {
      const ctrl = new AbortController()
      const t = setTimeout(() => ctrl.abort(), 5000)
      const resp = await fetch('/api/health', { signal: ctrl.signal, cache: 'no-store' })
      clearTimeout(t)
      const wasDown = !serverUp.value
      serverUp.value = resp.ok
      if (wasDown && resp.ok) restoredAt.value = new Date()
    } catch {
      serverUp.value = false
    }
  }

  function onOnline() {
    online.value = true
    probe()
  }

  onMounted(() => {
    window.addEventListener('online', onOnline)
    window.addEventListener('offline', setOffline)
    probe()
    timer = setInterval(probe, 30000)
  })
  onBeforeUnmount(() => {
    window.removeEventListener('online', onOnline)
    window.removeEventListener('offline', setOffline)
    if (timer) clearInterval(timer)
  })

  return { online, serverUp, restoredAt, probe }
}
