<!--
  门店收银

  流程：
    1. 搜索/选择客户（必填）
    2. 扫码（手机扫码 or 蓝牙扫码枪回车）
    3. 每瓶扫完弹框输入售价（必须在区间内）
    4. 选付款方式 → 提交
    5. 成功展示销售单号 + 提成
-->
<template>
  <view class="page">
    <!-- 客户选择 -->
    <view class="section">
      <view class="section__title customer-header">
        <text>客户</text>
        <view class="mode-toggle">
          <view
            :class="['mode-chip', customerMode === 'member' && 'mode-chip--active']"
            @tap="switchMode('member')"
          >
            会员
          </view>
          <view
            :class="['mode-chip', customerMode === 'walkin' && 'mode-chip--active']"
            @tap="switchMode('walkin')"
          >
            散客
          </view>
        </view>
      </view>

      <!-- 会员模式 -->
      <block v-if="customerMode === 'member'">
        <view v-if="selectedCustomer" class="customer-card">
          <view>
            <text class="customer-card__name">{{ selectedCustomer.name }}</text>
            <text class="customer-card__phone">{{ selectedCustomer.phone || '—' }}</text>
          </view>
          <text class="btn-text" @tap="selectedCustomer = null">重选</text>
        </view>
        <view v-else>
          <input
            v-model="customerKeyword"
            class="search-input"
            placeholder="输入客户手机号/姓名搜索"
            @confirm="searchCustomer"
          />
          <view v-if="customerResults.length" class="customer-list">
            <view
              v-for="c in customerResults"
              :key="c.id"
              class="customer-item"
              @tap="pickCustomer(c)"
            >
              <text>{{ c.name }}</text>
              <text class="customer-item__phone">{{ c.phone || '' }}</text>
            </view>
          </view>
        </view>
      </block>

      <!-- 散客模式 -->
      <block v-else>
        <view class="walkin-hint">
          未注册客户，可选填姓名/手机号用于回访，留空也可下单。
        </view>
        <input
          v-model="walkInName"
          class="search-input"
          placeholder="姓名（选填）"
          maxlength="30"
        />
        <input
          v-model="walkInPhone"
          class="search-input search-input--mt"
          placeholder="手机号（选填）"
          type="number"
          maxlength="11"
        />
      </block>
    </view>

    <!-- 扫码区 -->
    <view class="section">
      <view class="section__title">
        扫码（已扫 {{ items.length }} 瓶）
      </view>
      <view class="scan-row">
        <input
          ref="scanInput"
          v-model="scanInput"
          class="search-input"
          placeholder="扫码枪扫描 / 手输入条码后回车"
          :disabled="customerMode === 'member' && !selectedCustomer"
          @confirm="onScan"
        />
        <!-- #ifdef MP-WEIXIN || APP-PLUS -->
        <view class="btn" @tap="onNativeScan">
          📷 相机扫码
        </view>
        <!-- #endif -->
      </view>

      <view v-if="items.length" class="item-list">
        <view
          v-for="(it, idx) in items"
          :key="it.barcode"
          class="item-row"
        >
          <view class="item-row__main">
            <text class="item-row__name">{{ it.product_name }}</text>
            <text class="item-row__bar">{{ it.barcode }}</text>
            <text class="item-row__range">
              区间 ¥{{ it.min_sale_price }}–¥{{ it.max_sale_price }}
            </text>
          </view>
          <view class="item-row__price">
            <input
              v-model.number="it.sale_price"
              type="digit"
              class="price-input"
              :placeholder="it.min_sale_price"
            />
          </view>
          <text class="btn-text btn-text--danger" @tap="removeItem(idx)">删</text>
        </view>
      </view>
    </view>

    <!-- 付款方式 -->
    <view class="section">
      <view class="section__title">付款方式</view>
      <view class="method-row">
        <view
          v-for="m in methods"
          :key="m.value"
          :class="['method-chip', payment === m.value && 'method-chip--active']"
          @tap="payment = m.value"
        >
          {{ m.label }}
        </view>
      </view>
    </view>

    <!-- 合计 + 提交 -->
    <view class="summary">
      <view>
        <text>合计：</text>
        <text class="summary__amount">¥{{ totalSaleAmount }}</text>
      </view>
      <view
        :class="['submit-btn', canSubmit && 'submit-btn--active']"
        @tap="submit"
      >
        提交收银
      </view>
    </view>
  </view>
</template>

<script setup>
const customerKeyword = ref('')
const customerResults = ref([])
const selectedCustomer = ref(null)
// 决策 #3 散客支持：member | walkin
const customerMode = ref('member')
const walkInName = ref('')
const walkInPhone = ref('')
const scanInput = ref('')
const items = ref([])
const payment = ref('cash')
const submitting = ref(false)

const switchMode = (mode) => {
  customerMode.value = mode
  if (mode === 'member') {
    walkInName.value = ''
    walkInPhone.value = ''
  } else {
    selectedCustomer.value = null
    customerKeyword.value = ''
    customerResults.value = []
  }
}

const methods = [
  { value: 'cash', label: '现金' },
  { value: 'wechat', label: '微信' },
  { value: 'alipay', label: '支付宝' },
  { value: 'card', label: '刷卡' }
]

const totalSaleAmount = computed(() =>
  items.value.reduce((s, it) => s + (Number(it.sale_price) || 0), 0).toFixed(2)
)

const canSubmit = computed(() => {
  // 会员模式必须选客户；散客模式无需
  const customerOk = customerMode.value === 'walkin' || !!selectedCustomer.value
  return (
    customerOk &&
    items.value.length > 0 &&
    items.value.every(it => it.sale_price && Number(it.sale_price) > 0)
  )
})

const searchCustomer = async () => {
  if (!customerKeyword.value || customerKeyword.value.length < 2) return
  try {
    const res = await http.request({
      url: '/api/mall/workspace/store-sales/customers/search',
      method: 'GET',
      data: { keyword: customerKeyword.value }
    })
    customerResults.value = res.data?.records || []
    if (customerResults.value.length === 0) {
      uni.showToast({ title: '未找到客户', icon: 'none' })
    }
  } catch (e) {
    uni.showToast({ title: e?.detail || '搜索失败', icon: 'none' })
  }
}

const pickCustomer = (c) => {
  selectedCustomer.value = c
  customerResults.value = []
  customerKeyword.value = ''
}

const onScan = async () => {
  const code = (scanInput.value || '').trim()
  scanInput.value = ''
  if (!code) return
  if (items.value.find(it => it.barcode === code)) {
    uni.showToast({ title: '该条码已扫过', icon: 'none' })
    return
  }
  try {
    const res = await http.request({
      url: '/api/mall/workspace/store-sales/verify-barcode',
      method: 'GET',
      data: { barcode: code }
    })
    const r = res.data
    if (!r.ok) {
      uni.showToast({ title: r.message || '条码校验失败', icon: 'none' })
      return
    }
    items.value.push({
      barcode: code,
      product_id: r.product_id,
      product_name: r.product_name,
      spec: r.spec,
      min_sale_price: r.min_sale_price,
      max_sale_price: r.max_sale_price,
      sale_price: ''
    })
  } catch (e) {
    uni.showToast({ title: e?.detail || '扫码失败', icon: 'none' })
  }
}

const onNativeScan = () => {
  uni.scanCode({
    success: (res) => {
      scanInput.value = res.result
      onScan()
    }
  })
}

const removeItem = (idx) => {
  items.value.splice(idx, 1)
}

const submit = async () => {
  if (!canSubmit.value || submitting.value) return

  // 前端先校验售价区间
  for (const it of items.value) {
    const sp = Number(it.sale_price)
    if (sp < Number(it.min_sale_price) || sp > Number(it.max_sale_price)) {
      uni.showModal({
        title: '售价越界',
        content: `${it.product_name} 的售价 ¥${sp} 超出区间 ¥${it.min_sale_price}–¥${it.max_sale_price}`,
        showCancel: false
      })
      return
    }
  }

  submitting.value = true
  try {
    const payload = {
      line_items: items.value.map(it => ({
        barcode: it.barcode,
        sale_price: Number(it.sale_price)
      })),
      payment_method: payment.value
    }
    if (customerMode.value === 'member') {
      payload.customer_id = selectedCustomer.value.id
    } else {
      if (walkInName.value) payload.customer_walk_in_name = walkInName.value.trim()
      if (walkInPhone.value) payload.customer_walk_in_phone = walkInPhone.value.trim()
    }
    const res = await http.request({
      url: '/api/mall/workspace/store-sales',
      method: 'POST',
      data: payload
    })
    const r = res.data
    uni.showModal({
      title: '收银成功',
      content:
        `单号：${r.sale_no}\n` +
        `合计：¥${r.total_sale_amount}\n` +
        `利润：¥${r.total_profit}\n` +
        `你的提成：¥${r.total_commission}\n` +
        `${r.total_bottles} 瓶 / ${r.payment_method}`,
      showCancel: false,
      success: () => {
        selectedCustomer.value = null
        walkInName.value = ''
        walkInPhone.value = ''
        customerMode.value = 'member'
        items.value = []
        payment.value = 'cash'
      }
    })
  } catch (e) {
    uni.showToast({ title: e?.detail || '提交失败', icon: 'none' })
  } finally {
    submitting.value = false
  }
}
</script>

<style lang="scss" scoped>
.page {
  background: #faf8f5;
  min-height: 100vh;
  padding-bottom: 160rpx;
}
.section {
  background: #fff;
  padding: 24rpx 32rpx;
  margin-bottom: 16rpx;
}
.section__title {
  font-size: 28rpx;
  color: #0e0e0e;
  font-weight: 600;
  margin-bottom: 16rpx;
}
.customer-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
}
.mode-toggle { display: flex; gap: 8rpx; }
.mode-chip {
  padding: 8rpx 24rpx;
  background: #f5f5f5;
  border-radius: 24rpx;
  font-size: 24rpx;
  color: #8c8c8c;
  font-weight: 400;
}
.mode-chip--active {
  background: #0e0e0e;
  color: #c9a961;
  font-weight: 600;
}
.walkin-hint {
  font-size: 24rpx;
  color: #8c8c8c;
  padding: 12rpx 0 16rpx;
}
.search-input--mt { margin-top: 12rpx; }
.customer-card {
  display: flex;
  justify-content: space-between;
  align-items: center;
  padding: 24rpx;
  background: #fffbe6;
  border-radius: 12rpx;
}
.customer-card__name { font-weight: 600; font-size: 30rpx; margin-right: 16rpx; }
.customer-card__phone { color: #8c8c8c; font-size: 26rpx; }
.search-input {
  background: #f5f5f5;
  border-radius: 8rpx;
  padding: 20rpx 24rpx;
  font-size: 28rpx;
  width: 100%;
  box-sizing: border-box;
}
.customer-list {
  margin-top: 12rpx;
  background: #fff;
  border-radius: 8rpx;
}
.customer-item {
  display: flex;
  justify-content: space-between;
  padding: 20rpx 16rpx;
  border-top: 1rpx solid #ece8e1;
  font-size: 28rpx;
}
.customer-item__phone { color: #8c8c8c; }
.scan-row {
  display: flex;
  gap: 16rpx;
  align-items: center;
}
.btn {
  padding: 20rpx 24rpx;
  background: #c9a961;
  color: #fff;
  border-radius: 8rpx;
  font-size: 26rpx;
  white-space: nowrap;
}
.btn-text { color: #c9a961; font-size: 26rpx; padding: 8rpx 16rpx; }
.btn-text--danger { color: #ff4d4f; }
.item-list { margin-top: 16rpx; }
.item-row {
  display: flex;
  align-items: center;
  padding: 20rpx 0;
  border-top: 1rpx solid #ece8e1;
  gap: 12rpx;
}
.item-row__main { flex: 1; display: flex; flex-direction: column; }
.item-row__name { font-size: 28rpx; font-weight: 600; }
.item-row__bar { font-size: 22rpx; color: #8c8c8c; margin-top: 4rpx; }
.item-row__range { font-size: 22rpx; color: #c9a961; margin-top: 4rpx; }
.item-row__price { width: 180rpx; }
.price-input {
  border: 2rpx solid #c9a961;
  border-radius: 8rpx;
  padding: 12rpx 16rpx;
  font-size: 30rpx;
  text-align: right;
  width: 100%;
  box-sizing: border-box;
}
.method-row { display: flex; gap: 16rpx; flex-wrap: wrap; }
.method-chip {
  padding: 16rpx 32rpx;
  background: #f5f5f5;
  border-radius: 32rpx;
  font-size: 28rpx;
}
.method-chip--active {
  background: #0e0e0e;
  color: #c9a961;
}
.summary {
  position: fixed;
  bottom: 0;
  left: 0;
  right: 0;
  background: #fff;
  padding: 24rpx 32rpx;
  display: flex;
  justify-content: space-between;
  align-items: center;
  box-shadow: 0 -2rpx 16rpx rgba(0,0,0,0.08);
}
.summary__amount {
  font-size: 40rpx;
  font-weight: 700;
  color: #0e0e0e;
  margin-left: 16rpx;
}
.submit-btn {
  background: #d9d9d9;
  color: #8c8c8c;
  padding: 20rpx 40rpx;
  border-radius: 8rpx;
  font-size: 30rpx;
  font-weight: 600;
}
.submit-btn--active {
  background: #0e0e0e;
  color: #c9a961;
}
</style>
