<!--
  业务员 - 生成邀请码

  - 大字号展示 8 位邀请码
  - 二维码（指向 C 端注册页带 code 参数）
  - 倒计时 2:00:00，过期灰显
  - 今日剩余配额
  - 一键分享（open-type="share"）
  - 历史记录 Tab
-->
<template>
  <view class="page">
    <view class="hero">
      <view class="hero__title">
        邀请新客户
      </view>
      <view class="hero__sub">
        把邀请码发给客户，客户凭码即可注册绑定
      </view>
    </view>

    <view class="card">
      <view
        v-if="!code"
        class="card__empty"
      >
        <view class="card__hint">
          <text>点击下方按钮生成邀请码</text>
          <text class="card__hint2">
            2 小时有效 · 一次性使用
          </text>
        </view>
      </view>

      <view v-else>
        <view class="card__label">
          邀请码
        </view>
        <view class="card__code">
          {{ code.code }}
        </view>

        <view class="card__countdown">
          <text class="card__countdown-label">
            剩余
          </text>
          <text :class="['card__countdown-num', expired && 'card__countdown-num--expired']">
            {{ expired ? '已过期' : countdownText }}
          </text>
        </view>

        <!-- #ifdef H5 -->
        <view
          v-if="!expired && code.qr_svg"
          class="card__qr"
        >
          <!-- eslint-disable-next-line vue/no-v-text-v-html-on-component, vue/no-v-html -->
          <div class="card__qr-svg" v-html="code.qr_svg" />
          <text class="card__qr-hint">
            扫码直达注册页
          </text>
        </view>
        <!-- #endif -->
        <!-- #ifndef H5 -->
        <view
          v-if="!expired && code.deeplink"
          class="card__qr"
        >
          <view class="card__qr-placeholder">
            <text>注册链接</text>
            <text
              class="card__qr-hint"
              selectable
            >
              {{ code.deeplink }}
            </text>
          </view>
        </view>
        <!-- #endif -->
      </view>

      <view class="card__actions">
        <button
          v-if="code && !expired"
          class="card__btn card__btn--copy"
          @tap="onCopy"
        >
          复制邀请码
        </button>
        <button
          v-if="code && !expired"
          class="card__btn card__btn--share"
          open-type="share"
          @tap="onShare"
        >
          分享给客户
        </button>
        <!-- #ifdef MP-WEIXIN -->
        <!-- 真实小程序码（客户扫码可直接拉起小程序完成注册）；H5 端当前无意义，只保留 mp-weixin -->
        <button
          v-if="code && !expired"
          class="card__btn card__btn--share"
          :disabled="mpQrLoading"
          @tap="onSaveMpQr"
        >
          {{ mpQrLoading ? '下载中…' : '下载小程序码' }}
        </button>
        <!-- #endif -->
        <button
          class="card__btn card__btn--primary"
          :disabled="loading"
          @tap="onGenerate"
        >
          {{ code ? '重新生成' : '生成邀请码' }}
        </button>
      </view>

      <view class="card__quota">
        今日剩余 <text class="card__quota-num">
          {{ remainToday }}
        </text> 张
      </view>
    </view>

    <view class="section">
      <view class="section__title">
        最近邀请码
      </view>
      <view
        v-if="history.length === 0"
        class="section__empty"
      >
        暂无记录
      </view>
      <view
        v-for="h in history"
        :key="h.id"
        class="history"
      >
        <view class="history__main">
          <text class="history__code">
            {{ h.code }}
          </text>
          <text :class="['history__status', 'history__status--' + h.status]">
            {{ statusMap[h.status] }}
          </text>
        </view>
        <view class="history__meta">
          <text v-if="h.used_by_nick">
            被 {{ h.used_by_nick }} 使用
          </text>
          <text v-else-if="h.status === 'expired'">
            已过期
          </text>
          <text v-else-if="h.status === 'invalidated'">
            已作废
          </text>
        </view>
        <view class="history__time">
          {{ h.used_at || h.expires_at }}
        </view>
      </view>
    </view>
  </view>
</template>

<script setup>
const code = ref(null)
const remainToday = ref(20)
const loading = ref(false)
const history = ref([])
const countdownText = ref('02:00:00')
const expired = ref(false)
let timer = null

const statusMap = {
  used: '已使用',
  expired: '已过期',
  invalidated: '已作废',
  pending: '可使用'
}

const loadHistory = async () => {
  const res = await http.request({
    url: '/api/mall/salesman/invite-codes/history',
    method: 'GET',
    data: { limit: 10 }
  })
  history.value = res.data?.records || []
}

const onGenerate = async () => {
  loading.value = true
  try {
    const res = await http.request({
      url: '/api/mall/salesman/invite-codes',
      method: 'POST',
      data: {}
    })
    code.value = res.data
    remainToday.value = res.data.remaining_today ?? remainToday.value
    expired.value = false
    startCountdown()
    loadHistory()
  } catch (e) {
    uni.showToast({ title: e?.msg || '生成失败', icon: 'none' })
  } finally {
    loading.value = false
  }
}

const startCountdown = () => {
  if (timer) clearInterval(timer)
  const tick = () => {
    if (!code.value) return
    countdownText.value = salesman.countdown(code.value.expires_at)
    if (countdownText.value === '00:00:00') {
      expired.value = true
      clearInterval(timer)
    }
  }
  tick()
  timer = setInterval(tick, 1000)
}

const onCopy = () => {
  uni.setClipboardData({
    data: code.value.code,
    success: () => uni.showToast({ title: '已复制', icon: 'success' })
  })
}

const onShare = () => {
  uni.showToast({ title: '点右上角菜单分享', icon: 'none' })
}

// 下载小程序码（mp-weixin only）。拿到 PNG → 保存到相册（用户分享到微信聊天即可扫码）
const mpQrLoading = ref(false)
const onSaveMpQr = () => {
  if (!code.value?.id) return
  mpQrLoading.value = true
  const token = uni.getStorageSync('Token')
  uni.downloadFile({
    url: (import.meta.env.VITE_APP_BASE_API || '') + `/api/mall/salesman/invite-codes/${code.value.id}/qr-mp`,
    header: token ? { Authorization: token.startsWith('Bearer ') ? token : `Bearer ${token}` } : {},
    success: (r) => {
      if (r.statusCode !== 200) {
        mpQrLoading.value = false
        uni.showToast({ title: '下载失败', icon: 'none' })
        return
      }
      uni.saveImageToPhotosAlbum({
        filePath: r.tempFilePath,
        success: () => {
          uni.showToast({ title: '已保存到相册', icon: 'success' })
        },
        fail: (err) => {
          // 用户拒绝授权 / 已存在 etc
          uni.showToast({ title: err?.errMsg || '保存失败', icon: 'none' })
        },
        complete: () => { mpQrLoading.value = false }
      })
    },
    fail: () => {
      mpQrLoading.value = false
      uni.showToast({ title: '下载失败', icon: 'none' })
    }
  })
}

onShareAppMessage(() => ({
  title: `邀请您加入鑫久隆批发商城，邀请码 ${code.value?.code}`,
  path: `/pages/register-by-scan/register-by-scan?invite_code=${code.value?.code || ''}`
}))

onMounted(() => {
  loadHistory()
})

onUnmounted(() => {
  if (timer) clearInterval(timer)
})
</script>

<style lang="scss" scoped>
@import '@/styles/variables.scss';

.page {
  min-height: 100vh;
  background: $color-cream;
  padding-bottom: 40rpx;
}

.hero {
  padding: 48rpx 32rpx;
  background: $color-ink;
  color: #fff;

  &__title {
    font-size: 40rpx;
    font-weight: 600;
    color: $color-gold;
  }
  &__sub {
    margin-top: 8rpx;
    font-size: 24rpx;
    color: $color-gold-soft;
    opacity: 0.85;
  }
}

.card {
  margin: -28rpx 24rpx 0;
  padding: 36rpx 32rpx;
  background: $color-card;
  border-radius: 16rpx;
  box-shadow: 0 8rpx 40rpx rgba(14,14,14,0.08);

  &__empty {
    padding: 60rpx 0;
    text-align: center;
  }
  &__hint {
    color: $color-ink-soft;
    font-size: 28rpx;
    display: block;
  }
  &__hint2 {
    display: block;
    margin-top: 8rpx;
    font-size: 22rpx;
    color: $color-hint;
  }

  &__label {
    font-size: 24rpx;
    color: $color-hint;
    text-align: center;
  }
  &__code {
    margin-top: 12rpx;
    font-family: Menlo, Consolas, monospace;
    font-size: 72rpx;
    font-weight: 700;
    letter-spacing: 12rpx;
    color: $color-gold-deep;
    text-align: center;
  }

  &__countdown {
    margin-top: 24rpx;
    text-align: center;
  }
  &__countdown-label {
    font-size: 22rpx;
    color: $color-muted;
    margin-right: 8rpx;
  }
  &__countdown-num {
    font-family: Menlo, Consolas, monospace;
    font-size: 32rpx;
    font-weight: 600;
    color: $color-ink-soft;
    &--expired { color: $color-err; }
  }

  &__qr {
    margin-top: 32rpx;
    display: flex;
    flex-direction: column;
    align-items: center;
  }
  &__qr-svg {
    width: 320rpx;
    height: 320rpx;
    padding: 16rpx;
    background: #fff;
    border-radius: 12rpx;
    :deep(svg) {
      width: 100%;
      height: 100%;
      display: block;
    }
  }
  &__qr-placeholder {
    width: 320rpx;
    padding: 24rpx;
    background: $color-cream;
    border: 4rpx dashed $color-line;
    display: flex;
    flex-direction: column;
    align-items: center;
    justify-content: center;
    color: $color-hint;
    font-size: 26rpx;
    border-radius: 12rpx;
    word-break: break-all;
  }
  &__qr-hint {
    margin-top: 8rpx;
    font-size: 20rpx;
    color: $color-hint;
  }

  &__actions {
    margin-top: 32rpx;
    display: flex;
    flex-direction: column;
    gap: 16rpx;
  }
  &__btn {
    width: 100%;
    padding: 0 24rpx;
    height: 88rpx;
    line-height: 88rpx;
    font-size: 28rpx;
    border-radius: 12rpx;
    border: none;

    &--primary {
      background: $color-ink;
      color: $color-gold;
      font-weight: 600;
      letter-spacing: 2rpx;
    }
    &--copy {
      background: $color-card;
      color: $color-ink-soft;
      border: 2rpx solid $color-line;
    }
    &--share {
      background: $color-gold;
      color: $color-ink;
      font-weight: 600;
    }
  }

  &__quota {
    margin-top: 16rpx;
    text-align: center;
    font-size: 22rpx;
    color: $color-hint;
  }
  &__quota-num {
    color: $color-gold-deep;
    font-weight: 600;
  }
}

.section {
  margin: 24rpx;
  padding: 24rpx 32rpx;
  background: $color-card;
  border-radius: 16rpx;

  &__title {
    font-size: 28rpx;
    font-weight: 600;
    color: $color-ink-soft;
    margin-bottom: 16rpx;
    padding-left: 12rpx;
    border-left: 6rpx solid $color-gold;
  }
  &__empty {
    padding: 40rpx 0;
    text-align: center;
    font-size: 26rpx;
    color: $color-hint;
  }
}

.history {
  padding: 20rpx 0;
  border-bottom: 1rpx solid $color-line-soft;

  &:last-child { border-bottom: none; }

  &__main {
    display: flex;
    justify-content: space-between;
    align-items: center;
  }
  &__code {
    font-family: Menlo, Consolas, monospace;
    font-size: 28rpx;
    font-weight: 600;
    color: $color-ink-soft;
    letter-spacing: 4rpx;
  }
  &__status {
    padding: 4rpx 16rpx;
    border-radius: 20rpx;
    font-size: 22rpx;

    &--used { background: rgba(107,142,107,0.12); color: #6B8E6B; }
    &--expired { background: $color-line-soft; color: $color-hint; }
    &--invalidated { background: rgba(181,75,75,0.12); color: $color-err; }
    &--pending { background: rgba(201,169,97,0.18); color: $color-gold-deep; }
  }

  &__meta {
    margin-top: 8rpx;
    font-size: 24rpx;
    color: $color-muted;
  }
  &__time {
    margin-top: 4rpx;
    font-size: 22rpx;
    color: $color-hint;
  }
}
</style>
