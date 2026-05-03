<!--
  业务员 - 我的（tabBar 第 4 个）

  布局：
    - 顶部个人卡
    - 本月数据 4 格看板
    - 功能入口列表
      生成邀请码 / 我的客户 / 跳单告警 / 通知中心 / 考勤 / 请假 / 报销 /
      KPI / 扫码稽查 / 接单开关 / 收款码 / 退出
-->
<template>
  <view class="page">
    <!-- 个人卡 -->
    <view class="hero">
      <view class="hero__avatar">
        <text>{{ profile.nickname?.[0] || '业' }}</text>
      </view>
      <view class="hero__info">
        <view class="hero__name">
          <text>{{ profile.nickname }}</text>
          <text class="hero__tag">
            {{ profile.assigned_brand_name || '—' }}
          </text>
        </view>
        <view class="hero__meta">
          <text>工号 {{ profile.employee_no || '—' }}</text>
          <text>·</text>
          <text>{{ profile.phone || '—' }}</text>
        </view>
      </view>
    </view>

    <!-- 本月数据 -->
    <view class="stats">
      <view class="stats__title">
        <text>本月数据</text>
        <text
          class="stats__view-more"
          @tap="toWorkspace"
        >
          工作台 ›
        </text>
      </view>
      <view class="stats__grid">
        <view class="stats__cell">
          <text class="stats__num">
            {{ stats.month_orders }}
          </text>
          <text class="stats__label">
            接单数
          </text>
        </view>
        <view class="stats__cell">
          <text class="stats__num">
            {{ fmtCompactMoney(stats.month_gmv) }}
          </text>
          <text class="stats__label">
            成交额
          </text>
        </view>
        <view class="stats__cell">
          <text class="stats__num">
            {{ fmtMoney(stats.month_commission_pending) }}
          </text>
          <text class="stats__label">
            待入账提成
          </text>
        </view>
        <view class="stats__cell">
          <text class="stats__num">
            {{ fmtMoney(stats.month_commission_settled) }}
          </text>
          <text class="stats__label">
            已入账提成
          </text>
        </view>
        <view
          v-if="Number(stats.month_commission_reversed || 0) > 0"
          class="stats__cell stats__cell--warn"
        >
          <text class="stats__num">
            -{{ fmtMoney(stats.month_commission_reversed) }}
          </text>
          <text class="stats__label">
            退货冲销
          </text>
        </view>
      </view>
    </view>

    <!-- 接单开关 -->
    <view class="switch-row">
      <view class="switch-row__left">
        <text class="switch-row__label">
          接单开关
        </text>
        <text class="switch-row__hint">
          {{ profile.is_accepting_orders ? '在线接单中' : '已关闭，抢单池不再推送' }}
        </text>
      </view>
      <switch
        :checked="profile.is_accepting_orders"
        color="#C9A961"
        @change="onToggleAccepting"
      />
    </view>

    <!-- 功能入口 -->
    <view class="menu">
      <view class="menu__group-title">
        常用
      </view>
      <MenuItem
        icon="🎟"
        label="生成邀请码"
        :hint="`今日剩余 ${inviteRemain} 张`"
        @tap="toPage('/pages/salesman-invite/salesman-invite')"
      />
      <MenuItem
        icon="👥"
        label="我的客户"
        @tap="toPage('/pages/salesman-my-customers/salesman-my-customers')"
      />
      <MenuItem
        icon="⚠️"
        label="跳单告警"
        :badge="alertOpenCount"
        @tap="toPage('/pages/salesman-alerts/salesman-alerts')"
      />
      <MenuItem
        icon="🔔"
        label="通知中心"
        :badge="unreadCount"
        @tap="toPage('/pages/salesman-notifications/salesman-notifications')"
      />

      <view class="menu__group-title">
        考勤/请假/报销
      </view>
      <MenuItem
        icon="📍"
        label="打卡"
        @tap="toPage('/pages/salesman-checkin/salesman-checkin')"
      />
      <MenuItem
        icon="📅"
        label="我的考勤"
        @tap="toPage('/pages/salesman-attendance/salesman-attendance')"
      />
      <MenuItem
        icon="🚗"
        label="客户拜访"
        @tap="toPage('/pages/salesman-visit/salesman-visit')"
      />
      <MenuItem
        icon="🏖"
        label="请假申请"
        @tap="toPage('/pages/salesman-leave/salesman-leave')"
      />
      <MenuItem
        icon="💰"
        label="报销申请"
        @tap="toPage('/pages/salesman-expense/salesman-expense')"
      />

      <view class="menu__group-title">
        业务工具
      </view>
      <MenuItem
        icon="📊"
        label="我的 KPI"
        @tap="toPage('/pages/salesman-kpi/salesman-kpi')"
      />
      <MenuItem
        icon="🔍"
        label="扫码稽查"
        @tap="toPage('/pages/salesman-inspection/salesman-inspection')"
      />

      <view class="menu__group-title">
        账号
      </view>
      <MenuItem
        icon="💳"
        label="收款码设置"
        @tap="onSetPaymentQr"
      />
      <MenuItem
        icon="🚪"
        label="退出登录"
        danger
        @tap="onLogout"
      />
    </view>
    <SalesmanTabbar active="profile" />
  </view>
</template>

<script setup>
import MenuItem from './_MenuItem.vue'
import SalesmanTabbar from '@/components/salesman-tabbar/salesman-tabbar.vue'

const profile = ref({})
const stats = ref({
  month_orders: 0,
  month_gmv: 0,
  month_commission_pending: 0,
  month_commission_settled: 0,
  month_commission_reversed: 0
})
const inviteRemain = ref(20)
const alertOpenCount = ref(0)
const unreadCount = ref(0)

const fmtMoney = salesman.fmtMoney
const fmtCompactMoney = (n) => {
  if (!n && n !== 0) return '—'
  if (n >= 10000) return '¥' + (n / 10000).toFixed(1) + '万'
  return '¥' + Number(n).toLocaleString('zh-CN')
}

const loadProfile = async () => {
  const res = await http.request({
    url: '/api/mall/salesman/profile',
    method: 'GET'
  })
  profile.value = res.data || {}
}

const loadStats = async () => {
  const res = await http.request({
    url: '/api/mall/salesman/stats',
    method: 'GET',
    data: { range: 'month' }
  })
  stats.value = res.data || {}
}

const loadAlerts = async () => {
  try {
    const res = await http.request({
      url: '/api/mall/salesman/skip-alerts',
      method: 'GET',
      data: { status: 'open' },
      dontTrunLogin: true
    })
    alertOpenCount.value = res.data?.total || 0
  } catch {}
}

const loadUnread = async () => {
  try {
    const res = await http.request({
      url: '/api/mall/workspace/notifications/unread-count',
      method: 'GET',
      dontTrunLogin: true
    })
    unreadCount.value = res.data?.count || 0
  } catch {}
}

const toPage = (url) => uni.navigateTo({ url })
const toWorkspace = () => uni.navigateTo({ url: '/pages/salesman-workspace/salesman-workspace' })

const onToggleAccepting = async (e) => {
  const checked = e.detail.value
  profile.value.is_accepting_orders = checked
  try {
    await http.request({
      url: '/api/mall/salesman/profile/accepting-orders',
      method: 'PUT',
      data: { enabled: checked }
    })
    uni.showToast({ title: checked ? '已开启接单' : '已关闭接单', icon: 'none' })
  } catch {
    profile.value.is_accepting_orders = !checked
  }
}

// 上传单张收款码图到后端，拿到 URL
const uploadQrImage = (localPath) => {
  return new Promise((resolve, reject) => {
    const token = uni.getStorageSync('Token')
    uni.uploadFile({
      url: (import.meta.env.VITE_APP_BASE_API || '') + '/api/mall/salesman/attachments/upload',
      filePath: localPath,
      name: 'file',
      formData: { kind: 'payment_qr' },
      header: token ? { Authorization: token.startsWith('Bearer ') ? token : `Bearer ${token}` } : {},
      success: (r) => {
        try {
          const body = typeof r.data === 'string' ? JSON.parse(r.data) : r.data
          if (r.statusCode >= 200 && r.statusCode < 300 && body.url) {
            resolve(body.url)
          } else {
            reject(new Error(body.detail || '上传失败'))
          }
        } catch (e) { reject(e) }
      },
      fail: (err) => reject(err)
    })
  })
}

const onSetPaymentQr = () => {
  uni.showActionSheet({
    itemList: ['更新微信收款码', '更新支付宝收款码', '清空微信收款码', '清空支付宝收款码'],
    success: async (r) => {
      if (r.tapIndex === 0 || r.tapIndex === 1) {
        const kind = r.tapIndex === 0 ? 'wechat_qr_url' : 'alipay_qr_url'
        uni.chooseImage({
          count: 1,
          sizeType: ['compressed'],
          sourceType: ['album', 'camera'],
          success: async (ir) => {
            if (!ir.tempFilePaths?.length) return
            uni.showLoading({ title: '上传中…' })
            try {
              const url = await uploadQrImage(ir.tempFilePaths[0])
              await http.request({
                url: '/api/mall/salesman/profile/payment-qr',
                method: 'PUT',
                data: { [kind]: url }
              })
              uni.hideLoading()
              uni.showToast({ title: '已更新', icon: 'success' })
              loadProfile()
            } catch (e) {
              uni.hideLoading()
              uni.showToast({ title: e?.message || '上传失败', icon: 'none' })
            }
          }
        })
      } else if (r.tapIndex === 2 || r.tapIndex === 3) {
        const kind = r.tapIndex === 2 ? 'wechat_qr_url' : 'alipay_qr_url'
        await http.request({
          url: '/api/mall/salesman/profile/payment-qr',
          method: 'PUT',
          data: { [kind]: '' }
        })
        uni.showToast({ title: '已清空', icon: 'success' })
        loadProfile()
      }
    }
  })
}

const onLogout = () => {
  uni.showModal({
    title: '退出登录',
    content: '确定要退出吗？',
    success: (r) => {
      if (!r.confirm) return
      uni.removeStorageSync('Token')
      uni.removeStorageSync('loginResult')
      uni.removeStorageSync('hadLogin')
      uni.removeStorageSync('userType')
      uni.reLaunch({ url: '/pages/accountLogin/accountLogin' })
    }
  })
}

onShow(() => {
  loadProfile()
  loadStats()
  loadAlerts()
  loadUnread()
})
</script>

<style lang="scss" scoped>
@import '@/styles/variables.scss';

.page {
  min-height: 100vh;
  background: $color-cream;
  padding-bottom: calc(150rpx + env(safe-area-inset-bottom));
}

.hero {
  display: flex;
  align-items: center;
  gap: 24rpx;
  padding: 60rpx 32rpx 40rpx;
  background: $color-ink;

  &__avatar {
    width: 120rpx;
    height: 120rpx;
    border-radius: 50%;
    background: $color-gold;
    color: $color-ink;
    display: flex;
    align-items: center;
    justify-content: center;
    font-size: 60rpx;
    font-weight: 700;
    letter-spacing: 0;
  }
  &__info { flex: 1; }
  &__name {
    display: flex;
    align-items: center;
    gap: 16rpx;
    color: #fff;
    font-size: 36rpx;
    font-weight: 600;
  }
  &__tag {
    padding: 4rpx 16rpx;
    background: rgba(201,169,97,0.2);
    color: $color-gold;
    font-size: 22rpx;
    border-radius: 20rpx;
    font-weight: normal;
  }
  &__meta {
    display: flex;
    gap: 12rpx;
    margin-top: 12rpx;
    font-size: 24rpx;
    color: rgba(255,255,255,0.6);
  }
}

.stats {
  margin: -40rpx 24rpx 0;
  padding: 24rpx 28rpx 28rpx;
  background: $color-card;
  border-radius: 16rpx;
  box-shadow: 0 8rpx 40rpx rgba(14,14,14,0.08);

  &__title {
    display: flex;
    justify-content: space-between;
    align-items: center;
    font-size: 26rpx;
    font-weight: 600;
    color: $color-ink-soft;
    margin-bottom: 20rpx;
  }
  &__view-more {
    font-size: 22rpx;
    color: $color-gold-deep;
    font-weight: normal;
  }
  &__grid {
    display: grid;
    grid-template-columns: repeat(2, 1fr);
    gap: 16rpx;
  }
  &__cell {
    padding: 16rpx;
    background: $color-cream;
    border-radius: 12rpx;
    text-align: center;

    &--warn {
      background: rgba(255, 77, 79, 0.08);

      .stats__num {
        color: $color-err;
      }
    }
  }
  &__num {
    display: block;
    font-size: 36rpx;
    font-weight: 700;
    color: $color-gold-deep;
  }
  &__label {
    display: block;
    margin-top: 8rpx;
    font-size: 22rpx;
    color: $color-muted;
  }
}

.switch-row {
  margin: 24rpx;
  padding: 24rpx 32rpx;
  background: $color-card;
  border-radius: 16rpx;
  display: flex;
  justify-content: space-between;
  align-items: center;

  &__label {
    display: block;
    font-size: 28rpx;
    font-weight: 600;
    color: $color-ink-soft;
  }
  &__hint {
    display: block;
    margin-top: 4rpx;
    font-size: 22rpx;
    color: $color-muted;
  }
}

.menu {
  margin: 24rpx;
  background: $color-card;
  border-radius: 16rpx;
  overflow: hidden;

  &__group-title {
    padding: 24rpx 32rpx 8rpx;
    font-size: 22rpx;
    color: $color-hint;
    letter-spacing: 1rpx;
  }
}
</style>
