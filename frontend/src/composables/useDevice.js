import { onMounted, onUnmounted, ref } from 'vue'

// 与全局 CSS 断点保持一致：≤640 手机 / ≤1180 平板 / 其余桌面
export function useDevice() {
  const device = ref('desktop')

  function update() {
    const w = window.innerWidth
    device.value = w <= 640 ? 'mobile' : w <= 1180 ? 'tablet' : 'desktop'
  }

  onMounted(() => {
    update()
    window.addEventListener('resize', update)
  })
  onUnmounted(() => window.removeEventListener('resize', update))
  return device
}
