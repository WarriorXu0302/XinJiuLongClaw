<!--
  业务员扫码出库页（M4a A 方案）

  进入方式：订单详情页"标记已出库"按钮 → 本页
  流程：
    1. 展示订单应发 SKU × 数量（从 /salesman/orders/{id} 拉取 items）
    2. 点"扫一瓶" → uni.scanCode → 即时调 /verify-barcode
       - 合法且未扫过 → 加入已扫列表
       - 非法 / 重复 / 错 SKU → 弹错提示
    3. 凑够总瓶数后底部按钮 "确认出库" 亮起
    4. 提交 POST /ship {scanned_barcodes: [...]}
    5. 后端原子核销，成功返回 shipped；任一失败整笔回滚

  关键：后端 verify 是 soft check（不扣减），真正扣减在 /ship
-->
<template>
  <view class="page">
    <view class="header">
      <view class="header__title">
        扫码出库
      </view>
      <view class="header__sub">
        订单号：{{ orderNo }}
      </view>
    </view>

    <!-- 应发清单 -->
    <view class="section">
      <view class="section__title">
        应发商品（每瓶 1 码）
      </view>
      <view
        v-for="it in items"
        :key="it.sku_id"
        class="item"
      >
        <view class="item__name">
          {{ it.prod_name }} · {{ it.sku_name }}
        </view>
        <view class="item__count">
          <text :class="['item__done', scannedCountBySku[it.sku_id] === it.quantity ? 'item__done--ok' : '']">
            {{ scannedCountBySku[it.sku_id] || 0 }}
          </text>
          <text class="item__slash">/</text>
          <text class="item__total">{{ it.quantity }}</text>
        </view>
      </view>
    </view>

    <!-- 已扫条码 -->
    <view class="section">
      <view class="section__title">
        已扫条码（{{ scanned.length }} / {{ totalRequired }}）
      </view>
      <view
        v-if="scanned.length === 0"
        class="empty"
      >
        <text>还没扫，点下方按钮开始</text>
      </view>
      <view
        v-for="(s, idx) in scanned"
        :key="s.barcode"
        class="code"
      >
        <view class="code__main">
          <text class="code__barcode">{{ s.barcode }}</text>
          <text class="code__prod">{{ s.product_name }} · {{ s.sku_name }}</text>
        </view>
        <text
          class="code__del"
          @tap="onRemove(idx)"
        >
          删除
        </text>
      </view>
    </view>

    <!-- 底部操作 -->
    <view class="footer">
      <view
        class="footer__scan"
        @tap="onScan"
      >
        <text>📷 扫一瓶</text>
      </view>
      <view
        :class="['footer__submit', !canSubmit && 'footer__submit--disabled']"
        @tap="onSubmit"
      >
        <text>{{ canSubmit ? '确认出库' : `还差 ${totalRequired - scanned.length} 瓶` }}</text>
      </view>
    </view>
  </view>
</template>

<script setup>
const orderId = ref('')
const orderNo = ref('')
const items = ref([])  // [{sku_id, prod_name, sku_name, quantity}]
const scanned = ref([])  // [{barcode, sku_id, product_name, sku_name}]

const totalRequired = computed(() =>
  items.value.reduce((s, i) => s + i.quantity, 0)
)

const scannedCountBySku = computed(() => {
  const m = {}
  scanned.value.forEach((s) => {
    m[s.sku_id] = (m[s.sku_id] || 0) + 1
  })
  return m
})

const canSubmit = computed(() =>
  scanned.value.length === totalRequired.value && totalRequired.value > 0
)

onLoad((opts) => {
  orderId.value = opts.order_id
  orderNo.value = opts.order_no
  loadItems()
})

const loadItems = async () => {
  const res = await http.request({
    url: `/api/mall/salesman/orders/${orderId.value}`,
    method: 'GET'
  })
  const body = res.data ?? res
  items.value = (body.items || []).map(it => ({
    sku_id: it.skuId || it.sku_id,
    prod_name: it.prodName || it.prod_name,
    sku_name: it.skuName || it.sku_name,
    quantity: it.count || it.quantity
  }))
}

const onScan = () => {
  uni.scanCode({
    scanType: ['barCode', 'qrCode'],
    success: async (res) => {
      const code = res.result
      if (!code) return
      if (scanned.value.some(s => s.barcode === code)) {
        uni.showToast({ title: '该条码已扫过', icon: 'none' })
        return
      }
      try {
        const verifyRes = await http.request({
          url: `/api/mall/salesman/orders/${orderId.value}/verify-barcode`,
          method: 'GET',
          data: { barcode: code }
        })
        const body = verifyRes.data ?? verifyRes
        if (!body.ok) {
          uni.showToast({ title: body.message || '条码无效', icon: 'none' })
          return
        }
        // 校验数量：这个 SKU 已扫数量 < 应发数量 才允许
        const already = scanned.value.filter(s => s.sku_id === body.sku_id).length
        const item = items.value.find(i => i.sku_id === body.sku_id)
        if (!item || already >= item.quantity) {
          uni.showToast({ title: `${body.product_name} 已扫够`, icon: 'none' })
          return
        }
        scanned.value.push({
          barcode: code,
          sku_id: body.sku_id,
          product_name: body.product_name,
          sku_name: body.sku_name
        })
        uni.showToast({ title: `✓ ${body.product_name}`, icon: 'none', duration: 800 })
      } catch (e) {
        uni.showToast({ title: e?.detail || '校验失败', icon: 'none' })
      }
    },
    fail: (e) => {
      if (!e.errMsg?.includes('cancel')) {
        uni.showToast({ title: '扫码失败', icon: 'none' })
      }
    }
  })
}

const onRemove = (idx) => {
  scanned.value.splice(idx, 1)
}

const onSubmit = async () => {
  if (!canSubmit.value) return
  uni.showModal({
    title: '确认出库',
    content: `将出库 ${totalRequired.value} 瓶，确认？`,
    success: async (r) => {
      if (!r.confirm) return
      try {
        uni.showLoading({ title: '出库中...' })
        await http.request({
          url: `/api/mall/salesman/orders/${orderId.value}/ship`,
          method: 'POST',
          data: { scanned_barcodes: scanned.value.map(s => s.barcode) }
        })
        uni.hideLoading()
        uni.showToast({ title: '出库成功', icon: 'success' })
        setTimeout(() => uni.navigateBack(), 1000)
      } catch (e) {
        uni.hideLoading()
        uni.showModal({
          title: '出库失败',
          content: e?.detail || '服务异常，请重试',
          showCancel: false
        })
      }
    }
  })
}
</script>

<style lang="scss" scoped>
@import '@/styles/variables.scss';

.page {
  min-height: 100vh;
  background: $color-cream;
  padding-bottom: calc(180rpx + env(safe-area-inset-bottom));
}
.header {
  padding: 40rpx 30rpx 20rpx;
  background: #0E0E0E;
  color: #FAF8F5;
}
.header__title {
  font-size: 44rpx;
  font-weight: 600;
  letter-spacing: 2rpx;
}
.header__sub {
  font-size: 24rpx;
  color: #C9A961;
  margin-top: 8rpx;
  letter-spacing: 1rpx;
}
.section {
  margin: 20rpx 20rpx 0;
  padding: 24rpx 20rpx;
  background: #fff;
  border-radius: 12rpx;
}
.section__title {
  font-size: 28rpx;
  color: #0E0E0E;
  font-weight: 600;
  margin-bottom: 16rpx;
}
.item {
  display: flex;
  justify-content: space-between;
  padding: 12rpx 0;
  border-bottom: 1rpx solid #ECE8E1;
  &:last-child { border-bottom: none; }
}
.item__name {
  flex: 1;
  font-size: 26rpx;
  color: #333;
}
.item__count {
  font-size: 28rpx;
}
.item__done {
  color: #C9A961;
  font-weight: 600;
}
.item__done--ok { color: #3BA55D; }
.item__slash {
  color: #999;
  margin: 0 4rpx;
}
.item__total {
  color: #666;
}
.empty {
  padding: 30rpx 0;
  text-align: center;
  color: #999;
  font-size: 24rpx;
}
.code {
  display: flex;
  align-items: center;
  padding: 16rpx 0;
  border-bottom: 1rpx solid #ECE8E1;
  &:last-child { border-bottom: none; }
}
.code__main {
  flex: 1;
  display: flex;
  flex-direction: column;
}
.code__barcode {
  font-family: monospace;
  font-size: 24rpx;
  color: #0E0E0E;
  letter-spacing: 1rpx;
}
.code__prod {
  font-size: 22rpx;
  color: #9A9A9A;
  margin-top: 4rpx;
}
.code__del {
  color: #C74D46;
  font-size: 24rpx;
  padding: 6rpx 16rpx;
}
.footer {
  position: fixed;
  left: 0;
  right: 0;
  bottom: 0;
  display: flex;
  padding: 20rpx 20rpx calc(20rpx + env(safe-area-inset-bottom));
  background: #fff;
  border-top: 1rpx solid #ECE8E1;
  gap: 16rpx;
}
.footer__scan {
  flex: 1;
  height: 88rpx;
  border: 2rpx solid #C9A961;
  border-radius: 44rpx;
  display: flex;
  align-items: center;
  justify-content: center;
  color: #C9A961;
  font-size: 30rpx;
  font-weight: 600;
}
.footer__submit {
  flex: 1.5;
  height: 88rpx;
  background: #C9A961;
  border-radius: 44rpx;
  display: flex;
  align-items: center;
  justify-content: center;
  color: #0E0E0E;
  font-size: 30rpx;
  font-weight: 600;
}
.footer__submit--disabled {
  background: #E5E0D7;
  color: #9A9A9A;
}
</style>
