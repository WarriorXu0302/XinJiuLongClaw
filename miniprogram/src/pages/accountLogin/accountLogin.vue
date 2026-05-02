<template>
  <view class="con">
    <view class="brand">
      <text class="brand__mark">鑫</text>
      <text class="brand__name">鑫久隆</text>
      <text class="brand__sub">XIN JIU LONG · 批发商城</text>
    </view>
    <!-- 登录 -->
    <view class="login-form">
      <view :class="['item',errorTips==1? 'error':'']">
        <view class="account">
          <input
            type="text"
            data-type="account"
            placeholder-class="inp-palcehoder"
            placeholder="请输入用户名"
            @input="getInputVal"
          >
        </view>
        <view
          v-if="errorTips==1"
          class="error-text"
        >
          <text class="warning-icon">
            !
          </text>
          请输入账号！
        </view>
      </view>
      <view :class="['item',errorTips==2? 'error':'']">
        <view class="account">
          <input
            type="password"
            data-type="password"
            placeholder-class="inp-palcehoder"
            placeholder="请输入密码"
            @input="getInputVal"
          >
        </view>
        <view
          v-if="errorTips==2"
          class="error-text"
        >
          <text class="warning-icon">
            !
          </text>
          请输入密码！
        </view>
      </view>
      <view class="operate">
        <view
          class="to-register"
          @tap="toRegitser"
        >
          还没有账号？
          <text>去注册></text>
        </view>
      </view>
    </view>

    <view>
      <button
        class="authorized-btn"
        @tap="login"
      >
        登录
      </button>

      <!-- #ifdef MP-WEIXIN -->
      <view class="divider">
        <text class="divider__line" />
        <text class="divider__text">或</text>
        <text class="divider__line" />
      </view>
      <button
        class="wechat-btn"
        :disabled="wxLoading"
        @tap="onWechatLogin"
      >
        <text class="wechat-btn__icon">💬</text>
        <text>{{ wxLoading ? '登录中…' : '微信一键登录' }}</text>
      </button>
      <!-- #endif -->
    </view>
  </view>
</template>

<script setup>
/**
 * 生命周期函数--监听页面显示
 */
onShow(() => {
  uni.setNavigationBarTitle({
    title: '用户登录'
  })
})

const principal = ref('') // 账号
const errorTips = ref(0) // 错误提示
watch(
  () => principal.value,
  () => {
    errorTips.value = 0
  }
)

const credentials = ref('') // 密码
/**
 * 输入框的值
 */
const getInputVal = (e) => {
  const type = e.currentTarget.dataset.type
  if (type == 'account') {
    principal.value = e.detail.value
  } else if (type == 'password') {
    credentials.value = e.detail.value
  }
}

/**
 * 登录（ERP /api/mall/auth/login-password，bcrypt 比对，明文传 HTTPS）
 */
const login = () => {
  if (principal.value.length == 0) {
    errorTips.value = 1
    return
  }
  if (credentials.value.length == 0) {
    errorTips.value = 2
    return
  }
  errorTips.value = 0

  http.request({
    url: '/api/mall/auth/login-password',
    method: 'POST',
    login: true,
    data: {
      username: principal.value,
      password: credentials.value
    }
  })
    .then(({ data }) => {
      http.loginSuccess(data, () => {
        uni.showToast({ title: '登录成功', icon: 'none' })
        setTimeout(() => {
          salesman.dispatchAfterLogin(data.user_type || 'consumer')
        }, 800)
      })
    })
    .catch(() => {
      // http.js 已 toast detail，这里兜底
    })
}

/**
 * 去注册
 */
const toRegitser = () => {
  uni.navigateTo({
    url: '/pages/register/register'
  })
}

/**
 * 微信一键登录（mp-weixin 专用）
 *
 * 流程：
 *   uni.login 拿 code → /api/mall/auth/wechat-login
 *   - 200 → loginSuccess + dispatchAfterLogin 分流到 consumer/salesman 首页
 *   - 404  → openid 未注册，引导去扫业务员邀请码或手动输邀请码注册
 *   - 403 → 账号停用/归档，提示联系客服
 */
const wxLoading = ref(false)
const onWechatLogin = () => {
  wxLoading.value = true
  uni.login({
    provider: 'weixin',
    success: ({ code }) => {
      if (!code) {
        wxLoading.value = false
        uni.showToast({ title: '微信授权失败，请重试', icon: 'none' })
        return
      }
      http.request({
        url: '/api/mall/auth/wechat-login',
        method: 'POST',
        login: true,
        hasCatch: true,
        data: { code }
      }).then(({ data }) => {
        http.loginSuccess(data, () => {
          uni.showToast({ title: '登录成功', icon: 'none' })
          setTimeout(() => {
            salesman.dispatchAfterLogin(data.user_type || 'consumer')
          }, 800)
        })
      }).catch((e) => {
        wxLoading.value = false
        // 未注册：后端返 404 "账号未注册，请输入邀请码完成注册"
        if (e?.status === 404) {
          uni.showModal({
            title: '您还没有账号',
            content: '请扫业务员分享的邀请码，或手动输入邀请码注册',
            confirmText: '去注册',
            success: (r) => {
              if (r.confirm) {
                uni.navigateTo({ url: '/pages/register/register' })
              }
            }
          })
          return
        }
        uni.showToast({ title: e?.detail || e?.msg || '登录失败', icon: 'none' })
      })
    },
    fail: () => {
      wxLoading.value = false
      uni.showToast({ title: '微信授权失败，请重试', icon: 'none' })
    }
  })
}

/**
 * 回到首页
 */
</script>

<style scoped lang="scss">
@import "./accountLogin.scss";
</style>
