<!--
  C 端注册页
    - invite_code 必填（从 query 自动填入业务员分享的链接里的 code）
    - 成功后原子消费 invite_code + 创建 mall_user + 绑定 referrer_salesman_id
    - 响应返回 token + user_type，按 user_type 分流入口
-->
<template>
  <view class="register">
    <view class="con">
      <view class="brand">
        <text class="brand__mark">
          鑫
        </text>
        <text class="brand__name">
          鑫久隆
        </text>
        <text class="brand__sub">
          XIN JIU LONG · 批发商城
        </text>
      </view>

      <view class="login-form">
        <view :class="['item', errorTips === 'account' && 'error']">
          <view class="account">
            <input
              v-model="form.username"
              type="text"
              placeholder-class="inp-palcehoder"
              placeholder="请输入账号名称"
            >
          </view>
          <view
            v-if="errorTips === 'account'"
            class="error-text"
          >
            <text class="warning-icon">
              !
            </text>
            请输入账号！
          </view>
        </view>

        <view :class="['item', errorTips === 'password' && 'error']">
          <view class="account">
            <input
              v-model="form.password"
              type="password"
              placeholder-class="inp-palcehoder"
              placeholder="请输入密码"
            >
          </view>
          <view
            v-if="errorTips === 'password'"
            class="error-text"
          >
            <text class="warning-icon">
              !
            </text>
            请输入密码！
          </view>
        </view>

        <view :class="['item', errorTips === 'invite' && 'error']">
          <view class="account">
            <input
              v-model="form.invite_code"
              type="text"
              maxlength="8"
              :disabled="inviteLocked"
              placeholder-class="inp-palcehoder"
              placeholder="邀请码（业务员提供，必填）"
            >
          </view>
          <view
            v-if="inviteLocked"
            class="hint-text"
          >
            已自动填入业务员分享的邀请码
          </view>
          <view
            v-if="errorTips === 'invite'"
            class="error-text"
          >
            <text class="warning-icon">
              !
            </text>
            请输入邀请码！
          </view>
        </view>

        <view class="operate">
          <view
            class="to-register"
            @tap="toLogin"
          >
            已有账号？
            <text>去登录></text>
          </view>
        </view>
      </view>

      <view>
        <button
          class="authorized-btn"
          :disabled="submitting"
          @tap="toRegister"
        >
          {{ submitting ? '注册中…' : '注册' }}
        </button>
        <button
          class="to-idx-btn"
          @tap="toIndex"
        >
          回到首页
        </button>
      </view>
    </view>
  </view>
</template>

<script setup>
const form = ref({
  username: '',
  password: '',
  invite_code: ''
})
const inviteLocked = ref(false)
const errorTips = ref('')
const submitting = ref(false)

onLoad((q) => {
  uni.setNavigationBarTitle({ title: '用户注册' })
  if (q?.code) {
    form.value.invite_code = String(q.code).toUpperCase()
    inviteLocked.value = true
  }
})

const toRegister = async () => {
  if (!form.value.username.trim()) {
    errorTips.value = 'account'
    return
  }
  if (!form.value.password) {
    errorTips.value = 'password'
    return
  }
  if (!form.value.invite_code.trim()) {
    errorTips.value = 'invite'
    return
  }
  errorTips.value = ''
  submitting.value = true
  uni.showLoading({ title: '注册中…' })
  try {
    // ERP 端 bcrypt，前端明文传输（HTTPS 保底），不走旧 mall4j RSA 加密
    const res = await http.request({
      url: '/api/mall/auth/register',
      method: 'POST',
      login: true,
      data: {
        username: form.value.username.trim(),
        password: form.value.password,
        invite_code: form.value.invite_code.trim().toUpperCase()
      }
    })
    uni.hideLoading()
    uni.showToast({ title: '注册成功', icon: 'success', duration: 1200 })
    const data = res.data || {}
    if (data.token) {
      // 统一走 loginSuccess：Token / RefreshToken / expiresTimeStamp / userType 一次性写齐
      http.loginSuccess(data, () => {
        setTimeout(() => {
          salesman.dispatchAfterLogin(data.user_type || 'consumer')
        }, 1200)
      })
    } else {
      setTimeout(() => uni.navigateTo({ url: '/pages/accountLogin/accountLogin' }), 1200)
    }
  } catch (e) {
    uni.hideLoading()
    uni.showToast({ title: e?.msg || '注册失败', icon: 'none' })
  } finally {
    submitting.value = false
  }
}

const toLogin = () => uni.navigateTo({ url: '/pages/accountLogin/accountLogin' })
const toIndex = () => uni.switchTab({ url: '/pages/index/index' })
</script>

<style lang="scss" scoped>
@import "./register.scss";

.hint-text {
  margin-top: 8rpx;
  font-size: 22rpx;
  color: #C9A961;
}
</style>
