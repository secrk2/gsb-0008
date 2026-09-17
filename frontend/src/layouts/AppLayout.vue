<template>
  <div class="app-shell">
    <!-- 手机端遮罩 -->
    <div :class="['mobile-drawer-mask', { show: drawerOpen }]" @click="drawerOpen = false" />

    <aside :class="['app-sidebar', { open: drawerOpen }]">
      <div class="sidebar-brand">
        <span class="logo-mark"><el-icon><Connection /></el-icon></span>
        <span class="brand-text">溯源方</span>
      </div>
      <nav class="sidebar-nav">
        <router-link
          v-for="item in menus"
          :key="item.name"
          :to="item.to"
          :class="['nav-item', { active: route.name === item.name }]"
          @click="drawerOpen = false"
        >
          <el-icon><component :is="item.icon" /></el-icon>
          <span class="nav-label">{{ item.title }}</span>
        </router-link>
        <div class="nav-seed">II/III 期多中心注册研究 · v0.1</div>
      </nav>
    </aside>

    <div class="app-main">
      <!-- 弱网/离线提示：断网、服务器不通、恢复后处理指引 -->
      <div v-if="!online" class="offline-banner">
        <el-icon><WarningFilled /></el-icon>
        <span>当前设备已离线（检测到网络断开）。数据暂无法提交，请不要重复点击操作；已打开页面可继续查看。</span>
        <span class="banner-spacer" />
        <el-button size="small" type="danger" plain @click="manualProbe">重新检测</el-button>
      </div>
      <div v-else-if="!serverUp" class="offline-banner server">
        <el-icon><Link /></el-icon>
        <span>网络已连接，但无法访问平台服务（可能是院内 VPN/弱网）。正在每 30 秒自动探活…</span>
        <span class="banner-spacer" />
        <el-button size="small" type="warning" plain @click="manualProbe">立即重试</el-button>
      </div>
      <div v-if="restoredVisible" class="reconnect-hint">
        <el-icon><CircleCheckFilled /></el-icon>
        <span>网络已恢复。为避免弱网期间产生重复提交，请点击「刷新数据」重新拉取最新状态后再继续操作。</span>
        <span class="banner-spacer" />
        <el-button size="small" type="success" plain @click="reloadAll">刷新数据</el-button>
        <el-button size="small" text color="#fff" @click="restoredVisible = false">知道了</el-button>
      </div>

      <header class="app-header">
        <el-button class="mobile-menu-btn" text @click="drawerOpen = true">
          <el-icon :size="22"><Menu /></el-icon>
        </el-button>
        <span class="page-context">{{ route.meta?.title || '溯源方' }}</span>
        <span class="header-spacer" />
        <el-icon :color="online && serverUp ? 'var(--status-good)' : 'var(--status-critical)'" :size="16">
          <component :is="online && serverUp ? 'Connection' : 'WarningFilled'" />
        </el-icon>
        <div class="header-user">
          <el-avatar :size="30" style="background: var(--brand-500)">
            {{ auth.user?.full_name?.slice(0, 1) }}
          </el-avatar>
          <div style="line-height: 1.25">
            <div style="font-weight: 600; font-size: 13px">
              {{ auth.user?.full_name }}
              <span class="role-chip">{{ auth.user?.role_label }}</span>
            </div>
            <div style="font-size: 11px; color: var(--ink-3)">
              {{ auth.user?.site?.name || '申办方/CRO（全中心）' }}
            </div>
          </div>
          <el-button text size="small" @click="logout">
            <el-icon><SwitchButton /></el-icon>&nbsp;退出
          </el-button>
        </div>
      </header>

      <main class="app-content">
        <router-view @data-reload="handleDataReload" />
      </main>
    </div>
  </div>
</template>

<script setup>
import { ref, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { ElMessageBox } from 'element-plus'
import { useAuthStore } from '@/stores/auth'
import { useConnectivity } from '@/composables/useConnectivity'

const route = useRoute()
const router = useRouter()
const auth = useAuthStore()
const { online, serverUp, restoredAt, probe } = useConnectivity()

const drawerOpen = ref(false)
const restoredVisible = ref(false)

const menus = [
  { name: 'dashboard', title: '入组作战台', icon: 'DataAnalysis', to: '/dashboard' },
  { name: 'subjects', title: '受试者', icon: 'User', to: '/subjects' },
]

watch([online, serverUp], ([on, up], [prevOn, prevUp]) => {
  if ((!prevOn || !prevUp) && on && up) restoredVisible.value = true
})
watch(restoredAt, () => { restoredVisible.value = true })

function manualProbe() { probe() }
function reloadAll() {
  restoredVisible.value = false
  window.location.reload()
}
function handleDataReload() { /* 供子页在恢复后触发，整页刷新最稳妥 */ }

async function logout() {
  await ElMessageBox.confirm('确认退出登录？', '提示', { type: 'warning', confirmButtonText: '退出', cancelButtonText: '取消' })
  auth.clear()
  router.push({ name: 'login' })
}
</script>
