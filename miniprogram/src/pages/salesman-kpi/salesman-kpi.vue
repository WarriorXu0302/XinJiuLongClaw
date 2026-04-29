<!--
  业务员 - 我的 KPI / 销售目标
-->
<template>
  <view class="page">
    <view class="header">
      <view class="header__title">
        销售目标
      </view>
      <view class="header__sub">
        {{ data.target?.target_year }} 年 {{ data.target?.target_month }} 月
      </view>
    </view>

    <view class="progress-card">
      <view class="progress-card__title">
        {{ metricLabel }} 完成率
      </view>
      <view class="progress-card__percent">
        {{ percent }}%
      </view>

      <view class="progress-card__bar">
        <view
          class="progress-card__bar-fill"
          :style="{ width: Math.min(percent, 100) + '%' }"
        />
        <view
          v-if="percent > 100"
          class="progress-card__bar-over"
          :style="{ width: Math.min(percent - 100, 20) + '%', left: '100%' }"
        />
      </view>

      <view class="progress-card__nums">
        <view class="progress-card__num">
          <text class="progress-card__num-label">
            已完成
          </text>
          <text class="progress-card__num-val">
            {{ fmtMoney(actual) }}
          </text>
        </view>
        <view class="progress-card__num">
          <text class="progress-card__num-label">
            目标
          </text>
          <text class="progress-card__num-val">
            {{ fmtMoney(target) }}
          </text>
        </view>
      </view>
    </view>

    <view class="bonus">
      <view class="bonus__title">
        奖金阶梯
      </view>
      <view class="bonus__tier">
        <view class="bonus__tier-top">
          <text>达成 100%</text>
          <text class="bonus__tier-amount">
            +{{ fmtMoney(data.target?.bonus_at_100) }}
          </text>
        </view>
        <view :class="['bonus__tier-bar', percent >= 100 && 'bonus__tier-bar--hit']">
          <view
            class="bonus__tier-bar-fill"
            :style="{ width: Math.min(percent / 100 * 100, 100) + '%' }"
          />
        </view>
      </view>
      <view class="bonus__tier">
        <view class="bonus__tier-top">
          <text>达成 120%</text>
          <text class="bonus__tier-amount">
            +{{ fmtMoney(data.target?.bonus_at_120) }}
          </text>
        </view>
        <view :class="['bonus__tier-bar', percent >= 120 && 'bonus__tier-bar--hit']">
          <view
            class="bonus__tier-bar-fill"
            :style="{ width: Math.min(percent / 120 * 100, 100) + '%' }"
          />
        </view>
      </view>

      <view
        v-if="data.bonus_next_tier"
        class="bonus__hint"
      >
        距离下一档（{{ data.bonus_next_tier.at }}）还差
        <text class="bonus__hint-num">
          {{ fmtMoney(data.bonus_next_tier.missing) }}
        </text>
      </view>
    </view>

    <view class="other">
      <view class="other__title">
        其他指标
      </view>
      <view class="other__row">
        <text class="other__key">
          销售额完成
        </text>
        <text class="other__val">
          {{ fmtMoney(data.actual?.actual_sales) }} / {{ fmtMoney(data.target?.sales_target) }}
        </text>
      </view>
      <view class="other__row">
        <text class="other__key">
          销售完成率
        </text>
        <text class="other__val">
          {{ Math.round((data.completion?.sales_completion || 0) * 100) }}%
        </text>
      </view>
    </view>
  </view>
</template>

<script setup>
const data = ref({ target: {}, actual: {}, completion: {} })

const fmtMoney = salesman.fmtMoney

const metricLabel = computed(() => {
  return data.value.target?.bonus_metric === 'sales' ? '销售额' : '回款'
})

const target = computed(() => {
  const t = data.value.target || {}
  return t.bonus_metric === 'sales' ? t.sales_target : t.receipt_target
})

const actual = computed(() => {
  const a = data.value.actual || {}
  const t = data.value.target || {}
  return t.bonus_metric === 'sales' ? a.actual_sales : a.actual_receipt
})

const percent = computed(() => {
  if (!target.value) return 0
  return Math.round((actual.value / target.value) * 100)
})

const load = async () => {
  const res = await http.request({
    url: '/api/mall/workspace/sales-targets/my-dashboard',
    method: 'GET'
  })
  data.value = res.data || { target: {}, actual: {}, completion: {} }
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
    font-size: 26rpx;
    color: $color-gold-soft;
  }
}

.progress-card {
  margin: -28rpx 24rpx 0;
  padding: 32rpx;
  background: $color-card;
  border-radius: 16rpx;
  box-shadow: 0 8rpx 40rpx rgba(14,14,14,0.08);
  text-align: center;

  &__title {
    font-size: 24rpx;
    color: $color-muted;
  }
  &__percent {
    margin-top: 12rpx;
    font-size: 88rpx;
    font-weight: 700;
    color: $color-gold-deep;
    line-height: 1;
    font-family: Menlo, Consolas, monospace;
  }
  &__bar {
    margin-top: 24rpx;
    position: relative;
    height: 16rpx;
    background: $color-line-soft;
    border-radius: 8rpx;
    overflow: visible;
  }
  &__bar-fill {
    height: 100%;
    background: $gold-gradient;
    border-radius: 8rpx;
  }
  &__bar-over {
    position: absolute;
    top: 0;
    height: 16rpx;
    background: #6B8E6B;
    border-radius: 8rpx;
  }
  &__nums {
    margin-top: 28rpx;
    display: flex;
    justify-content: space-around;
  }
  &__num { text-align: center; }
  &__num-label {
    display: block;
    font-size: 22rpx;
    color: $color-hint;
  }
  &__num-val {
    display: block;
    margin-top: 4rpx;
    font-size: 28rpx;
    font-weight: 600;
    color: $color-ink-soft;
  }
}

.bonus {
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

  &__tier {
    margin-top: 16rpx;
  }
  &__tier-top {
    display: flex;
    justify-content: space-between;
    align-items: baseline;
    font-size: 26rpx;
  }
  &__tier-amount {
    color: $color-gold-deep;
    font-weight: 700;
    font-size: 28rpx;
  }
  &__tier-bar {
    margin-top: 8rpx;
    height: 12rpx;
    background: $color-line-soft;
    border-radius: 6rpx;
    overflow: hidden;

    &--hit .bonus__tier-bar-fill { background: #6B8E6B; }
  }
  &__tier-bar-fill {
    height: 100%;
    background: $color-gold;
  }

  &__hint {
    margin-top: 20rpx;
    padding: 16rpx;
    background: $color-cream;
    border-radius: 8rpx;
    font-size: 24rpx;
    color: $color-muted;
    text-align: center;
  }
  &__hint-num {
    color: $color-gold-deep;
    font-weight: 600;
    margin-left: 4rpx;
  }
}

.other {
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
  &__row {
    display: flex;
    justify-content: space-between;
    padding: 12rpx 0;
    font-size: 26rpx;
  }
  &__key { color: $color-muted; }
  &__val {
    color: $color-ink-soft;
    font-weight: 600;
  }
}
</style>
