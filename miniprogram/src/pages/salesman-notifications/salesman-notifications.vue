<!--
  业务员 - 通知中心（recipient_type='mall_user'）
-->
<template>
  <view class="page">
    <view class="header">
      <view class="header__title">
        通知中心
      </view>
      <view
        v-if="hasUnread"
        class="header__action"
        @tap="onMarkAllRead"
      >
        全部已读
      </view>
    </view>

    <view
      v-if="loading"
      class="state"
    >
      加载中…
    </view>
    <view
      v-else-if="notifications.length === 0"
      class="state"
    >
      暂无通知
    </view>

    <view
      v-for="n in notifications"
      :key="n.id"
      :class="['card', n.status === 'unread' && 'card--unread']"
      @tap="onRead(n)"
    >
      <view class="card__top">
        <view class="card__title-row">
          <text
            v-if="n.status === 'unread'"
            class="card__dot"
          />
          <text class="card__title">
            {{ n.title }}
          </text>
        </view>
        <text class="card__time">
          {{ relativeTime(n.created_at) }}
        </text>
      </view>
      <view class="card__content">
        {{ n.content }}
      </view>
      <view
        v-if="n.related_entity_type"
        class="card__tag"
      >
        <text>{{ entityTypeMap[n.related_entity_type] || n.related_entity_type }}</text>
      </view>
    </view>
  </view>
</template>

<script setup>
const notifications = ref([])
const loading = ref(false)

const relativeTime = salesman.relativeTime

const entityTypeMap = {
  SalesTarget: '销售目标',
  MallOrder: '商城订单',
  ExpenseClaim: '报销',
  MallSkipAlert: '跳单告警',
  SalaryRecord: '工资',
  LeaveRequest: '请假'
}

const hasUnread = computed(() => notifications.value.some(n => n.status === 'unread'))

const load = async () => {
  loading.value = true
  try {
    const res = await http.request({
      url: '/api/mall/workspace/notifications',
      method: 'GET'
    })
    notifications.value = res.data?.records || []
  } finally {
    loading.value = false
  }
}

const jumpByEntity = (n) => {
  const type = n.related_entity_type
  const id = n.related_entity_id
  if (!type || !id) return
  // 业务员侧三类通知实体：MallOrder / MallSkipAlert / MallPayment
  if (type === 'MallOrder') {
    // 业务员订单详情页用 order_id（UUID）跳转
    uni.navigateTo({
      url: `/pages/salesman-order-detail/salesman-order-detail?order_id=${id}`
    })
  } else if (type === 'MallSkipAlert') {
    uni.navigateTo({ url: '/pages/salesman-alerts/salesman-alerts' })
  } else if (type === 'MallPayment') {
    // 凭证在订单详情里；payment.order_id 不在通知里，跳通用订单列表兜底
    uni.switchTab
      ? uni.switchTab({ url: '/pages/salesman-orders/salesman-orders' })
      : uni.navigateTo({ url: '/pages/salesman-orders/salesman-orders' })
  }
}

const onRead = async (n) => {
  const notifId = n.id
  if (n.status === 'unread') {
    // 乐观更新：先改本地，后调接口；失败回滚
    n.status = 'read'
    try {
      await http.request({
        url: `/api/mall/workspace/notifications/${notifId}/mark-read`,
        method: 'POST',
        data: {}
      })
    } catch {
      // eslint-disable-next-line require-atomic-updates
      n.status = 'unread'
    }
  }
  jumpByEntity(n)
}

const onMarkAllRead = async () => {
  await http.request({
    url: '/api/mall/workspace/notifications/mark-all-read',
    method: 'POST',
    data: {}
  })
  notifications.value.forEach(n => {
    n.status = 'read'
  })
  uni.showToast({ title: '已全部标记为已读', icon: 'success' })
}

onMounted(() => load())
onShow(() => load())
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
  display: flex;
  justify-content: space-between;
  align-items: center;

  &__title {
    font-size: 40rpx;
    font-weight: 600;
    color: $color-gold;
  }
  &__action {
    padding: 8rpx 20rpx;
    border: 1rpx solid $color-gold;
    color: $color-gold;
    font-size: 22rpx;
    border-radius: 20rpx;
  }
}

.state {
  padding: 120rpx 0;
  text-align: center;
  color: $color-hint;
}

.card {
  margin: 24rpx 24rpx 0;
  padding: 24rpx 32rpx;
  background: $color-card;
  border-radius: 16rpx;
  border-left: 6rpx solid transparent;

  &--unread { border-left-color: $color-gold; }

  &__top {
    display: flex;
    justify-content: space-between;
    align-items: center;
  }
  &__title-row {
    display: flex;
    align-items: center;
    gap: 8rpx;
  }
  &__dot {
    width: 12rpx;
    height: 12rpx;
    border-radius: 50%;
    background: $color-err;
  }
  &__title {
    font-size: 28rpx;
    font-weight: 600;
    color: $color-ink-soft;
  }
  &__time {
    font-size: 22rpx;
    color: $color-hint;
  }
  &__content {
    margin-top: 12rpx;
    font-size: 26rpx;
    color: $color-muted;
    line-height: 1.6;
  }
  &__tag {
    margin-top: 12rpx;
    display: inline-block;
    padding: 4rpx 16rpx;
    background: $color-cream;
    border-radius: 12rpx;
    font-size: 22rpx;
    color: $color-gold-deep;
  }
}
</style>
