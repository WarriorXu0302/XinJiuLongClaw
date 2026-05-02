<!--
  业务员 - 我的考勤（月度汇总）
-->
<template>
  <view class="page">
    <view class="header">
      <view class="header__title">
        我的考勤
      </view>
      <view class="header__month">
        {{ summary.month }}
      </view>
    </view>

    <view class="grid">
      <view class="grid__cell">
        <text class="grid__num">
          {{ summary.checkin_days }}/{{ summary.work_days }}
        </text>
        <text class="grid__label">
          打卡天数
        </text>
      </view>
      <view class="grid__cell">
        <text :class="['grid__num', (summary.late_times || 0) > 0 && 'grid__num--warn']">
          {{ summary.late_times || 0 }}
        </text>
        <text class="grid__label">
          迟到次数
        </text>
      </view>
      <view class="grid__cell">
        <text :class="['grid__num', (summary.late_over30_times || 0) > 0 && 'grid__num--err']">
          {{ summary.late_over30_times || 0 }}
        </text>
        <text class="grid__label">
          超 30 分钟
        </text>
      </view>
      <view class="grid__cell">
        <text class="grid__num">
          {{ summary.leave_days || 0 }}
        </text>
        <text class="grid__label">
          请假天数
        </text>
      </view>
      <view class="grid__cell">
        <text class="grid__num">
          {{ summary.valid_visits || 0 }}
        </text>
        <text class="grid__label">
          有效拜访
        </text>
      </view>
      <view class="grid__cell">
        <text :class="['grid__num', summary.is_full_attendance && 'grid__num--ok']">
          {{ summary.is_full_attendance ? '是' : '否' }}
        </text>
        <text class="grid__label">
          全勤
        </text>
      </view>
    </view>

    <view class="section">
      <view class="section__title">
        近期打卡
      </view>
      <view
        v-for="r in records"
        :key="r.checkin_date"
        class="row"
      >
        <text class="row__date">
          {{ r.checkin_date }}
        </text>
        <view class="row__times">
          <text :class="['row__time', r.status_in === 'late' && 'row__time--warn']">
            上班 {{ r.work_in || '—' }}
          </text>
          <text class="row__time">
            下班 {{ r.work_out || '—' }}
          </text>
        </view>
        <text
          v-if="r.status_in === 'late'"
          class="row__tag row__tag--warn"
        >
          迟到
        </text>
      </view>
    </view>
  </view>
</template>

<script setup>
const summary = ref({})
const records = ref([])

const loadSummary = async () => {
  const res = await http.request({
    url: '/api/mall/workspace/attendance/monthly-summary',
    method: 'GET'
  })
  summary.value = res.data || {}
}

const loadRecords = async () => {
  const res = await http.request({
    url: '/api/mall/workspace/attendance/checkin',
    method: 'GET'
  })
  records.value = res.data?.records || []
}

onMounted(() => {
  loadSummary()
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
  &__month {
    margin-top: 8rpx;
    font-size: 26rpx;
    color: $color-gold-soft;
  }
}

.grid {
  margin: 24rpx;
  padding: 20rpx;
  background: $color-card;
  border-radius: 16rpx;
  display: grid;
  grid-template-columns: repeat(3, 1fr);
  gap: 16rpx;

  &__cell {
    padding: 24rpx 0;
    background: $color-cream;
    border-radius: 12rpx;
    text-align: center;
  }
  &__num {
    display: block;
    font-size: 36rpx;
    font-weight: 700;
    color: $color-gold-deep;

    &--warn { color: #B38000; }
    &--err { color: $color-err; }
  }
  &__label {
    display: block;
    margin-top: 8rpx;
    font-size: 22rpx;
    color: $color-muted;
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
}

.row {
  display: flex;
  align-items: center;
  gap: 16rpx;
  padding: 16rpx 0;
  border-bottom: 1rpx solid $color-line-soft;
  font-size: 26rpx;

  &:last-child { border-bottom: none; }

  &__date {
    width: 180rpx;
    color: $color-muted;
    font-family: Menlo, Consolas, monospace;
  }
  &__times {
    flex: 1;
    display: flex;
    flex-direction: column;
    gap: 4rpx;
  }
  &__time {
    color: $color-ink-soft;
    font-size: 24rpx;

    &--warn { color: #B38000; font-weight: 600; }
  }
  &__tag {
    padding: 4rpx 12rpx;
    font-size: 20rpx;
    border-radius: 12rpx;

    &--warn {
      background: rgba(179,128,0,0.12);
      color: #B38000;
    }
  }
}
</style>
