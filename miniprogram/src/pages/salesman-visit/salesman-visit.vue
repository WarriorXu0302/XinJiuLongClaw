<!--
  业务员 - 拜访记录
  仅用于查看历史 + 当前进行中拜访；新建/结束拜访统一在 salesman-checkin 页面完成
-->
<template>
  <view class="page">
    <view class="header">
      <view class="header__title">
        客户拜访
      </view>
      <view class="header__sub">
        拜访时长 ≥ 30 分钟为有效；每日目标 6 家
      </view>
    </view>

    <view
      v-if="activeVisit"
      class="active"
      @tap="goCheckin"
    >
      <view class="active__title">
        进店中
      </view>
      <view class="active__name">
        {{ activeVisit.customer_name }}
      </view>
      <view class="active__time">
        进店于 {{ fmtTime(activeVisit.enter_time) }}
      </view>
      <view class="active__cta">
        前往离店打卡 ›
      </view>
    </view>
    <view
      v-else
      class="enter"
      @tap="goCheckin"
    >
      <view class="enter__title">
        新拜访
      </view>
      <view class="enter__cta">
        前往打卡中心（拜访）
      </view>
    </view>

    <view class="summary">
      <view class="summary__cell">
        <view class="summary__num">
          {{ todayValid }}
        </view>
        <view class="summary__label">
          今日有效
        </view>
      </view>
      <view class="summary__cell">
        <view class="summary__num">
          {{ todayTotal }}
        </view>
        <view class="summary__label">
          今日总数
        </view>
      </view>
      <view class="summary__cell">
        <view class="summary__num">
          {{ target }}
        </view>
        <view class="summary__label">
          日目标
        </view>
      </view>
    </view>

    <view class="section">
      <view class="section__title">
        最近拜访记录
      </view>
      <view
        v-if="records.length === 0"
        class="section__empty"
      >
        暂无记录
      </view>
      <view
        v-for="v in records"
        :key="v.id"
        class="row"
      >
        <view class="row__main">
          <text class="row__name">
            {{ v.customer_name }}
          </text>
          <text :class="['row__tag', v.is_valid ? 'row__tag--ok' : 'row__tag--invalid']">
            {{ v.is_valid ? '有效' : '时长不足' }}
          </text>
        </view>
        <view class="row__meta">
          {{ v.enter_time?.slice(5, 16) }}
          <text v-if="v.leave_time">
            - {{ v.leave_time?.slice(11, 16) }} · {{ v.duration_minutes }} 分钟
          </text>
          <text v-else>
            · 进店中
          </text>
        </view>
      </view>
    </view>
  </view>
</template>

<script setup>
const activeVisit = ref(null)
const records = ref([])
const target = ref(6)

const localDateStr = () => {
  const d = new Date()
  const pad = (n) => String(n).padStart(2, '0')
  return `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())}`
}
const todayRecords = computed(() => {
  const today = localDateStr()
  return records.value.filter(v => v.enter_time?.slice(0, 10) === today)
})
const todayTotal = computed(() => todayRecords.value.length)
const todayValid = computed(() => todayRecords.value.filter(v => v.is_valid).length)

const fmtTime = (iso) => {
  if (!iso) return ''
  const d = new Date(iso)
  return `${String(d.getHours()).padStart(2, '0')}:${String(d.getMinutes()).padStart(2, '0')}`
}

const loadActive = async () => {
  const res = await http.request({
    url: '/api/mall/workspace/attendance/visits/active',
    method: 'GET'
  })
  activeVisit.value = res.data || null
}

const loadRecords = async () => {
  const res = await http.request({
    url: '/api/mall/workspace/attendance/visits',
    method: 'GET'
  })
  records.value = res.data?.records || []
}

const goCheckin = () => {
  uni.navigateTo({ url: '/pages/salesman-checkin/salesman-checkin?mode=visit' })
}

onMounted(() => {
  loadActive()
  loadRecords()
})
onShow(() => {
  loadActive()
  loadRecords()
})
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
  }
}

.active {
  margin: 24rpx;
  padding: 32rpx;
  background: linear-gradient(135deg, #0E0E0E 0%, #2A211B 100%);
  color: #fff;
  border-radius: 16rpx;

  &__title { font-size: 22rpx; color: $color-gold-soft; }
  &__name { margin-top: 12rpx; font-size: 34rpx; font-weight: 700; color: $color-gold; }
  &__time { margin-top: 8rpx; font-size: 22rpx; color: rgba(255,255,255,0.6); }
  &__cta { margin-top: 16rpx; font-size: 24rpx; color: $color-gold; }
}

.enter {
  margin: 24rpx;
  padding: 32rpx;
  background: $color-card;
  border-radius: 16rpx;
  display: flex;
  justify-content: space-between;
  align-items: center;

  &__title { font-size: 28rpx; color: $color-ink-soft; font-weight: 600; }
  &__cta { font-size: 24rpx; color: $color-gold-deep; }
}

.summary {
  margin: 0 24rpx;
  display: flex;
  background: $color-card;
  border-radius: 16rpx;
  overflow: hidden;

  &__cell {
    flex: 1;
    padding: 24rpx 0;
    text-align: center;
    border-right: 1rpx solid $color-line-soft;

    &:last-child { border-right: none; }
  }
  &__num {
    font-size: 40rpx;
    font-weight: 700;
    color: $color-gold-deep;
    font-family: Menlo, Consolas, monospace;
  }
  &__label {
    margin-top: 4rpx;
    font-size: 22rpx;
    color: $color-hint;
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
    margin-bottom: 12rpx;
    padding-left: 12rpx;
    border-left: 6rpx solid $color-gold;
  }
  &__empty {
    padding: 40rpx 0;
    text-align: center;
    color: $color-hint;
  }
}

.row {
  padding: 16rpx 0;
  border-bottom: 1rpx solid $color-line-soft;

  &:last-child { border-bottom: none; }

  &__main {
    display: flex;
    justify-content: space-between;
    align-items: center;
  }
  &__name {
    font-size: 28rpx;
    color: $color-ink-soft;
  }
  &__tag {
    padding: 4rpx 14rpx;
    font-size: 22rpx;
    border-radius: 16rpx;

    &--ok { background: rgba(107,142,107,0.12); color: #6B8E6B; }
    &--invalid { background: $color-line-soft; color: $color-hint; }
  }
  &__meta {
    margin-top: 6rpx;
    font-size: 22rpx;
    color: $color-hint;
    font-family: Menlo, Consolas, monospace;
  }
}
</style>
