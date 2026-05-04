<!--
  业务员 - 我的提成流水（G6）

  展示：
    - 本月 pending / settled / reversed / 追回 四格汇总
    - 下方列表支持 Tab 切换：全部 / pending / settled / reversed / 追回
    - 每行显示原订单号、提成金额、状态、备注
    - 追回项 单独标红 + 展示原 commission 金额
-->
<template>
  <view class="page">
    <view class="header">
      <view class="header__title">
        我的提成流水
      </view>
      <view class="header__month-picker">
        <text @tap="prevMonth">
          ‹
        </text>
        <text class="header__month">
          {{ year }} 年 {{ month }} 月
        </text>
        <text @tap="nextMonth">
          ›
        </text>
      </view>
    </view>

    <!-- 汇总卡 -->
    <view class="summary">
      <view
        :class="['summary__card', filter === 'pending' && 'summary__card--active']"
        @tap="setFilter('pending')"
      >
        <text class="summary__label">
          待发放
        </text>
        <text class="summary__value summary__value--pending">
          ¥{{ stats.pending || '0' }}
        </text>
        <text class="summary__count">
          {{ pendingCount }} 笔
        </text>
      </view>
      <view
        :class="['summary__card', filter === 'settled' && 'summary__card--active']"
        @tap="setFilter('settled')"
      >
        <text class="summary__label">
          已发放
        </text>
        <text class="summary__value summary__value--settled">
          ¥{{ stats.settled || '0' }}
        </text>
        <text class="summary__count">
          {{ settledCount }} 笔
        </text>
      </view>
      <view
        :class="['summary__card', filter === 'reversed' && 'summary__card--active']"
        @tap="setFilter('reversed')"
      >
        <text class="summary__label">
          被冲销
        </text>
        <text class="summary__value summary__value--reversed">
          ¥{{ stats.reversed || '0' }}
        </text>
        <text class="summary__count">
          {{ reversedCount }} 笔
        </text>
      </view>
      <view
        :class="['summary__card', filter === 'adjustment' && 'summary__card--active']"
        @tap="setFilter('adjustment')"
      >
        <text class="summary__label">
          跨月追回
        </text>
        <text class="summary__value summary__value--adj">
          ¥{{ stats.adjustment || '0' }}
        </text>
        <text class="summary__count">
          {{ adjustmentCount }} 笔
        </text>
      </view>
    </view>

    <view class="tabs">
      <view
        v-for="t in tabs"
        :key="t.key"
        :class="['tab', filter === t.key && 'tab--active']"
        @tap="setFilter(t.key)"
      >
        {{ t.label }}
      </view>
    </view>

    <view
      v-if="list.length === 0"
      class="empty"
    >
      {{ loading ? '加载中…' : '本月没有对应数据' }}
    </view>
    <view
      v-else
      class="list"
    >
      <view
        v-for="it in list"
        :key="it.id"
        class="item"
      >
        <view class="item__row1">
          <text class="item__order-no">
            {{ it.order_no || '—' }}
          </text>
          <text :class="['item__amount', amountClass(it)]">
            {{ formatAmount(it.commission_amount) }}
          </text>
        </view>
        <view class="item__row2">
          <text class="item__meta">
            {{ refTypeLabel(it.ref_type) }} · {{ dateStr(it.created_at) }}
          </text>
          <view
            class="item__status"
            :style="statusStyle(it)"
          >
            {{ statusLabel(it) }}
          </view>
        </view>
        <view
          v-if="it.is_adjustment"
          class="item__adjustment"
        >
          <text class="item__adjustment-line">
            ⚠ 原 commission ¥{{ it.origin_commission_amount }}（{{ originStatusLabel(it.origin_status) }}）
          </text>
          <text class="item__adjustment-note">
            {{ it.notes || '跨月退货追回' }}
          </text>
        </view>
        <view
          v-else-if="it.notes"
          class="item__notes"
        >
          {{ it.notes }}
        </view>
      </view>
    </view>
  </view>
</template>

<script setup>
const now = new Date()
const year = ref(now.getFullYear())
const month = ref(now.getMonth() + 1)
const filter = ref('all')
const list = ref([])
const stats = ref({ pending: '0', settled: '0', reversed: '0', adjustment: '0' })
const pendingCount = ref(0)
const settledCount = ref(0)
const reversedCount = ref(0)
const adjustmentCount = ref(0)
const loading = ref(false)

const tabs = [
  { key: 'all', label: '全部' },
  { key: 'pending', label: '待发放' },
  { key: 'settled', label: '已发放' },
  { key: 'reversed', label: '被冲销' },
  { key: 'adjustment', label: '追回' }
]

const setFilter = (v) => {
  filter.value = v
  fetchList()
}

const prevMonth = () => {
  if (month.value === 1) {
    year.value -= 1
    month.value = 12
  } else {
    month.value -= 1
  }
  fetchAll()
}
const nextMonth = () => {
  if (month.value === 12) {
    year.value += 1
    month.value = 1
  } else {
    month.value += 1
  }
  fetchAll()
}

const fetchStats = async () => {
  try {
    const res = await http.request({
      url: '/api/mall/workspace/my-commissions/stats',
      method: 'GET',
      data: { year: year.value, month: month.value }
    })
    const d = res.data
    stats.value = {
      pending: Number(d.by_status?.pending?.amount || 0).toFixed(2),
      settled: Number(d.by_status?.settled?.amount || 0).toFixed(2),
      reversed: Number(d.by_status?.reversed?.amount || 0).toFixed(2),
      adjustment: Number(d.adjustment?.amount || 0).toFixed(2)
    }
    pendingCount.value = d.by_status?.pending?.count || 0
    settledCount.value = d.by_status?.settled?.count || 0
    reversedCount.value = d.by_status?.reversed?.count || 0
    adjustmentCount.value = d.adjustment?.count || 0
  } catch (e) {
    uni.showToast({ title: e?.detail || '统计失败', icon: 'none' })
  }
}

const fetchList = async () => {
  loading.value = true
  try {
    const res = await http.request({
      url: '/api/mall/workspace/my-commissions',
      method: 'GET',
      data: {
        status: filter.value,
        year: year.value,
        month: month.value,
        limit: 50
      }
    })
    list.value = res.data?.records || []
  } catch (e) {
    uni.showToast({ title: e?.detail || '加载失败', icon: 'none' })
  } finally {
    loading.value = false
  }
}

const fetchAll = () => {
  fetchStats()
  fetchList()
}

onLoad(() => fetchAll())

const formatAmount = (v) => {
  const n = Number(v)
  if (n >= 0) return `+¥${n.toFixed(2)}`
  return `-¥${Math.abs(n).toFixed(2)}`
}

const amountClass = (it) => {
  if (it.is_adjustment) return 'item__amount--adj'
  if (it.status === 'reversed') return 'item__amount--reversed'
  if (it.status === 'settled') return 'item__amount--settled'
  return 'item__amount--pending'
}

const refTypeLabel = (t) => {
  if (t === 'mall_order') return '商城订单'
  if (t === 'store_sale') return '门店零售'
  if (t === 'b2b_order') return 'B2B'
  return '—'
}

const dateStr = (v) => {
  if (!v) return ''
  const d = new Date(v)
  return `${d.getMonth() + 1}-${d.getDate()} ${d.getHours().toString().padStart(2, '0')}:${d.getMinutes().toString().padStart(2, '0')}`
}

const statusLabel = (it) => {
  if (it.is_adjustment) return '追回'
  if (it.status === 'pending') return '待发放'
  if (it.status === 'settled') return '已发放'
  if (it.status === 'reversed') return '被冲销'
  return it.status
}

const statusStyle = (it) => {
  if (it.is_adjustment) return { background: '#fff1f0', color: '#cf1322' }
  if (it.status === 'reversed') return { background: '#f4f4f4', color: '#8c8c8c' }
  if (it.status === 'settled') return { background: '#e6ffed', color: '#389e0d' }
  return { background: '#fffbe6', color: '#c9a961' }
}

const originStatusLabel = (s) => {
  if (s === 'settled') return '上月已发'
  if (s === 'pending') return '原待发放'
  return s
}
</script>

<style lang="scss" scoped>
.page {
  background: #faf8f5;
  min-height: 100vh;
  padding-bottom: 40rpx;
}
.header {
  background: #0e0e0e;
  color: #c9a961;
  padding: 40rpx 32rpx;
}
.header__title {
  font-size: 40rpx;
  font-weight: 700;
}
.header__month-picker {
  margin-top: 16rpx;
  display: flex;
  gap: 32rpx;
  align-items: center;
  font-size: 28rpx;
}
.header__month {
  flex: 1;
  text-align: center;
}
.summary {
  display: flex;
  gap: 12rpx;
  padding: 24rpx 24rpx 0;
}
.summary__card {
  flex: 1;
  background: #fff;
  padding: 16rpx 12rpx;
  border-radius: 12rpx;
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: 4rpx;
  border: 2rpx solid transparent;
}
.summary__card--active {
  border-color: #c9a961;
}
.summary__label {
  font-size: 22rpx;
  color: #8c8c8c;
}
.summary__value {
  font-size: 26rpx;
  font-weight: 700;
}
.summary__value--pending { color: #c9a961; }
.summary__value--settled { color: #389e0d; }
.summary__value--reversed { color: #8c8c8c; }
.summary__value--adj { color: #cf1322; }
.summary__count {
  font-size: 20rpx;
  color: #bfbfbf;
}
.tabs {
  display: flex;
  gap: 16rpx;
  padding: 24rpx 24rpx 0;
  overflow-x: auto;
}
.tab {
  padding: 12rpx 24rpx;
  background: #fff;
  border-radius: 24rpx;
  font-size: 24rpx;
  color: #8c8c8c;
  white-space: nowrap;
}
.tab--active {
  background: #0e0e0e;
  color: #c9a961;
  font-weight: 600;
}
.empty {
  padding: 80rpx;
  text-align: center;
  color: #bfbfbf;
  font-size: 26rpx;
}
.list { padding: 16rpx 24rpx; }
.item {
  background: #fff;
  padding: 24rpx;
  border-radius: 12rpx;
  margin-bottom: 16rpx;
}
.item__row1 {
  display: flex;
  justify-content: space-between;
  align-items: center;
  margin-bottom: 8rpx;
}
.item__order-no {
  font-size: 28rpx;
  font-weight: 600;
}
.item__amount {
  font-size: 32rpx;
  font-weight: 700;
}
.item__amount--adj { color: #cf1322; }
.item__amount--reversed { color: #8c8c8c; text-decoration: line-through; }
.item__amount--settled { color: #389e0d; }
.item__amount--pending { color: #c9a961; }
.item__row2 {
  display: flex;
  justify-content: space-between;
  align-items: center;
}
.item__meta {
  font-size: 22rpx;
  color: #8c8c8c;
}
.item__status {
  padding: 4rpx 12rpx;
  border-radius: 8rpx;
  font-size: 22rpx;
}
.item__adjustment {
  margin-top: 12rpx;
  padding: 12rpx;
  background: #fff1f0;
  border-radius: 8rpx;
  display: flex;
  flex-direction: column;
  gap: 4rpx;
}
.item__adjustment-line {
  font-size: 22rpx;
  color: #cf1322;
  font-weight: 500;
}
.item__adjustment-note {
  font-size: 22rpx;
  color: #8c8c8c;
}
.item__notes {
  margin-top: 8rpx;
  font-size: 22rpx;
  color: #8c8c8c;
}
</style>
