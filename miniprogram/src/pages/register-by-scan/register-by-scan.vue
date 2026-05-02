<!--
  扫码一键注册（小程序码入口）

  流程：
    1. 业务员生成邀请码 + /qr-mp 小程序码 PNG（scene = 邀请码）
    2. 客户微信扫码 → 小程序拉起本页，scene 从 onLoad query 拿
    3. 用户点"微信一键注册"
    4. uni.login 拿 wx_code
    5. 调 /api/mall/auth/wechat-register { code: wx_code, invite_code: scene }
    6. 后端：code2session 拿 openid + 消费邀请码 + 建 mall_user + 签 token
    7. 前端保存 token → 跳首页

  失败分支：
    - openid 已注册 → 后端返 409 → 引导用户直接用 wechat-login 登录
    - 邀请码过期/已用 → 提示联系业务员重新生成
-->
<template>
  <view class="page">
    <view class="hero">
      <view class="hero__logo">
        鑫久隆
      </view>
      <view class="hero__title">
        欢迎加入
      </view>
      <view class="hero__sub">
        您正在通过业务员推荐码注册
      </view>
    </view>

    <view
      v-if="inviteCode"
      class="info"
    >
      <view class="info__row">
        <text class="info__label">
          推荐码
        </text>
        <text class="info__code">
          {{ inviteCode }}
        </text>
      </view>
      <view
        v-if="salesmanNick"
        class="info__row"
      >
        <text class="info__label">
          推荐业务员
        </text>
        <text class="info__val">
          {{ salesmanNick }}
        </text>
      </view>
    </view>

    <view
      v-else
      class="state state--err"
    >
      未识别到邀请码，请联系业务员重新扫码
    </view>

    <!-- #ifdef MP-WEIXIN -->
    <button
      v-if="inviteCode && !loading"
      class="cta"
      open-type="getUserInfo"
      @getuserinfo="onWechatRegister"
    >
      微信一键注册
    </button>
    <!-- #endif -->
    <!-- #ifndef MP-WEIXIN -->
    <button
      v-if="inviteCode && !loading"
      class="cta"
      @tap="onWechatRegister"
    >
      微信一键注册
    </button>
    <!-- #endif -->

    <view
      v-if="loading"
      class="state"
    >
      注册中...
    </view>

    <view
      v-if="errorMsg"
      class="state state--err"
    >
      {{ errorMsg }}
    </view>

    <view class="footer">
      <text class="footer__hint">
        点击注册即表示同意《服务协议》和《隐私政策》
      </text>
      <view
        class="footer__alt"
        @tap="toPasswordLogin"
      >
        已有账号？直接登录
      </view>
    </view>
  </view>
</template>

<script setup>
const inviteCode = ref('')
const salesmanNick = ref('') // 预留字段，后端暂不返发码业务员昵称给未注册用户
const loading = ref(false)
const errorMsg = ref('')

/**
 * 扫码进来 scene 从 onLoad 的 options 拿；直接点进来（测试）可通过 query 传 code
 *
 * 小程序码 scene 微信传过来的字段名是 `scene`，其他入口（分享等）是 `invite_code`。
 */
onLoad((options) => {
  const raw = options?.scene ||
    options?.invite_code ||
    options?.code
  if (raw) {
    inviteCode.value = decodeURIComponent(raw).trim().toUpperCase()
  }
})

const onWechatRegister = () => {
  if (!inviteCode.value) {
    errorMsg.value = '邀请码缺失，无法注册'
    return
  }
  errorMsg.value = ''
  loading.value = true
  // 1. uni.login 拿 code（openid 换取依据）
  uni.login({
    provider: 'weixin',
    success: async ({ code }) => {
      if (!code) {
        loading.value = false
        errorMsg.value = '微信授权失败，请重试'
        return
      }
      try {
        const res = await http.request({
          url: '/api/mall/auth/wechat-register',
          method: 'POST',
          login: true,
          hasCatch: true,
          data: {
            code,
            invite_code: inviteCode.value
          }
        })
        http.loginSuccess(res.data || res, () => {
          uni.showToast({ title: '注册成功', icon: 'success' })
          setTimeout(() => {
            uni.reLaunch({ url: '/pages/index/index' })
          }, 600)
        })
      } catch (e) {
        loading.value = false
        errorMsg.value = e?.detail || e?.msg || '注册失败，请重试'
      }
    },
    fail: () => {
      loading.value = false
      errorMsg.value = '微信授权失败，请重试'
    }
  })
}

const toPasswordLogin = () => {
  uni.navigateTo({ url: '/pages/accountLogin/accountLogin' })
}
</script>

<style lang="scss" scoped>
@import '@/styles/variables.scss';

.page {
  min-height: 100vh;
  background: $color-cream;
  padding: 80rpx 48rpx;
}

.hero {
  text-align: center;
  margin-bottom: 64rpx;

  &__logo {
    font-size: 56rpx;
    font-weight: 700;
    color: $color-gold;
    margin-bottom: 16rpx;
  }
  &__title {
    font-size: 40rpx;
    font-weight: 600;
    color: $color-ink-soft;
    margin-bottom: 8rpx;
  }
  &__sub {
    font-size: 24rpx;
    color: $color-hint;
  }
}

.info {
  background: #fff;
  padding: 32rpx;
  border-radius: 16rpx;
  margin-bottom: 48rpx;

  &__row {
    display: flex;
    justify-content: space-between;
    align-items: center;
    padding: 16rpx 0;
    border-bottom: 1rpx solid $color-line;

    &:last-child {
      border-bottom: none;
    }
  }
  &__label {
    font-size: 26rpx;
    color: $color-hint;
  }
  &__code {
    font-size: 32rpx;
    font-weight: 600;
    color: $color-gold;
    letter-spacing: 4rpx;
  }
  &__val {
    font-size: 28rpx;
    color: $color-ink-soft;
  }
}

.cta {
  width: 100%;
  height: 88rpx;
  line-height: 88rpx;
  text-align: center;
  background: $color-gold;
  color: #fff;
  border-radius: 44rpx;
  font-size: 30rpx;
  font-weight: 600;
}

.state {
  text-align: center;
  padding: 32rpx;
  font-size: 26rpx;
  color: $color-hint;

  &--err {
    color: $color-err;
  }
}

.footer {
  margin-top: 64rpx;
  text-align: center;

  &__hint {
    display: block;
    font-size: 22rpx;
    color: $color-hint;
    margin-bottom: 16rpx;
  }
  &__alt {
    font-size: 26rpx;
    color: $color-gold;
  }
}
</style>
