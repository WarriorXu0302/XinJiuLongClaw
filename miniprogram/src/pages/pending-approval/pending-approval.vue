<!--
  注册提交后的"审批中"页。

  - 路径 query: ?application_id=<uuid>
  - 页面每 10 秒轮询 /api/mall/auth/application-status
  - pending: 显示"等待审核"
  - approved: 提示"审核通过"，自动跳登录页
  - rejected: 显示驳回理由 + "联系业务员重新申请"按钮
-->
<template>
  <view class="page">
    <view class="hero">
      <view
        v-if="status === 'pending'"
        class="hero__icon hero__icon--pending"
      >
        ⏳
      </view>
      <view
        v-else-if="status === 'approved'"
        class="hero__icon hero__icon--ok"
      >
        ✅
      </view>
      <view
        v-else-if="status === 'rejected'"
        class="hero__icon hero__icon--err"
      >
        ❌
      </view>

      <view class="hero__title">
        {{ titleText }}
      </view>
      <view class="hero__sub">
        {{ subText }}
      </view>
    </view>

    <view
      v-if="status === 'rejected' && rejectionReason"
      class="reject-box"
    >
      <view class="reject-box__label">
        驳回原因
      </view>
      <view class="reject-box__text">
        {{ rejectionReason }}
      </view>
    </view>

    <view class="actions">
      <button
        v-if="status === 'approved'"
        class="btn btn--primary"
        @tap="toLogin"
      >
        去登录
      </button>
      <button
        v-if="status === 'rejected'"
        class="btn btn--primary"
        @tap="toRegister"
      >
        联系业务员重新申请
      </button>
      <button
        v-if="status === 'pending'"
        class="btn btn--ghost"
        @tap="refreshNow"
      >
        刷新状态
      </button>
      <button
        class="btn btn--ghost"
        @tap="toIndex"
      >
        回到首页
      </button>
    </view>
  </view>
</template>

<script setup>
const applicationId = ref('')
const status = ref('pending')
const rejectionReason = ref('')
let pollTimer = null

const titleText = computed(() => {
  if (status.value === 'approved') return '审核通过'
  if (status.value === 'rejected') return '审核未通过'
  return '资料审核中'
})
const subText = computed(() => {
  if (status.value === 'approved') return '您的账号已激活，现在可以登录使用'
  if (status.value === 'rejected') return '请联系业务员重新申请'
  return '通常 1 个工作日内完成，审核结果会推送到您的手机'
})

const loadStatus = async () => {
  if (!applicationId.value) return
  try {
    const res = await http.request({
      url: '/api/mall/auth/application-status',
      method: 'GET',
      login: true, // 跳过 refreshToken 前置
      hasCatch: true,
      data: { application_id: applicationId.value }
    })
    const d = res.data || {}
    status.value = d.application_status || 'pending'
    rejectionReason.value = d.rejection_reason || ''
    if (status.value === 'approved') {
      stopPolling()
      uni.showToast({ title: '审核通过！', icon: 'success' })
      // 3 秒后自动跳登录
      setTimeout(toLogin, 3000)
    } else if (status.value === 'rejected') {
      stopPolling()
    }
  } catch {
    // 轮询失败不阻塞 UI；下次继续尝试
  }
}

const startPolling = () => {
  stopPolling()
  pollTimer = setInterval(loadStatus, 10000)
}
const stopPolling = () => {
  if (pollTimer) {
    clearInterval(pollTimer)
    pollTimer = null
  }
}

const refreshNow = () => loadStatus()
const toLogin = () => uni.reLaunch({ url: '/pages/accountLogin/accountLogin' })
const toRegister = () => uni.reLaunch({ url: '/pages/register/register' })
const toIndex = () => uni.switchTab({ url: '/pages/index/index' })

onLoad((q) => {
  uni.setNavigationBarTitle({ title: '审核进度' })
  applicationId.value = q?.application_id || ''
  if (applicationId.value) {
    loadStatus()
    startPolling()
  }
})

onUnload(() => stopPolling())
onHide(() => stopPolling())
onShow(() => {
  if (applicationId.value && status.value === 'pending') {
    loadStatus()
    startPolling()
  }
})
</script>

<style lang="scss" scoped>
@import '@/styles/variables.scss';

.page {
  min-height: 100vh;
  background: $color-cream;
  padding: 120rpx 48rpx;
}

.hero {
  text-align: center;
  margin-bottom: 64rpx;

  &__icon {
    font-size: 120rpx;
    line-height: 1;
    margin-bottom: 32rpx;
  }
  &__title {
    font-size: 40rpx;
    font-weight: 600;
    color: $color-ink-soft;
    margin-bottom: 16rpx;
  }
  &__sub {
    font-size: 26rpx;
    color: $color-hint;
    line-height: 1.6;
  }
}

.reject-box {
  background: rgba(181, 75, 75, 0.08);
  border: 1rpx solid rgba(181, 75, 75, 0.2);
  border-radius: 12rpx;
  padding: 24rpx;
  margin-bottom: 48rpx;

  &__label {
    font-size: 24rpx;
    color: $color-err;
    font-weight: 600;
    margin-bottom: 12rpx;
  }
  &__text {
    font-size: 26rpx;
    color: $color-ink-soft;
    line-height: 1.6;
  }
}

.actions {
  display: flex;
  flex-direction: column;
  gap: 20rpx;
}

.btn {
  height: 88rpx;
  line-height: 88rpx;
  border-radius: 44rpx;
  font-size: 28rpx;
  text-align: center;

  &--primary {
    background: $color-gold;
    color: #fff;
  }
  &--ghost {
    background: transparent;
    color: $color-ink-soft;
    border: 1rpx solid $color-line;
  }

  &::after {
    border: 0;
  }
}
</style>
