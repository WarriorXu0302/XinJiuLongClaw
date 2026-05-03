<!--
  业务员 - 我的订单列表（tabBar 第 2 个）

  4 Tab：待配送 / 待收款 / 待财务确认 / 已完成
  数据：GET /api/mall/salesman/orders?status_filter=in_transit|awaiting_payment|awaiting_finance|completed
-->
<template>
  <view class="page">
    <scroll-view
      scroll-x
      class="tabs"
      :scroll-into-view="'tab-' + activeTab"
      :show-scrollbar="false"
    >
      <view
        v-for="t in tabs"
        :id="'tab-' + t.key"
        :key="t.key"
        :class="['tabs__item', activeTab === t.key && 'tabs__item--active']"
        @tap="onTabChange(t.key)"
      >
        <text>{{ t.label }}</text>
        <text
          v-if="badge[t.key] > 0"
          class="tabs__badge"
        >
          {{ badge[t.key] }}
        </text>
      </view>
    </scroll-view>

    <view
      v-if="loading"
      class="state"
    >
      加载中…
    </view>
    <view
      v-else-if="orders.length === 0"
      class="state"
    >
      暂无订单
    </view>

    <view
      v-for="o in orders"
      :key="o.orderNo || o.order_no"
      class="card"
      @tap="toDetail(o)"
    >
      <view class="card__top">
        <text class="card__order">
          {{ o.orderNo || o.order_no }}
        </text>
        <text :class="['card__status', 'card__status--' + o.status]">
          {{ statusLabel(o.status) }}
        </text>
      </view>

      <view class="card__customer">
        <text class="card__nick">
          {{ o.customer_nick }}
        </text>
      </view>

      <view class="card__items">
        {{ o.items_brief }}
      </view>

      <view class="card__bottom">
        <text class="card__time">
          {{ relativeTime(o.createTime || o.created_at) }}
        </text>
        <text class="card__amount">
          {{ fmtMoney(o.payAmount || o.amount) }}
        </text>
      </view>

      <view
        v-if="o.status === 'assigned' || o.status === 'shipped' || o.status === 'delivered'"
        class="card__next"
      >
        下一步：
        <text class="card__next-text">
          {{ nextAction(o.status) }}
        </text>
      </view>
    </view>
    <SalesmanTabbar active="orders" />
  </view>
</template>

<script setup>
import SalesmanTabbar from '@/components/salesman-tabbar/salesman-tabbar.vue'

const activeTab = ref('in_transit')
const orders = ref([])
const loading = ref(false)
const badge = ref({ in_transit: 0, awaiting_payment: 0, awaiting_finance: 0, completed: 0 })

const tabs = salesman.ORDER_TAB_LABELS.map(x => ({ key: x.key, label: x.label }))

const statusLabel = (s) => salesman.ORDER_STATUS_LABEL[s] || s
const fmtMoney = salesman.fmtMoney
const relativeTime = salesman.relativeTime

const nextAction = (status) => {
  if (status === 'assigned') return '标记已出库'
  if (status === 'shipped') return '标记已送达'
  if (status === 'delivered') return '上传收款凭证'
  return ''
}

// 前端 tab key → 后端 MallOrderStatus 过滤；后端 status 支持逗号分隔多值
const TAB_STATUS_MAP = {
  in_transit: 'assigned,shipped',
  awaiting_payment: 'delivered',
  awaiting_finance: 'pending_payment_confirmation',
  completed: 'completed,partial_closed',
  refunded: 'refunded'
}

const loadOrders = async () => {
  loading.value = true
  try {
    const status = TAB_STATUS_MAP[activeTab.value]
    const res = await http.request({
      url: '/api/mall/salesman/orders',
      method: 'GET',
      data: status ? { status } : {}
    })
    orders.value = res.data?.records || []
  } finally {
    loading.value = false
  }
}

const loadBadges = async () => {
  const res = await http.request({
    url: '/api/mall/salesman/stats/order-count-badges',
    method: 'GET',
    dontTrunLogin: true
  })
  const d = res.data || {}
  badge.value = {
    in_transit: d.in_transit || 0,
    awaiting_payment: d.awaiting_payment || 0,
    awaiting_finance: d.awaiting_finance || 0,
    completed: 0
  }
}

const onTabChange = (k) => {
  if (activeTab.value === k) return
  activeTab.value = k
  loadOrders()
}

const toDetail = (o) => {
  // 详情页需要 order_id 调后端 GET/POST 接口；order_no 仅做展示用
  const orderId = o.orderId || o.order_id
  const orderNo = o.orderNo || o.order_no
  uni.navigateTo({
    url: `/pages/salesman-order-detail/salesman-order-detail?order_id=${orderId}&order_no=${orderNo}`
  })
}

onMounted(() => {
  loadOrders()
  loadBadges()
})

onShow(() => {
  loadOrders()
  loadBadges()
})

onPullDownRefresh(async () => {
  await loadOrders()
  uni.stopPullDownRefresh()
})
</script>

<style lang="scss" scoped>
@import '@/styles/variables.scss';

.page {
  min-height: 100vh;
  background: $color-cream;
  padding-bottom: calc(150rpx + env(safe-area-inset-bottom));
}

.tabs {
  position: sticky;
  top: 0;
  z-index: 10;
  display: flex;
  background: $color-card;
  border-bottom: 1rpx solid $color-line;
  white-space: nowrap;

  &__item {
    display: inline-flex;
    align-items: center;
    padding: 28rpx 32rpx;
    font-size: 28rpx;
    color: $color-muted;
    position: relative;

    &--active {
      color: $color-ink;
      font-weight: 600;
      &::after {
        content: '';
        position: absolute;
        left: 32rpx;
        right: 32rpx;
        bottom: 0;
        height: 4rpx;
        background: $color-gold;
        border-radius: 2rpx;
      }
    }
  }
  &__badge {
    margin-left: 8rpx;
    min-width: 30rpx;
    padding: 0 8rpx;
    height: 30rpx;
    line-height: 30rpx;
    background: $color-err;
    color: #fff;
    border-radius: 15rpx;
    font-size: 20rpx;
    text-align: center;
  }
}

.state {
  text-align: center;
  padding: 80rpx 0;
  color: $color-hint;
  font-size: 26rpx;
}

.card {
  margin: 24rpx 24rpx 0;
  padding: 28rpx 32rpx;
  background: $color-card;
  border-radius: 16rpx;
  box-shadow: 0 4rpx 24rpx rgba(14,14,14,0.04);

  &__top {
    display: flex;
    justify-content: space-between;
    align-items: center;
  }
  &__order {
    font-family: Menlo, Consolas, monospace;
    font-size: 24rpx;
    color: $color-muted;
  }
  &__status {
    font-size: 24rpx;
    font-weight: 600;
    padding: 4rpx 16rpx;
    border-radius: 20rpx;

    &--assigned, &--shipped { color: $color-gold-deep; background: rgba(201,169,97,0.12); }
    &--delivered { color: #B38000; background: rgba(255,200,0,0.12); }
    &--pending_payment_confirmation { color: #9E5A00; background: rgba(201,169,97,0.2); }
    &--completed { color: #6B8E6B; background: rgba(107,142,107,0.12); }
    &--partial_closed { color: $color-err; background: rgba(181,75,75,0.12); }
    &--cancelled, &--refunded { color: $color-hint; background: $color-line-soft; }
  }

  &__customer { margin-top: 16rpx; }
  &__nick {
    font-size: 30rpx;
    font-weight: 600;
    color: $color-ink-soft;
  }

  &__items {
    margin-top: 12rpx;
    padding: 14rpx 18rpx;
    background: $color-cream;
    border-radius: 8rpx;
    font-size: 24rpx;
    color: $color-ink-soft;
  }

  &__bottom {
    margin-top: 16rpx;
    display: flex;
    justify-content: space-between;
    align-items: center;
  }
  &__time {
    font-size: 22rpx;
    color: $color-hint;
  }
  &__amount {
    font-size: 32rpx;
    font-weight: 700;
    color: $color-gold-deep;
  }

  &__next {
    margin-top: 16rpx;
    padding-top: 16rpx;
    border-top: 1rpx dashed $color-line;
    font-size: 24rpx;
    color: $color-muted;
  }
  &__next-text {
    color: $color-gold-deep;
    font-weight: 600;
    margin-left: 8rpx;
  }
}
</style>
