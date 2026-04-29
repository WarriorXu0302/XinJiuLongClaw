<!--
  业务员视角订单详情

  功能：
    - 状态时间线
    - 客户完整信息（+ 一键拨号 / 一键导航）
    - 商品清单
    - 金额明细
    - 动态操作按钮（按状态显示 ship / deliver / upload-voucher / release）

  接口：
    - GET /api/mall/salesman/orders/{order_no}
    - POST /api/mall/salesman/orders/{order_no}/ship
    - POST /api/mall/salesman/orders/{order_no}/deliver
    - POST /api/mall/salesman/orders/{order_no}/upload-payment-voucher
    - POST /api/mall/salesman/orders/{order_no}/release
-->
<template>
  <view class="page">
    <view
      v-if="loading"
      class="state"
    >
      加载中…
    </view>

    <block v-else-if="order">
      <!-- 状态条 -->
      <view class="status-bar">
        <text class="status-bar__label">
          {{ statusLabel(order.status) }}
        </text>
        <text class="status-bar__hint">
          {{ nextStepHint }}
        </text>
      </view>

      <!-- 时间线 -->
      <view class="timeline">
        <view
          v-for="(it, idx) in timeline"
          :key="idx"
          class="timeline__item"
        >
          <view :class="['timeline__dot', it.done && 'timeline__dot--done']" />
          <view class="timeline__body">
            <text class="timeline__label">
              {{ it.label }}
            </text>
            <text
              v-if="it.time"
              class="timeline__time"
            >
              {{ it.time }}
            </text>
          </view>
        </view>
      </view>

      <!-- 客户信息 -->
      <view class="section">
        <view class="section__title">
          收货信息
        </view>
        <view class="section__row">
          <text class="section__key">
            收件人
          </text>
          <text class="section__val">
            {{ order.address.receiver }}
          </text>
          <text
            class="section__action"
            @tap="onCall"
          >
            拨打电话
          </text>
        </view>
        <view class="section__row">
          <text class="section__key">
            电话
          </text>
          <text class="section__val">
            {{ order.customer_phone }}
          </text>
        </view>
        <view class="section__row section__row--addr">
          <text class="section__key">
            地址
          </text>
          <text class="section__val section__val--addr">
            {{ fullAddress }}
          </text>
          <text
            class="section__action"
            @tap="onNavigate"
          >
            导航
          </text>
        </view>
        <view
          v-if="order.remarks"
          class="section__row section__row--remark"
        >
          <text class="section__key">
            备注
          </text>
          <text class="section__val">
            {{ order.remarks }}
          </text>
        </view>
      </view>

      <!-- 商品 -->
      <view class="section">
        <view class="section__title">
          商品清单
        </view>
        <view
          v-for="(it, idx) in order.items"
          :key="idx"
          class="item"
        >
          <view class="item__main">
            <text class="item__name">
              {{ it.prod_name }}
            </text>
            <text class="item__spec">
              {{ it.sku_spec }}
            </text>
          </view>
          <view class="item__price">
            <text class="item__unit">
              {{ fmtMoney(it.price) }}
            </text>
            <text class="item__qty">
              × {{ it.quantity }}
            </text>
          </view>
        </view>
      </view>

      <!-- 金额 -->
      <view class="section">
        <view class="section__title">
          金额明细
        </view>
        <view class="section__row">
          <text class="section__key">
            商品合计
          </text>
          <text class="section__val">
            {{ fmtMoney(order.total_amount) }}
          </text>
        </view>
        <view class="section__row">
          <text class="section__key">
            运费
          </text>
          <text class="section__val">
            {{ fmtMoney(order.shipping_fee) }}
          </text>
        </view>
        <view
          v-if="order.discount_amount"
          class="section__row"
        >
          <text class="section__key">
            优惠
          </text>
          <text class="section__val">
            -{{ fmtMoney(order.discount_amount) }}
          </text>
        </view>
        <view class="section__row section__row--total">
          <text class="section__key">
            应收
          </text>
          <text class="section__val section__val--total">
            {{ fmtMoney(order.pay_amount) }}
          </text>
        </view>
      </view>

      <!-- 操作按钮 -->
      <view class="actions">
        <view
          v-if="['assigned', 'shipped'].includes(order.status)"
          class="actions__secondary"
          @tap="onRelease"
        >
          <text>释放订单</text>
        </view>
        <view
          v-if="order.status === 'assigned'"
          class="actions__primary"
          @tap="onShip"
        >
          <text>标记已出库</text>
        </view>
        <view
          v-if="order.status === 'shipped'"
          class="actions__primary"
          @tap="onDeliver"
        >
          <text>标记已送达</text>
        </view>
        <view
          v-if="order.status === 'delivered'"
          class="actions__primary"
          @tap="onUploadVoucher"
        >
          <text>上传收款凭证</text>
        </view>
      </view>
    </block>
  </view>
</template>

<script setup>
const order = ref(null)
const loading = ref(false)
const orderNo = ref('')

const statusLabel = (s) => salesman.ORDER_STATUS_LABEL[s] || s
const fmtMoney = salesman.fmtMoney

const fullAddress = computed(() => {
  if (!order.value) return ''
  const a = order.value.address
  return `${a.province}${a.city}${a.area} ${a.addr}`
})

const nextStepHint = computed(() => {
  if (!order.value) return ''
  const s = order.value.status
  if (s === 'assigned') return '备货出库，完成后点「标记已出库」'
  if (s === 'shipped') return '配送中，送达后拍照点「标记已送达」'
  if (s === 'delivered') return '收到客户货款后上传凭证'
  if (s === 'pending_payment_confirmation') return '等待财务确认收款'
  if (s === 'completed') return '订单已完成，提成已计入本月待发放'
  if (s === 'partial_closed') return '订单已折损，按实收金额结算'
  return ''
})

const timeline = computed(() => {
  if (!order.value) return []
  const o = order.value
  const done = (t) => !!t
  return [
    { label: '下单', time: o.created_at, done: done(o.created_at) },
    { label: '已接单', time: o.claimed_at, done: done(o.claimed_at) },
    { label: '已出库', time: o.shipped_at, done: done(o.shipped_at) },
    { label: '已送达', time: o.delivered_at, done: done(o.delivered_at) },
    { label: '财务确认', time: o.paid_at, done: done(o.paid_at) },
    { label: '已完成', time: o.completed_at, done: done(o.completed_at) }
  ]
})

const loadOrder = async () => {
  loading.value = true
  try {
    const res = await http.request({
      url: `/api/mall/salesman/orders/${orderNo.value}`,
      method: 'GET'
    })
    order.value = res.data
  } finally {
    loading.value = false
  }
}

const onCall = () => {
  uni.makePhoneCall({
    phoneNumber: order.value.customer_phone,
    fail: () => {}
  })
}

const onNavigate = () => {
  const a = order.value.address
  if (a.lat && a.lng) {
    uni.openLocation({
      latitude: a.lat,
      longitude: a.lng,
      name: a.receiver,
      address: fullAddress.value
    })
  } else {
    uni.showToast({ title: '地理坐标缺失', icon: 'none' })
  }
}

const onShip = () => {
  uni.showModal({
    title: '标记已出库',
    content: '确认商品已出库？出库后库存将扣减。',
    success: async (r) => {
      if (!r.confirm) return
      await http.request({
        url: `/api/mall/salesman/orders/${orderNo.value}/ship`,
        method: 'POST',
        data: {}
      })
      uni.showToast({ title: '已出库', icon: 'success' })
      loadOrder()
    }
  })
}

const onDeliver = () => {
  // 正式实现需要 uni.chooseImage 拍送达照 + 上传
  uni.chooseImage({
    count: 3,
    sizeType: ['compressed'],
    sourceType: ['camera', 'album'],
    success: async () => {
      await http.request({
        url: `/api/mall/salesman/orders/${orderNo.value}/deliver`,
        method: 'POST',
        data: { delivery_photos: ['mock-photo-url'] }
      })
      uni.showToast({ title: '已送达', icon: 'success' })
      loadOrder()
    }
  })
}

const onUploadVoucher = () => {
  uni.navigateTo({
    url: `/pages/salesman-upload-voucher/salesman-upload-voucher?order_no=${orderNo.value}`
  })
}

const onRelease = () => {
  uni.showModal({
    title: '确定释放订单？',
    content: '释放后订单将回到抢单池。如果该客户是你推荐的，将记录一次"跳单"，累计超过 3 次会触发告警。',
    confirmColor: '#B54B4B',
    success: async (r) => {
      if (!r.confirm) return
      await http.request({
        url: `/api/mall/salesman/orders/${orderNo.value}/release`,
        method: 'POST',
        data: { reason: '业务员主动释放' }
      })
      uni.showToast({ title: '已释放', icon: 'success' })
      setTimeout(() => uni.navigateBack(), 800)
    }
  })
}

onLoad((query) => {
  orderNo.value = query.order_no || ''
  if (orderNo.value) loadOrder()
})
</script>

<style lang="scss" scoped>
@import '@/styles/variables.scss';

.page {
  min-height: 100vh;
  background: $color-cream;
  padding-bottom: 180rpx;
}

.state {
  text-align: center;
  padding: 120rpx 0;
  color: $color-hint;
}

.status-bar {
  padding: 40rpx 32rpx;
  background: $color-ink;
  color: #fff;

  &__label {
    display: block;
    font-size: 40rpx;
    font-weight: 600;
    color: $color-gold;
  }
  &__hint {
    display: block;
    margin-top: 8rpx;
    font-size: 24rpx;
    color: $color-gold-soft;
    opacity: 0.85;
  }
}

.timeline {
  margin: 24rpx;
  padding: 28rpx 32rpx;
  background: $color-card;
  border-radius: 16rpx;

  &__item {
    display: flex;
    gap: 20rpx;
    padding: 10rpx 0;
  }
  &__dot {
    margin-top: 8rpx;
    width: 20rpx;
    height: 20rpx;
    border-radius: 50%;
    border: 3rpx solid $color-line;
    background: $color-card;
    &--done {
      background: $color-gold;
      border-color: $color-gold;
    }
  }
  &__body {
    flex: 1;
    display: flex;
    justify-content: space-between;
    align-items: center;
  }
  &__label {
    font-size: 26rpx;
    color: $color-ink-soft;
  }
  &__time {
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
    margin-bottom: 16rpx;
    padding-left: 12rpx;
    border-left: 6rpx solid $color-gold;
  }

  &__row {
    display: flex;
    align-items: center;
    gap: 16rpx;
    padding: 12rpx 0;
    font-size: 26rpx;

    &--addr { align-items: flex-start; }
    &--remark { color: $color-muted; }
    &--total {
      margin-top: 12rpx;
      padding-top: 16rpx;
      border-top: 1rpx dashed $color-line;
    }
  }

  &__key {
    min-width: 120rpx;
    color: $color-muted;
  }
  &__val {
    flex: 1;
    color: $color-ink-soft;
    &--addr { line-height: 1.5; }
    &--total {
      font-size: 34rpx;
      font-weight: 700;
      color: $color-gold-deep;
    }
  }
  &__action {
    padding: 6rpx 20rpx;
    background: $color-ink;
    color: $color-gold;
    font-size: 22rpx;
    border-radius: 30rpx;
  }
}

.item {
  display: flex;
  justify-content: space-between;
  align-items: center;
  padding: 16rpx 0;
  border-bottom: 1rpx solid $color-line-soft;

  &:last-child { border-bottom: none; }

  &__main { flex: 1; }
  &__name {
    display: block;
    font-size: 26rpx;
    color: $color-ink-soft;
  }
  &__spec {
    display: block;
    margin-top: 4rpx;
    font-size: 22rpx;
    color: $color-hint;
  }
  &__price {
    text-align: right;
  }
  &__unit {
    display: block;
    font-size: 26rpx;
    color: $color-ink-soft;
  }
  &__qty {
    display: block;
    margin-top: 4rpx;
    font-size: 22rpx;
    color: $color-muted;
  }
}

.actions {
  position: fixed;
  left: 0;
  right: 0;
  bottom: 0;
  display: flex;
  gap: 16rpx;
  padding: 20rpx 24rpx calc(20rpx + env(safe-area-inset-bottom));
  background: $color-card;
  box-shadow: 0 -4rpx 24rpx rgba(14,14,14,0.06);

  &__secondary {
    flex: 1;
    padding: 24rpx 0;
    text-align: center;
    background: $color-card;
    color: $color-err;
    border: 2rpx solid $color-err;
    border-radius: 12rpx;
    font-size: 28rpx;
    font-weight: 600;
  }
  &__primary {
    flex: 2;
    padding: 24rpx 0;
    text-align: center;
    background: $color-ink;
    color: $color-gold;
    border-radius: 12rpx;
    font-size: 30rpx;
    font-weight: 600;
    letter-spacing: 2rpx;
  }
}
</style>
