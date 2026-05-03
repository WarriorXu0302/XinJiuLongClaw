<!--
  C 端 - 消息通知

  读 /api/mall/workspace/notifications（端点通用，按 mall_user_id 过滤）。
  点通知后跳转：订单/退货相关 → 订单详情；注册审批 → 账号页；其他跳个人中心。
-->
<template>
  <view class="page">
    <view class="header">
      <view class="header__title">
        消息通知
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
          {{ formatTime(n.created_at) }}
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

const entityTypeMap = {
  MallOrder: '商城订单',
  MallReturnRequest: '退货申请',
  MallPayment: '收款凭证',
  MallUser: '账号'
}

const hasUnread = computed(() => notifications.value.some(n => n.status === 'unread'))

const formatTime = (iso) => {
  if (!iso) return ''
  const d = new Date(iso)
  if (isNaN(d.getTime())) return iso
  const pad = (n) => String(n).padStart(2, '0')
  return `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())} ${pad(d.getHours())}:${pad(d.getMinutes())}`
}

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

// C 端跳转：订单/退货/凭证都能用 order_no 或 order_id；简化处理
const jumpByEntity = (n) => {
  const type = n.related_entity_type
  const id = n.related_entity_id
  if (!type || !id) return
  if (type === 'MallOrder') {
    // C 端订单详情用 orderNum（即 order_no），但通知里的 id 是 UUID；
    // 先跳订单列表兜底，用户从列表进详情
    uni.switchTab({
      url: '/pages/user/user',
      fail: () => uni.navigateTo({ url: '/pages/orderList/orderList' })
    })
    setTimeout(() => uni.navigateTo({ url: '/pages/orderList/orderList' }), 100)
  } else if (type === 'MallReturnRequest' || type === 'MallPayment') {
    uni.navigateTo({ url: '/pages/orderList/orderList' })
  } else if (type === 'MallUser') {
    uni.switchTab({ url: '/pages/user/user' })
  }
}

const onRead = async (n) => {
  const notifId = n.id
  if (n.status === 'unread') {
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
  try {
    await http.request({
      url: '/api/mall/workspace/notifications/mark-all-read',
      method: 'POST',
      data: {}
    })
    notifications.value.forEach(n => {
      n.status = 'read'
    })
    uni.showToast({ title: '已全部标记已读', icon: 'success' })
  } catch (e) {
    uni.showToast({ title: '操作失败', icon: 'none' })
  }
}

onShow(() => {
  uni.setNavigationBarTitle({ title: '消息通知' })
  load()
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
  display: flex;
  justify-content: space-between;
  align-items: center;
  padding: 32rpx;
  background: $color-ink;
  color: #fff;

  &__title {
    font-size: 36rpx;
    font-weight: 600;
    color: $color-gold;
  }

  &__action {
    font-size: 24rpx;
    color: $color-gold;
  }
}

.state {
  padding: 100rpx 0;
  text-align: center;
  color: $color-hint;
  font-size: 26rpx;
}

.card {
  margin: 24rpx;
  padding: 24rpx;
  background: #fff;
  border-radius: 16rpx;

  &--unread {
    border-left: 8rpx solid $color-gold;
  }

  &__top {
    display: flex;
    justify-content: space-between;
    align-items: center;
    margin-bottom: 12rpx;
  }

  &__title-row {
    display: flex;
    align-items: center;
    gap: 10rpx;
    flex: 1;
  }

  &__dot {
    width: 12rpx;
    height: 12rpx;
    border-radius: 50%;
    background: $color-err;
  }

  &__title {
    font-size: 30rpx;
    font-weight: 600;
    color: $color-ink-soft;
  }

  &__time {
    font-size: 22rpx;
    color: $color-hint;
  }

  &__content {
    font-size: 26rpx;
    color: #555;
    line-height: 1.5;
    margin-bottom: 8rpx;
    word-break: break-all;
  }

  &__tag {
    display: inline-block;
    margin-top: 8rpx;
    padding: 4rpx 14rpx;
    background: $color-cream;
    border-radius: 20rpx;
    font-size: 20rpx;
    color: $color-hint;
  }
}
</style>
