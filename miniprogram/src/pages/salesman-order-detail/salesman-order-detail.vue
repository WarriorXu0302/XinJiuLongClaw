<!--
  业务员视角订单详情

  功能：
    - 状态时间线
    - 客户完整信息（+ 一键拨号 / 一键导航）
    - 商品清单
    - 金额明细
    - 动态操作按钮（按状态显示 ship / deliver / upload-voucher / release）

  接口（后端路径参数全部是 order_id，不是 order_no）：
    - GET /api/mall/salesman/orders/{order_id}
    - POST /api/mall/salesman/orders/{order_id}/ship
    - POST /api/mall/salesman/orders/{order_id}/deliver
    - POST /api/mall/salesman/orders/{order_id}/upload-payment-voucher
    - POST /api/mall/salesman/orders/{order_id}/release
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
            {{ order.address && order.address.receiver }}
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
            {{ order.address && order.address.mobile }}
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
              {{ it.prodName || it.prod_name }}
            </text>
            <text class="item__spec">
              {{ it.skuName || it.sku_name }}
            </text>
          </view>
          <view class="item__price">
            <text class="item__unit">
              {{ fmtMoney(it.price) }}
            </text>
            <text class="item__qty">
              × {{ it.count || it.quantity }}
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
            {{ fmtMoney(order.totalAmount || order.total_amount) }}
          </text>
        </view>
        <view class="section__row">
          <text class="section__key">
            运费
          </text>
          <text class="section__val">
            {{ fmtMoney(order.shippingFee || order.shipping_fee) }}
          </text>
        </view>
        <view
          v-if="order.discountAmount || order.discount_amount"
          class="section__row"
        >
          <text class="section__key">
            优惠
          </text>
          <text class="section__val">
            -{{ fmtMoney(order.discountAmount || order.discount_amount) }}
          </text>
        </view>
        <view class="section__row section__row--total">
          <text class="section__key">
            应收
          </text>
          <text class="section__val section__val--total">
            {{ fmtMoney(order.payAmount || order.pay_amount) }}
          </text>
        </view>
      </view>

      <!-- 凭证列表（仅存在时展示；驳回条目高亮红底 + 原因） -->
      <view
        v-if="order.payments && order.payments.length"
        class="section"
      >
        <view class="section__title">
          收款凭证
        </view>
        <view
          v-for="p in order.payments"
          :key="p.id"
          :class="['voucher', `voucher--${p.status}`]"
        >
          <view class="voucher__head">
            <text class="voucher__amt">
              {{ fmtMoney(p.amount) }}
            </text>
            <text :class="['voucher__status', `voucher__status--${p.status}`]">
              {{ paymentStatusLabel(p.status) }}
            </text>
          </view>
          <view class="voucher__meta">
            <text>{{ paymentMethodLabel(p.paymentMethod || p.payment_method) }}</text>
            <text>·</text>
            <text>{{ fmtDate(p.createdAt || p.created_at) }}</text>
          </view>
          <view
            v-if="p.status === 'rejected' && (p.rejectedReason || p.rejected_reason)"
            class="voucher__reject"
          >
            <text class="voucher__reject-label">
              驳回原因：
            </text>
            <text>{{ p.rejectedReason || p.rejected_reason }}</text>
          </view>
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
          <text>{{ needReupload ? '重新上传收款凭证' : '上传收款凭证' }}</text>
        </view>
      </view>
    </block>
  </view>
</template>

<script setup>
const order = ref(null)
const loading = ref(false)
const orderNo = ref('')
const orderId = ref('')

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

// 订单 delivered 状态下若有 rejected 凭证 → 按钮文案改"重新上传"
const needReupload = computed(() => {
  if (!order.value) return false
  if (order.value.status !== 'delivered') return false
  const pays = order.value.payments || []
  return pays.some(p => p.status === 'rejected')
})

const paymentStatusLabel = (s) => ({
  pending_confirmation: '待财务确认',
  confirmed: '已确认',
  rejected: '已驳回'
}[s] || s)

const paymentMethodLabel = (m) => ({
  cash: '现金',
  bank: '银行转账',
  wechat: '微信',
  alipay: '支付宝'
}[m] || m || '-')

const fmtDate = (iso) => {
  if (!iso) return ''
  const d = new Date(iso)
  if (isNaN(d.getTime())) return iso
  const pad = (n) => String(n).padStart(2, '0')
  return `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())} ${pad(d.getHours())}:${pad(d.getMinutes())}`
}

const timeline = computed(() => {
  if (!order.value) return []
  const o = order.value
  // 兼容后端两种命名：驼峰 alias（createTime/shippedAt/...）+ snake_case 历史兜底
  const pick = (camel, snake) => o[camel] ?? o[snake]
  const done = (t) => !!t
  const createdAt = pick('createTime', 'created_at')
  const claimedAt = pick('claimedAt', 'claimed_at')
  const shippedAt = pick('shippedAt', 'shipped_at')
  const deliveredAt = pick('deliveredAt', 'delivered_at')
  const paidAt = pick('paidAt', 'paid_at')
  const completedAt = pick('completedAt', 'completed_at')
  return [
    { label: '下单', time: createdAt, done: done(createdAt) },
    { label: '已接单', time: claimedAt, done: done(claimedAt) },
    { label: '已出库', time: shippedAt, done: done(shippedAt) },
    { label: '已送达', time: deliveredAt, done: done(deliveredAt) },
    { label: '财务确认', time: paidAt, done: done(paidAt) },
    { label: '已完成', time: completedAt, done: done(completedAt) }
  ]
})

const loadOrder = async () => {
  loading.value = true
  try {
    const res = await http.request({
      url: `/api/mall/salesman/orders/${orderId.value}`,
      method: 'GET'
    })
    order.value = res.data
    // 后端 detail VO 暂不含 orderId，兜底从 response 里读 (后端返回的 detail 里没有 id)；
    // 若后续需要用到 id 做下游动作，仍用 orderId.value（从 query 来的那个）
  } finally {
    loading.value = false
  }
}

const onCall = () => {
  // 业务员抢单后可见完整手机号：优先 address.mobile（订单快照），兜底 customer_phone（旧字段）
  const phone = order.value?.address?.mobile || order.value?.customer_phone
  if (!phone) {
    uni.showToast({ title: '缺少客户手机号', icon: 'none' })
    return
  }
  uni.makePhoneCall({
    phoneNumber: phone,
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

const onShip = async () => {
  // 先问后端该走扫码还是散装：mall 仓采购入库不生成条码，强行扫码会卡死
  let mode = 'scan'
  let requiredBottles = 0
  try {
    const res = await http.request({
      url: `/api/mall/salesman/orders/${orderId.value}/ship-mode`,
      method: 'GET'
    })
    mode = res?.data?.mode || 'scan'
    requiredBottles = res?.data?.required_bottles || 0
  } catch (e) {
    uni.showToast({ title: '查询出库方式失败', icon: 'none' })
    return
  }

  if (mode === 'scan') {
    uni.navigateTo({
      url: `/pages/salesman-ship-scan/salesman-ship-scan?order_id=${orderId.value}&order_no=${orderNo.value}`
    })
    return
  }
  // bulk：弹确认 + 按数量直接 POST /ship
  uni.showModal({
    title: '按数量出库',
    content: `此订单在 mall 仓为散装库存，应发 ${requiredBottles} 瓶。确认按数量出库？（不扫码）`,
    confirmText: '确认出库',
    cancelText: '取消',
    success: async (r) => {
      if (!r.confirm) return
      uni.showLoading({ title: '出库中...' })
      try {
        await http.request({
          url: `/api/mall/salesman/orders/${orderId.value}/ship`,
          method: 'POST',
          data: { scanned_barcodes: [] }
        })
        uni.hideLoading()
        uni.showToast({ title: '已出库', icon: 'success' })
        loadOrder()
      } catch (err) {
        uni.hideLoading()
        uni.showToast({ title: err?.detail || '出库失败', icon: 'none' })
      }
    }
  })
}

const uploadDeliveryPhoto = (localPath) => {
  return new Promise((resolve, reject) => {
    const token = uni.getStorageSync('Token')
    uni.uploadFile({
      url: (import.meta.env.VITE_APP_BASE_API || '') + '/api/mall/salesman/attachments/upload',
      filePath: localPath,
      name: 'file',
      formData: { kind: 'delivery_photo' },
      header: token ? { Authorization: token.startsWith('Bearer ') ? token : `Bearer ${token}` } : {},
      success: (r) => {
        try {
          const body = typeof r.data === 'string' ? JSON.parse(r.data) : r.data
          if (r.statusCode >= 200 && r.statusCode < 300 && body.url && body.sha256) {
            resolve({ url: body.url, sha256: body.sha256, size: body.size, mime_type: body.mime_type })
          } else {
            reject(new Error(body.detail || body.msg || '上传失败'))
          }
        } catch (e) {
          reject(e)
        }
      },
      fail: (err) => reject(err)
    })
  })
}

const onDeliver = () => {
  uni.chooseImage({
    count: 3,
    sizeType: ['compressed'],
    sourceType: ['camera', 'album'],
    success: async (res) => {
      if (!res.tempFilePaths?.length) return
      uni.showLoading({ title: '上传中...' })
      try {
        const photos = await Promise.all(res.tempFilePaths.map(uploadDeliveryPhoto))
        uni.hideLoading()
        uni.showLoading({ title: '标记送达...' })
        await http.request({
          url: `/api/mall/salesman/orders/${orderId.value}/deliver`,
          method: 'POST',
          data: { delivery_photos: photos }
        })
        uni.hideLoading()
        uni.showToast({ title: '已送达', icon: 'success' })
        loadOrder()
      } catch (err) {
        uni.hideLoading()
        uni.showToast({ title: err?.message || err?.detail || '送达失败', icon: 'none' })
      }
    }
  })
}

const onUploadVoucher = () => {
  uni.navigateTo({
    url: `/pages/salesman-upload-voucher/salesman-upload-voucher?order_id=${orderId.value}&order_no=${orderNo.value}`
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
        url: `/api/mall/salesman/orders/${orderId.value}/release`,
        method: 'POST',
        data: { reason: '业务员主动释放' }
      })
      uni.showToast({ title: '已释放', icon: 'success' })
      setTimeout(() => uni.navigateBack(), 800)
    }
  })
}

onLoad((query) => {
  orderId.value = query.order_id || ''
  orderNo.value = query.order_no || ''
  // 兼容老跳转：若只传了 order_no 而没 order_id，记一条提示但后端会 404
  if (orderId.value) loadOrder()
  else if (orderNo.value) {
    uni.showToast({ title: '订单 ID 缺失，请从列表重新进入', icon: 'none' })
  }
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

.voucher {
  padding: 20rpx 0;
  border-bottom: 1rpx solid $color-line;

  &:last-child {
    border-bottom: none;
  }

  &__head {
    display: flex;
    justify-content: space-between;
    align-items: center;
    margin-bottom: 8rpx;
  }

  &__amt {
    font-size: 32rpx;
    font-weight: 600;
    color: $color-ink-soft;
  }

  &__status {
    font-size: 22rpx;
    padding: 4rpx 16rpx;
    border-radius: 20rpx;

    &--pending_confirmation {
      background: rgba(201, 169, 97, 0.15);
      color: $color-gold-deep;
    }
    &--confirmed {
      background: rgba(82, 196, 26, 0.15);
      color: #52c41a;
    }
    &--rejected {
      background: rgba(255, 77, 79, 0.15);
      color: $color-err;
    }
  }

  &__meta {
    display: flex;
    gap: 10rpx;
    font-size: 22rpx;
    color: $color-hint;
  }

  &__reject {
    margin-top: 12rpx;
    padding: 16rpx;
    background: rgba(255, 77, 79, 0.08);
    border-left: 4rpx solid $color-err;
    border-radius: 8rpx;
    font-size: 26rpx;
    color: $color-err;
    line-height: 1.5;
  }

  &__reject-label {
    font-weight: 600;
  }

  &--rejected {
    background: rgba(255, 77, 79, 0.02);
  }
}
</style>
