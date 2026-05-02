<!--
  业务员工作台首页 - 接单池（tabBar 第 1 个）

  两个 Tab：
    - 我的客户（my）  — 推荐人独占期订单，带倒计时
    - 抢单广场（public）— 开放期订单，所有业务员都能抢

  数据：GET /api/mall/salesman/orders/pool?scope=my|public
  操作：POST /api/mall/salesman/orders/{order_id}/claim
  角标：GET /api/mall/salesman/stats/order-count-badges → my_pool 数
-->
<template>
  <view class="page">
    <view class="header">
      <view class="header__title">
        接单池
      </view>
      <view class="header__subtitle">
        {{ headerSubtitle }}
      </view>
    </view>

    <view class="tabs">
      <view
        v-for="t in tabs"
        :key="t.key"
        :class="['tabs__item', activeTab === t.key && 'tabs__item--active']"
        @tap="onTabChange(t.key)"
      >
        <text>{{ t.label }}</text>
        <text
          v-if="t.key === 'my' && badgeMyPool > 0"
          class="tabs__badge"
        >
          {{ badgeMyPool }}
        </text>
      </view>
    </view>

    <view
      v-if="loading"
      class="state"
    >
      <text>加载中…</text>
    </view>
    <view
      v-else-if="orders.length === 0"
      class="state"
    >
      <text>暂无可接订单</text>
    </view>

    <view
      v-for="o in orders"
      :key="o.orderNo || o.order_no"
      class="card"
    >
      <view class="card__top">
        <text class="card__order">
          {{ o.orderNo || o.order_no }}
        </text>
        <text class="card__time">
          {{ relativeTime(o.createTime || o.created_at) }}
        </text>
      </view>

      <view class="card__customer">
        <text class="card__nick">
          {{ o.customer_nick }}
        </text>
        <text class="card__phone">
          {{ o.masked_phone }}
        </text>
      </view>

      <view class="card__addr">
        <text class="card__icon">📍</text>
        <text>{{ o.brief_address }}</text>
      </view>

      <view class="card__items">
        {{ o.items_brief }}
      </view>

      <view class="card__bottom">
        <text class="card__amount">
          {{ fmtMoney(o.payAmount || o.amount) }}
        </text>
        <view class="card__actions">
          <text
            v-if="o.expires_at"
            class="card__timer"
          >
            独占 {{ countdownMap[o.orderNo || o.order_no] || '00:00:00' }}
          </text>
          <view
            class="card__claim"
            @tap="onClaim(o)"
          >
            <text>抢单</text>
          </view>
        </view>
      </view>
    </view>
    <SalesmanTabbar active="home" />
  </view>
</template>

<script setup>
import SalesmanTabbar from '@/components/salesman-tabbar/salesman-tabbar.vue'

const activeTab = ref('my')
const orders = ref([])
const loading = ref(false)
const badgeMyPool = ref(0)
const countdownMap = ref({})
let countdownTimer = null

const tabs = [
  { key: 'my', label: '我的客户' },
  { key: 'public', label: '抢单广场' }
]

const headerSubtitle = computed(() =>
  activeTab.value === 'my' ? '推荐关系绑定，独占期内优先接单' : '超时未接单已开放，先到先得'
)

const loadPool = async () => {
  loading.value = true
  try {
    const res = await http.request({
      url: '/api/mall/salesman/orders/pool',
      method: 'GET',
      data: { scope: activeTab.value }
    })
    const body = res.data ?? res
    orders.value = body?.records || []
    refreshCountdowns()
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
  badgeMyPool.value = res.data?.my_pool || 0
  if (badgeMyPool.value > 0) {
    uni.setTabBarBadge({ index: 0, text: String(badgeMyPool.value), fail: () => {} })
  } else {
    uni.removeTabBarBadge({ index: 0, fail: () => {} })
  }
}

const refreshCountdowns = () => {
  const m = {}
  orders.value.forEach(o => {
    const key = o.orderNo || o.order_no
    if (o.expires_at) m[key] = salesman.countdown(o.expires_at)
  })
  countdownMap.value = m
}

const onTabChange = (key) => {
  if (activeTab.value === key) return
  activeTab.value = key
  loadPool()
}

const onClaim = (o) => {
  // 后端 claim 接口路径参数是 order_id（非 order_no），
  // 对应 MallOrderListItemVO.orderId（schema 已加 serialization_alias）。
  const orderId = o.orderId || o.order_id
  uni.showModal({
    title: '确认抢单',
    content: `确定接 ${o.customer_nick || '客户'} 的订单 ${o.orderNo || o.order_no}？`,
    success: async (res) => {
      if (!res.confirm) return
      try {
        await http.request({
          url: `/api/mall/salesman/orders/${orderId}/claim`,
          method: 'POST',
          data: {}
        })
        uni.showToast({ title: '已接单', icon: 'success' })
        loadPool()
        loadBadges()
      } catch (e) {
        uni.showToast({ title: e?.msg || '抢单失败', icon: 'none' })
      }
    }
  })
}

// 工具函数（来自 src/utils/salesman.js，由 AutoImport 导出）
const fmtMoney = salesman.fmtMoney
const relativeTime = salesman.relativeTime

onMounted(() => {
  loadPool()
  loadBadges()
  countdownTimer = setInterval(refreshCountdowns, 1000)
})

onUnmounted(() => {
  if (countdownTimer) clearInterval(countdownTimer)
})

onShow(() => {
  loadBadges()
})

onPullDownRefresh(async () => {
  await Promise.all([loadPool(), loadBadges()])
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

.header {
  padding: 40rpx 32rpx 24rpx;
  background: $color-ink;
  color: #fff;

  &__title {
    font-size: 44rpx;
    font-weight: 600;
    letter-spacing: 2rpx;
  }
  &__subtitle {
    margin-top: 8rpx;
    font-size: 24rpx;
    color: $color-gold-soft;
    opacity: 0.85;
  }
}

.tabs {
  display: flex;
  background: $color-ink;
  padding: 0 32rpx 24rpx;
  gap: 48rpx;

  &__item {
    position: relative;
    padding: 16rpx 0;
    color: rgba(255,255,255,0.55);
    font-size: 28rpx;
    font-weight: 500;

    &--active {
      color: $color-gold;
      &::after {
        content: '';
        position: absolute;
        left: 0;
        right: 0;
        bottom: 0;
        height: 4rpx;
        background: $color-gold;
        border-radius: 2rpx;
      }
    }
  }

  &__badge {
    display: inline-block;
    margin-left: 12rpx;
    min-width: 32rpx;
    padding: 0 8rpx;
    height: 32rpx;
    line-height: 32rpx;
    text-align: center;
    background: $color-err;
    color: #fff;
    font-size: 20rpx;
    border-radius: 16rpx;
  }
}

.state {
  text-align: center;
  color: $color-hint;
  padding: 80rpx 0;
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
    font-size: 24rpx;
    color: $color-hint;
  }
  &__order {
    font-family: Menlo, Consolas, monospace;
    color: $color-muted;
  }
  &__time { font-size: 22rpx; }

  &__customer {
    margin-top: 16rpx;
    display: flex;
    align-items: baseline;
    gap: 16rpx;
  }
  &__nick {
    font-size: 32rpx;
    font-weight: 600;
    color: $color-ink-soft;
  }
  &__phone {
    font-size: 24rpx;
    color: $color-muted;
  }

  &__addr {
    margin-top: 12rpx;
    display: flex;
    align-items: center;
    gap: 8rpx;
    font-size: 24rpx;
    color: $color-muted;
  }
  &__icon { width: 24rpx; height: 24rpx; }

  &__items {
    margin-top: 16rpx;
    padding: 16rpx 20rpx;
    background: $color-cream;
    border-radius: 8rpx;
    font-size: 24rpx;
    color: $color-ink-soft;
    line-height: 1.5;
  }

  &__bottom {
    margin-top: 20rpx;
    display: flex;
    justify-content: space-between;
    align-items: center;
  }
  &__amount {
    font-size: 36rpx;
    font-weight: 700;
    color: $color-gold-deep;
  }
  &__actions {
    display: flex;
    align-items: center;
    gap: 20rpx;
  }
  &__timer {
    font-size: 22rpx;
    color: $color-err;
    font-family: Menlo, Consolas, monospace;
  }
  &__claim {
    padding: 14rpx 36rpx;
    background: $color-ink;
    color: $color-gold;
    font-size: 28rpx;
    font-weight: 600;
    border-radius: 40rpx;
    letter-spacing: 2rpx;
  }
}
</style>
