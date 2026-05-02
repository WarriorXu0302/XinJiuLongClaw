<!--
  业务员 - 跳单告警

  mall_skip_alerts WHERE salesman_user_id = me
  字段：关联客户 / 跳单次数 / 状态
  操作：展开详情 + 申诉
-->
<template>
  <view class="page">
    <view class="header">
      <view class="header__title">
        跳单告警
      </view>
      <view class="header__sub">
        同一客户累计跳单 3 次触发告警。如认为记录有误可申诉。
      </view>
    </view>

    <view
      v-if="loading"
      class="state"
    >
      加载中…
    </view>
    <view
      v-else-if="alerts.length === 0"
      class="state state--ok"
    >
      <text class="state__emoji">
        ✓
      </text>
      <text>暂无告警</text>
    </view>

    <view
      v-for="a in alerts"
      :key="a.id"
      class="card"
    >
      <view class="card__top">
        <view class="card__left">
          <text class="card__customer">
            {{ a.customer?.nickname || '—' }}
          </text>
          <text class="card__phone">
            {{ a.customer?.masked_phone }}
          </text>
        </view>
        <text :class="['card__status', 'card__status--' + a.status]">
          {{ statusMap[a.status] }}
        </text>
      </view>

      <view class="card__summary">
        累计 <text class="card__num">
          {{ a.skip_count }}
        </text> 次跳单
        <text class="card__range">
          · {{ relativeTime(a.created_at) }}
        </text>
      </view>

      <view
        v-if="a.appeal_reason"
        class="card__appeal-info"
      >
        <text class="card__appeal-label">
          已提交申诉：
        </text>
        <text class="card__appeal-text">
          {{ a.appeal_reason }}
        </text>
      </view>

      <view
        v-if="a.resolution_note"
        class="card__appeal-info"
      >
        <text class="card__appeal-label">
          运营回复：
        </text>
        <text class="card__appeal-text">
          {{ a.resolution_note }}
        </text>
      </view>

      <view
        v-if="a.status === 'open' && !a.appeal_reason"
        class="card__actions"
      >
        <view
          class="card__appeal"
          @tap="onAppeal(a)"
        >
          <text>提交申诉</text>
        </view>
      </view>
    </view>
  </view>
</template>

<script setup>
const alerts = ref([])
const loading = ref(false)

const statusMap = salesman.SKIP_ALERT_STATUS_LABEL
const relativeTime = salesman.relativeTime

const load = async () => {
  loading.value = true
  try {
    const res = await http.request({
      url: '/api/mall/salesman/skip-alerts',
      method: 'GET'
    })
    alerts.value = res.data?.records || []
  } finally {
    loading.value = false
  }
}

const onAppeal = (a) => {
  // 小程序里 uni.showModal 的 editable 是目前最稳的跨端输入 UX；
  // 富文本输入框依赖自定义 rich-editor，非 H5 环境不通用 — 先这样
  uni.showModal({
    title: '提交申诉',
    editable: true,
    placeholderText: '请说明申诉理由（如：客户主动取消、超时由客观原因造成…）',
    confirmText: '提交',
    success: async (r) => {
      if (!r.confirm || !r.content) return
      await http.request({
        url: `/api/mall/salesman/skip-alerts/${a.id}/appeal`,
        method: 'POST',
        data: { reason: r.content }
      })
      uni.showToast({ title: '已提交申诉', icon: 'success' })
      load()
    }
  })
}

onMounted(() => load())
</script>

<style lang="scss" scoped>
@import '@/styles/variables.scss';

.page {
  min-height: 100vh;
  background: $color-cream;
  padding-bottom: 40rpx;
}

.header {
  padding: 40rpx 32rpx;
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
    line-height: 1.5;
  }
}

.state {
  padding: 120rpx 0;
  text-align: center;
  color: $color-hint;
  font-size: 26rpx;

  &--ok &__emoji {
    display: block;
    font-size: 80rpx;
    color: #6B8E6B;
    margin-bottom: 16rpx;
  }
}

.card {
  margin: 24rpx 24rpx 0;
  padding: 24rpx 32rpx;
  background: $color-card;
  border-radius: 16rpx;

  &__top {
    display: flex;
    justify-content: space-between;
    align-items: center;
  }
  &__left {
    display: flex;
    align-items: baseline;
    gap: 16rpx;
  }
  &__customer {
    font-size: 30rpx;
    font-weight: 600;
    color: $color-ink-soft;
  }
  &__phone {
    font-size: 22rpx;
    color: $color-muted;
  }
  &__status {
    padding: 6rpx 16rpx;
    border-radius: 20rpx;
    font-size: 22rpx;
    font-weight: 600;

    &--open { background: rgba(181,75,75,0.12); color: $color-err; }
    &--resolved { background: rgba(107,142,107,0.12); color: #6B8E6B; }
    &--dismissed { background: $color-line-soft; color: $color-hint; }
  }

  &__summary {
    margin-top: 16rpx;
    font-size: 26rpx;
    color: $color-ink-soft;
  }
  &__num {
    color: $color-err;
    font-size: 32rpx;
    font-weight: 700;
    margin: 0 4rpx;
  }
  &__range {
    font-size: 22rpx;
    color: $color-hint;
  }

  &__logs {
    margin-top: 20rpx;
    padding: 16rpx 20rpx;
    background: $color-cream;
    border-radius: 8rpx;
  }
  &__actions {
    margin-top: 20rpx;
  }
  &__appeal {
    padding: 18rpx 0;
    border: 2rpx solid $color-ink;
    color: $color-ink;
    text-align: center;
    border-radius: 12rpx;
    font-size: 26rpx;
    font-weight: 600;
  }
}

.log {
  display: flex;
  align-items: center;
  gap: 16rpx;
  padding: 8rpx 0;
  font-size: 22rpx;

  &__type {
    color: $color-err;
    font-weight: 600;
  }
  &__order {
    flex: 1;
    font-family: Menlo, Consolas, monospace;
    color: $color-muted;
  }
  &__time { color: $color-hint; }
}
</style>
