<!--
  C 端注册页
    两种注册方式：
      1. 微信一键注册（mp-weixin 推荐）：邀请码 + uni.login → /wechat-register
      2. 账密注册：用户名 + 密码 + 邀请码 → /register

    invite_code 必填，可从 query ?code= / ?invite_code= / ?scene= 预填并锁定
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

      <!-- 注册方式切换 tab -->
      <!-- #ifdef MP-WEIXIN -->
      <view class="method-tabs">
        <view
          :class="['method-tabs__item', method === 'wechat' && 'method-tabs__item--active']"
          @tap="method = 'wechat'"
        >
          微信注册
        </view>
        <view
          :class="['method-tabs__item', method === 'password' && 'method-tabs__item--active']"
          @tap="method = 'password'"
        >
          账密注册
        </view>
      </view>
      <!-- #endif -->

      <view class="login-form">
        <!-- 账密字段：仅 method=password 显示 -->
        <block v-if="method === 'password'">
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
        </block>

        <!-- 邀请码：两种方式都要 -->
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
        <!-- #ifdef MP-WEIXIN -->
        <button
          v-if="method === 'wechat'"
          class="authorized-btn wechat"
          :disabled="submitting"
          @tap="onWechatRegister"
        >
          <text class="wechat__icon">
            💬
          </text>
          <text>{{ submitting ? '注册中…' : '微信一键注册' }}</text>
        </button>
        <!-- #endif -->
        <button
          v-if="method === 'password'"
          class="authorized-btn"
          :disabled="submitting"
          @tap="onPasswordRegister"
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

// mp-weixin 默认微信注册，其他平台默认账密
// 用运行时 process.env 判断而非条件编译，避免 ESLint 同标识符重复声明
const method = ref(
  // eslint-disable-next-line no-undef
  (typeof process !== 'undefined' && process.env?.UNI_PLATFORM === 'mp-weixin') ? 'wechat' : 'password'
)

onLoad((q) => {
  uni.setNavigationBarTitle({ title: '用户注册' })
  // 兼容三种 query 命名：?code=（老链接）/ ?invite_code=（分享卡片）/ ?scene=（小程序码）
  const raw = q?.code || q?.invite_code || q?.scene
  if (raw) {
    form.value.invite_code = String(raw).toUpperCase()
    inviteLocked.value = true
  }
})

const validateInvite = () => {
  if (!form.value.invite_code.trim()) {
    errorTips.value = 'invite'
    return false
  }
  return true
}

/**
 * 微信一键注册（mp-weixin only）
 *
 * 流程：验证邀请码 → uni.login 拿 code → /wechat-register
 * 后端：code2session 拿 openid → 若已注册直接登录（不消耗邀请码）
 *      否则消费邀请码 + 创建账号 + 签 token
 */
const onWechatRegister = () => {
  if (!validateInvite()) return
  errorTips.value = ''
  submitting.value = true
  uni.login({
    provider: 'weixin',
    success: ({ code }) => {
      if (!code) {
        submitting.value = false
        uni.showToast({ title: '微信授权失败，请重试', icon: 'none' })
        return
      }
      http.request({
        url: '/api/mall/auth/wechat-register',
        method: 'POST',
        login: true,
        hasCatch: true,
        data: {
          code,
          invite_code: form.value.invite_code.trim().toUpperCase()
        }
      }).then(({ data }) => {
        submitting.value = false
        uni.showToast({ title: '注册成功', icon: 'success', duration: 1200 })
        http.loginSuccess(data, () => {
          setTimeout(() => {
            salesman.dispatchAfterLogin(data.user_type || 'consumer')
          }, 1000)
        })
      }).catch((e) => {
        submitting.value = false
        uni.showToast({ title: e?.detail || e?.msg || '注册失败', icon: 'none' })
      })
    },
    fail: () => {
      submitting.value = false
      uni.showToast({ title: '微信授权失败，请重试', icon: 'none' })
    }
  })
}

const onPasswordRegister = async () => {
  if (!form.value.username.trim()) {
    errorTips.value = 'account'
    return
  }
  if (!form.value.password) {
    errorTips.value = 'password'
    return
  }
  if (!validateInvite()) return
  errorTips.value = ''
  submitting.value = true
  uni.showLoading({ title: '注册中…' })
  try {
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

.method-tabs {
  display: flex;
  margin: 0 60rpx 40rpx;
  background: #f5f3ef;
  border-radius: 16rpx;
  padding: 6rpx;

  &__item {
    flex: 1;
    text-align: center;
    padding: 20rpx 0;
    font-size: 26rpx;
    color: #666;
    border-radius: 12rpx;
    transition: all 0.2s;

    &--active {
      background: #fff;
      color: #C9A961;
      font-weight: 600;
      box-shadow: 0 2rpx 8rpx rgba(0, 0, 0, 0.06);
    }
  }
}

.hint-text {
  margin-top: 8rpx;
  font-size: 22rpx;
  color: #C9A961;
}

.authorized-btn.wechat {
  background: #07C160;
  color: #fff;

  .wechat__icon {
    margin-right: 8rpx;
  }
}
</style>
