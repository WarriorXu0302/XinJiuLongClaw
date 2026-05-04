<!--
  业务员 - 我的客户

  列表：referrer_salesman_id == me 的 consumer
  字段：昵称 / 手机（脱敏） / 绑定时间 / 最近下单 / 订单数 / 累计 GMV
-->
<template>
  <view class="page">
    <view class="header">
      <view class="header__title">
        我的客户
      </view>
      <view class="header__sub">
        共 {{ total }} 位，累计成交
        <text class="header__gmv">
          {{ totalGmv }}
        </text>
      </view>
    </view>

    <view
      v-if="loading"
      class="state"
    >
      加载中…
    </view>
    <view
      v-else-if="customers.length === 0"
      class="state"
    >
      暂无客户
    </view>

    <view
      v-for="c in customers"
      :key="c.id"
      class="card"
    >
      <view class="card__top">
        <view class="card__avatar">
          {{ (c.real_name || c.nickname || '客')[0] }}
        </view>
        <view class="card__info">
          <view class="card__name">
            <text>{{ c.real_name || c.nickname }}</text>
            <text
              v-if="c.archived"
              class="card__tag card__tag--archived"
            >
              已归档
            </text>
          </view>
          <view class="card__bound">
            绑定于 {{ formatDate(c.bound_at) }}
          </view>
          <view
            v-if="c.default_address"
            class="card__addr"
          >
            {{ c.default_address.province }}{{ c.default_address.city }}{{ c.default_address.area }} {{ c.default_address.addr }}
          </view>
        </view>
      </view>

      <view class="card__quick">
        <view
          :class="['quick-btn', !c.phone && 'quick-btn--disabled']"
          @tap="onCall(c)"
        >
          <text class="quick-btn__icon">
            📞
          </text>
          <text>{{ c.phone || '无电话' }}</text>
        </view>
        <view
          :class="['quick-btn', !c.default_address && 'quick-btn--disabled']"
          @tap="onNavigate(c)"
        >
          <text class="quick-btn__icon">
            📍
          </text>
          <text>导航</text>
        </view>
      </view>

      <view class="card__stats">
        <view class="card__stat">
          <text class="card__stat-num">
            {{ c.total_orders }}
          </text>
          <text class="card__stat-label">
            订单数
          </text>
        </view>
        <view class="card__stat-divider" />
        <view class="card__stat">
          <text class="card__stat-num">
            {{ fmtMoney(c.total_gmv) }}
          </text>
          <text class="card__stat-label">
            累计 GMV
          </text>
        </view>
        <view class="card__stat-divider" />
        <view class="card__stat">
          <text class="card__stat-num">
            {{ relativeTime(c.last_order_at) }}
          </text>
          <text class="card__stat-label">
            最近下单
          </text>
        </view>
      </view>
    </view>
  </view>
</template>

<script setup>
const customers = ref([])
const total = ref(0)
const totalGmvServer = ref(null)
const loading = ref(false)

const fmtMoney = salesman.fmtMoney
const relativeTime = salesman.relativeTime

const formatDate = (ts) => {
  if (!ts) return '—'
  return String(ts).slice(0, 10)
}

const totalGmv = computed(() => {
  if (totalGmvServer.value !== null) return fmtMoney(totalGmvServer.value)
  const sum = customers.value.reduce((a, b) => a + (b.total_gmv || 0), 0)
  return fmtMoney(sum)
})

const load = async () => {
  loading.value = true
  try {
    const res = await http.request({
      url: '/api/mall/salesman/my-customers',
      method: 'GET'
    })
    const d = res.data || {}
    customers.value = d.records || []
    total.value = d.total ?? customers.value.length
    totalGmvServer.value = d.total_gmv ?? null
  } finally {
    loading.value = false
  }
}

const onCall = async (customer) => {
  if (!customer.phone) {
    uni.showToast({ title: '客户未留电话', icon: 'none' })
    return
  }
  // G16：点拨号时才去后端取完整号 + 写审计
  try {
    const res = await http.request({
      url: `/api/mall/salesman/my-customers/${customer.id}/phone`,
      method: 'GET',
    })
    const full = res.data?.phone
    if (!full) {
      uni.showToast({ title: '无法获取电话', icon: 'none' })
      return
    }
    uni.makePhoneCall({ phoneNumber: full, fail: () => {} })
  } catch (e) {
    uni.showToast({ title: e?.detail || '获取电话失败', icon: 'none' })
  }
}

// 调用地图：mp-weixin 直接打开地图；h5/其他端弹复制地址
const onNavigate = (c) => {
  const a = c?.default_address
  if (!a) {
    uni.showToast({ title: '客户未留收货地址', icon: 'none' })
    return
  }
  const full = `${a.province || ''}${a.city || ''}${a.area || ''} ${a.addr || ''}`.trim()
  // #ifdef MP-WEIXIN
  // 微信端无经纬度也能打开地图（传地址让用户搜索）
  uni.openLocation({
    latitude: a.lat || 0,
    longitude: a.lng || 0,
    name: c.real_name || c.nickname || '客户',
    address: full,
    fail: () => {
      uni.setClipboardData({ data: full })
      uni.showToast({ title: '地址已复制', icon: 'none' })
    }
  })
  // #endif
  // #ifndef MP-WEIXIN
  uni.setClipboardData({ data: full })
  uni.showToast({ title: '地址已复制，请前往地图应用粘贴', icon: 'none', duration: 2000 })
  // #endif
}

onMounted(() => load())
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

  &__title {
    font-size: 40rpx;
    font-weight: 600;
    color: $color-gold;
  }
  &__sub {
    margin-top: 8rpx;
    font-size: 24rpx;
    color: $color-gold-soft;
  }
  &__gmv {
    color: $color-gold;
    font-weight: 600;
    margin-left: 8rpx;
  }
}

.state {
  padding: 80rpx 0;
  text-align: center;
  color: $color-hint;
}

.card {
  margin: 24rpx 24rpx 0;
  padding: 24rpx 32rpx;
  background: $color-card;
  border-radius: 16rpx;

  &__top {
    display: flex;
    gap: 20rpx;
    align-items: center;
  }
  &__avatar {
    width: 80rpx;
    height: 80rpx;
    border-radius: 50%;
    background: $color-gold;
    color: $color-ink;
    display: flex;
    align-items: center;
    justify-content: center;
    font-size: 36rpx;
    font-weight: 700;
  }
  &__info { flex: 1; }
  &__name {
    display: flex;
    align-items: center;
    gap: 16rpx;
    font-size: 30rpx;
    font-weight: 600;
    color: $color-ink-soft;
  }
  &__tag {
    font-size: 20rpx;
    padding: 2rpx 10rpx;
    border-radius: 10rpx;

    &--archived {
      color: $color-err;
      background: rgba(255, 77, 79, 0.1);
    }
  }
  &__bound {
    margin-top: 4rpx;
    font-size: 22rpx;
    color: $color-hint;
  }
  &__addr {
    margin-top: 6rpx;
    font-size: 22rpx;
    color: $color-hint;
    line-height: 1.4;
  }
  &__quick {
    margin-top: 16rpx;
    display: flex;
    gap: 16rpx;
  }

  &__stats {
    margin-top: 20rpx;
    padding: 16rpx 0;
    display: flex;
    background: $color-cream;
    border-radius: 12rpx;
  }
  &__stat {
    flex: 1;
    text-align: center;
  }
  &__stat-num {
    display: block;
    font-size: 26rpx;
    font-weight: 600;
    color: $color-ink-soft;
  }
  &__stat-label {
    display: block;
    margin-top: 4rpx;
    font-size: 20rpx;
    color: $color-hint;
  }
  &__stat-divider {
    width: 2rpx;
    background: $color-line;
  }
}

.quick-btn {
  flex: 1;
  height: 64rpx;
  line-height: 64rpx;
  text-align: center;
  background: $color-cream;
  color: $color-ink-soft;
  border: 1rpx solid $color-line;
  border-radius: 10rpx;
  font-size: 24rpx;

  &__icon {
    margin-right: 6rpx;
  }

  &--disabled {
    opacity: 0.4;
  }
}
</style>
