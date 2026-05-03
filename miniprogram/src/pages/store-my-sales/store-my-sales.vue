<!--
  门店店员"我的业绩"

  本月汇总卡片 + 最近销售流水（下拉加载）
-->
<template>
  <view class="page">
    <!-- 本月汇总 -->
    <view class="hero">
      <view class="hero__label">{{ summary.year }}年{{ summary.month }}月 · 我的业绩</view>
      <view class="hero__amount">¥{{ summary.total_sale_amount }}</view>
      <view class="hero__row">
        <view class="hero__cell">
          <text class="hero__cell-k">成交单数</text>
          <text class="hero__cell-v">{{ summary.sale_count }}</text>
        </view>
        <view class="hero__cell">
          <text class="hero__cell-k">瓶数</text>
          <text class="hero__cell-v">{{ summary.total_bottles }}</text>
        </view>
        <view class="hero__cell">
          <text class="hero__cell-k">利润</text>
          <text class="hero__cell-v hero__cell-v--green">¥{{ summary.total_profit }}</text>
        </view>
        <view class="hero__cell">
          <text class="hero__cell-k">我的提成</text>
          <text class="hero__cell-v hero__cell-v--gold">¥{{ summary.total_commission }}</text>
        </view>
      </view>
    </view>

    <!-- 销售流水 -->
    <view class="section">
      <view class="section__title">最近销售</view>
      <view v-if="!records.length && !loading" class="empty">暂无销售记录</view>
      <view
        v-for="r in records"
        :key="r.id"
        class="row"
      >
        <view class="row__left">
          <text class="row__no">{{ r.sale_no }}</text>
          <text class="row__meta">{{ r.customer_name || '—' }} · {{ r.total_bottles }} 瓶</text>
          <text class="row__time">{{ fmtTime(r.created_at) }}</text>
        </view>
        <view class="row__right">
          <text class="row__amount">¥{{ r.total_sale_amount }}</text>
          <text class="row__commission">提成 ¥{{ r.total_commission }}</text>
          <text class="row__return" @tap="applyReturn(r)">申请退货</text>
        </view>
      </view>
    </view>
  </view>
</template>

<script setup>
const summary = ref({
  year: new Date().getFullYear(),
  month: new Date().getMonth() + 1,
  total_sale_amount: '0',
  total_profit: '0',
  total_commission: '0',
  total_bottles: 0,
  sale_count: 0
})
const records = ref([])
const loading = ref(false)

const loadAll = async () => {
  loading.value = true
  try {
    const [s, l] = await Promise.all([
      http.request({ url: '/api/mall/workspace/store-sales/my/summary', method: 'GET' }),
      http.request({ url: '/api/mall/workspace/store-sales/my/sales', method: 'GET', data: { limit: 20 } })
    ])
    summary.value = s.data
    records.value = l.data?.records || []
  } catch (e) {
    uni.showToast({ title: e?.detail || '加载失败', icon: 'none' })
  } finally {
    loading.value = false
  }
}

const fmtTime = (t) => {
  if (!t) return '—'
  const d = new Date(t)
  return `${String(d.getMonth() + 1).padStart(2, '0')}-${String(d.getDate()).padStart(2, '0')} ${String(d.getHours()).padStart(2, '0')}:${String(d.getMinutes()).padStart(2, '0')}`
}

const applyReturn = (r) => {
  let reason = ''
  uni.showModal({
    title: '申请整单退货',
    content: `${r.sale_no}\n共 ${r.total_bottles} 瓶，应退 ¥${r.total_sale_amount}\n\n退货需管理员审批后生效（条码回池、库存回加、提成冲销）。确认发起？`,
    editable: true,
    placeholderText: '退货原因（可选）',
    success: async (res) => {
      if (!res.confirm) return
      reason = res.content || ''
      try {
        const resp = await http.request({
          url: '/api/mall/workspace/store-returns',
          method: 'POST',
          data: { original_sale_id: r.id, reason }
        })
        uni.showModal({
          title: '已提交退货申请',
          content: `退货单 ${resp.data.return_no}\n状态：待审批\n应退 ¥${resp.data.refund_amount}`,
          showCancel: false,
          success: () => loadAll()
        })
      } catch (e) {
        uni.showToast({ title: e?.detail || '申请失败', icon: 'none' })
      }
    }
  })
}

onLoad(() => { loadAll() })
onShow(() => { loadAll() })
</script>

<style lang="scss" scoped>
.page { background: #faf8f5; min-height: 100vh; }
.hero {
  background: linear-gradient(135deg, #0e0e0e 0%, #3a2c0f 100%);
  color: #faf8f5;
  padding: 48rpx 32rpx;
}
.hero__label { font-size: 26rpx; color: #c9a961; }
.hero__amount { font-size: 72rpx; font-weight: 700; margin: 16rpx 0 24rpx; }
.hero__row { display: flex; justify-content: space-between; gap: 16rpx; }
.hero__cell { flex: 1; display: flex; flex-direction: column; align-items: center; }
.hero__cell-k { font-size: 22rpx; color: #8c8c8c; }
.hero__cell-v { font-size: 32rpx; font-weight: 600; margin-top: 8rpx; color: #faf8f5; }
.hero__cell-v--green { color: #52c41a; }
.hero__cell-v--gold { color: #c9a961; }

.section { background: #fff; margin-top: 16rpx; padding: 24rpx 32rpx; }
.section__title { font-size: 28rpx; font-weight: 600; margin-bottom: 16rpx; }
.empty { color: #8c8c8c; font-size: 26rpx; padding: 32rpx 0; text-align: center; }
.row {
  display: flex; justify-content: space-between;
  padding: 24rpx 0;
  border-top: 1rpx solid #ece8e1;
}
.row__left { display: flex; flex-direction: column; }
.row__right { display: flex; flex-direction: column; align-items: flex-end; }
.row__no { font-size: 26rpx; color: #0e0e0e; }
.row__meta { font-size: 22rpx; color: #8c8c8c; margin-top: 4rpx; }
.row__time { font-size: 22rpx; color: #8c8c8c; margin-top: 4rpx; }
.row__amount { font-size: 30rpx; font-weight: 600; color: #0e0e0e; }
.row__commission { font-size: 22rpx; color: #c9a961; margin-top: 4rpx; }
.row__return {
  margin-top: 8rpx;
  font-size: 22rpx;
  color: #ff4d4f;
  padding: 4rpx 12rpx;
  border: 1rpx solid #ff4d4f;
  border-radius: 4rpx;
}
</style>
