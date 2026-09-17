<template>
  <div class="login-wrap">
    <div class="login-card">
      <div class="login-brand">
        <span class="logo-mark"><el-icon><Connection /></el-icon></span>
        <h1>溯源方</h1>
      </div>
      <div class="login-sub">受试者访视与数据质疑协同平台 · II/III 期多中心注册研究</div>

      <el-form :model="form" :rules="rules" ref="formRef" @submit.prevent="submit">
        <el-form-item prop="username">
          <el-input v-model="form.username" size="large" placeholder="用户名" :prefix-icon="User" />
        </el-form-item>
        <el-form-item prop="password">
          <el-input v-model="form.password" size="large" type="password" show-password
                    placeholder="密码" :prefix-icon="Lock" @keyup.enter="submit" />
        </el-form-item>
        <el-button type="primary" size="large" style="width: 100%" :loading="loading" @click="submit">
          登 录
        </el-button>
      </el-form>

      <div v-if="!online" class="offline-banner" style="margin-top: 16px; border-radius: 8px; padding: 10px 12px">
        <el-icon><WarningFilled /></el-icon>
        <span>当前设备离线，请恢复网络后登录。</span>
      </div>

      <div class="login-hint">
        <div style="font-weight:600; margin-bottom:4px">演示账号（密码统一 <code>Suyuan@2026</code>）：</div>
        <div><code>dm</code> 数据管理员（跨中心）　<code>inv01</code> 北京中心研究者</div>
        <div><code>inv02/inv03</code> 上海/广州研究者　<code>mon01~03</code> 各中心监查员</div>
      </div>
    </div>
  </div>
</template>

<script setup>
import { ref } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { ElMessage } from 'element-plus'
import { User, Lock } from '@element-plus/icons-vue'
import { authApi } from '@/api'
import { useAuthStore } from '@/stores/auth'
import { useConnectivity } from '@/composables/useConnectivity'

const router = useRouter()
const route = useRoute()
const auth = useAuthStore()
const { online } = useConnectivity()

const formRef = ref()
const loading = ref(false)
const form = ref({ username: 'inv01', password: 'Suyuan@2026' })
const rules = {
  username: [{ required: true, message: '请输入用户名', trigger: 'blur' }],
  password: [{ required: true, message: '请输入密码', trigger: 'blur' }],
}

async function submit() {
  await formRef.value.validate(async (valid) => {
    if (!valid) return
    if (!online.value) {
      ElMessage.error('设备当前离线，请恢复网络后再登录')
      return
    }
    loading.value = true
    try {
      const data = await authApi.login(form.value.username, form.value.password)
      auth.setSession(data.access_token, data.user)
      ElMessage.success(`欢迎，${data.user.full_name}`)
      router.push(route.query.redirect || '/dashboard')
    } catch (e) {
      ElMessage.error(e.message || '登录失败')
    } finally {
      loading.value = false
    }
  })
}
</script>
