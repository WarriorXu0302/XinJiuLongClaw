<!--
  业务员 - 扫码稽查
-->
<template>
  <view class="page">
    <view class="header">
      <view class="header__title">
        扫码稽查
      </view>
      <view class="header__sub">
        扫商品条码查真伪、批次、出库仓信息
      </view>
    </view>

    <view
      class="scan-btn"
      @tap="onScan"
    >
      <text class="scan-btn__icon">
        ⌖
      </text>
      <text class="scan-btn__text">
        扫码
      </text>
    </view>

    <view
      v-if="scanResult"
      class="result"
    >
      <view class="result__top">
        <view :class="['result__badge', scanResult.is_valid ? 'result__badge--ok' : 'result__badge--warn']">
          {{ scanResult.is_valid ? '正品' : '异常' }}
        </view>
        <text class="result__barcode">
          {{ scanResult.barcode }}
        </text>
      </view>

      <view class="result__main">
        <text class="result__name">
          {{ scanResult.product_name }}
        </text>
        <view class="result__meta">
          <text>品牌：{{ scanResult.brand }}</text>
          <text>·</text>
          <text>批次：{{ scanResult.batch_no }}</text>
        </view>
        <view class="result__loc">
          最后出库仓：{{ scanResult.last_known_location }}
        </view>
      </view>

      <view
        v-if="scanResult.notes"
        class="result__note"
      >
        {{ scanResult.notes }}
      </view>

      <view class="result__actions">
        <view
          class="result__btn"
          @tap="onReport"
        >
          提交稽查
        </view>
      </view>
    </view>

    <view class="section">
      <view class="section__title">
        我的稽查记录
      </view>
      <view
        v-if="cases.length === 0"
        class="section__empty"
      >
        暂无记录
      </view>
      <view
        v-for="c in cases"
        :key="c.case_no"
        class="row"
      >
        <view class="row__top">
          <text class="row__no">
            {{ c.case_no }}
          </text>
          <text :class="['row__status', 'row__status--' + c.status]">
            {{ statusMap[c.status] }}
          </text>
        </view>
        <view class="row__body">
          <text>{{ typeMap[c.case_type] }} · 条码 {{ c.barcode }}</text>
        </view>
        <view class="row__meta">
          {{ c.created_at }}
        </view>
      </view>
    </view>
  </view>
</template>

<script setup>
const scanResult = ref(null)
const cases = ref([])

const statusMap = {
  pending: '待审批',
  approved: '已批准',
  executed: '已执行',
  closed: '已结案'
}
const typeMap = {
  outflow_malicious: '恶意外流',
  outflow_nonmalicious: '非恶意外流',
  outflow_transfer: '被转码',
  inflow_resell: '回购入库',
  inflow_transfer: '转码入库'
}

const onScan = () => {
  uni.scanCode({
    onlyFromCamera: false,
    success: async (res) => {
      const barcode = res.result
      await doQuery(barcode)
    },
    fail: () => {
      // 开发环境手动输入
      uni.showModal({
        title: '模拟扫码',
        editable: true,
        placeholderText: '输入条码',
        success: async (r) => {
          if (r.confirm && r.content) await doQuery(r.content)
        }
      })
    }
  })
}

const doQuery = async (barcode) => {
  uni.showLoading({ title: '查询中…' })
  try {
    const res = await http.request({
      url: '/api/mall/workspace/inspection-cases/scan',
      method: 'GET',
      data: { barcode }
    })
    scanResult.value = res.data
  } finally {
    uni.hideLoading()
  }
}

const onReport = () => {
  uni.showModal({
    title: '提交稽查',
    content: `提交后交由财务审核。确定稽查 ${scanResult.value.barcode} 吗？`,
    success: async (r) => {
      if (!r.confirm) return
      await http.request({
        url: '/api/mall/workspace/inspection-cases',
        method: 'POST',
        data: {
          barcode: scanResult.value.barcode,
          case_type: 'outflow_nonmalicious',
          batch_no: scanResult.value.batch_no
        }
      })
      uni.showToast({ title: '已提交', icon: 'success' })
      loadCases()
    }
  })
}

const loadCases = async () => {
  const res = await http.request({
    url: '/api/mall/workspace/inspection-cases',
    method: 'GET'
  })
  cases.value = res.data?.records || []
}

onMounted(() => loadCases())
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

.scan-btn {
  margin: 40rpx 24rpx;
  padding: 80rpx 0;
  background: $color-card;
  border: 4rpx dashed $color-gold;
  border-radius: 16rpx;
  display: flex;
  flex-direction: column;
  align-items: center;

  &__icon {
    font-size: 120rpx;
    color: $color-gold;
  }
  &__text {
    margin-top: 16rpx;
    font-size: 32rpx;
    font-weight: 600;
    color: $color-ink-soft;
  }
}

.result {
  margin: 24rpx;
  padding: 24rpx 32rpx;
  background: $color-card;
  border-radius: 16rpx;

  &__top {
    display: flex;
    align-items: center;
    gap: 16rpx;
  }
  &__badge {
    padding: 8rpx 20rpx;
    font-size: 24rpx;
    font-weight: 600;
    border-radius: 24rpx;

    &--ok { background: rgba(107,142,107,0.15); color: #6B8E6B; }
    &--warn { background: rgba(181,75,75,0.15); color: $color-err; }
  }
  &__barcode {
    font-family: Menlo, Consolas, monospace;
    font-size: 22rpx;
    color: $color-muted;
  }
  &__main {
    margin-top: 20rpx;
  }
  &__name {
    font-size: 32rpx;
    font-weight: 600;
    color: $color-ink-soft;
  }
  &__meta {
    margin-top: 8rpx;
    display: flex;
    gap: 8rpx;
    font-size: 24rpx;
    color: $color-muted;
  }
  &__loc {
    margin-top: 8rpx;
    font-size: 24rpx;
    color: $color-muted;
  }
  &__note {
    margin-top: 16rpx;
    padding: 16rpx;
    background: $color-cream;
    border-radius: 8rpx;
    font-size: 22rpx;
    color: $color-muted;
  }
  &__actions {
    margin-top: 20rpx;
  }
  &__btn {
    padding: 20rpx 0;
    background: $color-ink;
    color: $color-gold;
    text-align: center;
    border-radius: 12rpx;
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

  &__top {
    display: flex;
    justify-content: space-between;
    align-items: center;
  }
  &__no {
    font-family: Menlo, Consolas, monospace;
    font-size: 22rpx;
    color: $color-muted;
  }
  &__status {
    padding: 4rpx 14rpx;
    font-size: 22rpx;
    border-radius: 16rpx;

    &--pending { background: rgba(201,169,97,0.18); color: $color-gold-deep; }
    &--approved, &--executed { background: rgba(107,142,107,0.12); color: #6B8E6B; }
    &--closed { background: $color-line-soft; color: $color-hint; }
  }
  &__body {
    margin-top: 8rpx;
    font-size: 24rpx;
    color: $color-ink-soft;
  }
  &__meta {
    margin-top: 4rpx;
    font-size: 22rpx;
    color: $color-hint;
  }
}
</style>
