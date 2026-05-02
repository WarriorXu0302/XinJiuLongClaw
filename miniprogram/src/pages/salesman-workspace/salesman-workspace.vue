<!--
  业务员 - 工作入口（tabBar 第 3 个）

  网格入口：打卡 / 考勤 / 拜访 / 请假 / 报销 / 稽查 / KPI / 通知
-->
<template>
  <view class="page">
    <view class="hero">
      <view class="hero__title">
        工作
      </view>
      <view class="hero__sub">
        打卡、请假、报销、KPI，一站式处理
      </view>
    </view>

    <view class="section">
      <view class="section__title">
        今日考勤
      </view>
      <view class="today">
        <view class="today__item">
          <text class="today__label">
            上班打卡
          </text>
          <text :class="['today__value', todayCheckin.work_in ? 'today__value--done' : '']">
            {{ todayCheckin.work_in || '未打卡' }}
          </text>
        </view>
        <view class="today__divider" />
        <view class="today__item">
          <text class="today__label">
            下班打卡
          </text>
          <text :class="['today__value', todayCheckin.work_out ? 'today__value--done' : '']">
            {{ todayCheckin.work_out || '未打卡' }}
          </text>
        </view>
      </view>
      <view
        class="today__btn"
        @tap="toPage('/pages/salesman-checkin/salesman-checkin')"
      >
        去打卡
      </view>
    </view>

    <view class="section">
      <view class="section__title">
        快捷入口
      </view>
      <view class="grid">
        <view
          v-for="e in entries"
          :key="e.key"
          class="grid__cell"
          @tap="toPage(e.path)"
        >
          <text class="grid__icon">
            {{ e.icon }}
          </text>
          <text class="grid__label">
            {{ e.label }}
          </text>
          <text
            v-if="badges[e.key]"
            class="grid__badge"
          >
            {{ badges[e.key] }}
          </text>
        </view>
      </view>
    </view>
    <SalesmanTabbar active="workspace" />
  </view>
</template>

<script setup>
import SalesmanTabbar from '@/components/salesman-tabbar/salesman-tabbar.vue'

const todayCheckin = ref({ work_in: null, work_out: null })
const badges = ref({ notifications: 0 })

const entries = [
  { key: 'checkin', icon: '📍', label: '打卡', path: '/pages/salesman-checkin/salesman-checkin' },
  { key: 'attendance', icon: '📅', label: '考勤', path: '/pages/salesman-attendance/salesman-attendance' },
  { key: 'visit', icon: '🚗', label: '拜访', path: '/pages/salesman-visit/salesman-visit' },
  { key: 'leave', icon: '🏖', label: '请假', path: '/pages/salesman-leave/salesman-leave' },
  { key: 'expense', icon: '💰', label: '报销', path: '/pages/salesman-expense/salesman-expense' },
  { key: 'inspection', icon: '🔍', label: '扫码稽查', path: '/pages/salesman-inspection/salesman-inspection' },
  { key: 'kpi', icon: '📊', label: 'KPI', path: '/pages/salesman-kpi/salesman-kpi' },
  { key: 'notifications', icon: '🔔', label: '通知', path: '/pages/salesman-notifications/salesman-notifications' }
]

const toPage = (url) => uni.navigateTo({ url })

const fmtCheckinTime = (t) => {
  if (!t) return null
  const d = new Date(t)
  return `${String(d.getHours()).padStart(2, '0')}:${String(d.getMinutes()).padStart(2, '0')}`
}
const loadTodayCheckin = async () => {
  try {
    const res = await http.request({
      url: '/api/mall/workspace/attendance/today',
      method: 'GET'
    })
    todayCheckin.value = {
      work_in: fmtCheckinTime(res.data?.work_in?.checkin_time),
      work_out: fmtCheckinTime(res.data?.work_out?.checkin_time)
    }
  } catch {}
}

const loadBadges = async () => {
  try {
    const res = await http.request({
      url: '/api/mall/workspace/notifications/unread-count',
      method: 'GET',
      dontTrunLogin: true
    })
    badges.value.notifications = res.data?.count || 0
  } catch {}
}

onShow(() => {
  loadTodayCheckin()
  loadBadges()
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
  padding: 40rpx 32rpx 32rpx;
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
    opacity: 0.85;
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
    margin-bottom: 20rpx;
    padding-left: 12rpx;
    border-left: 6rpx solid $color-gold;
  }
}

.today {
  display: flex;
  padding: 16rpx 0;

  &__item {
    flex: 1;
    display: flex;
    flex-direction: column;
    align-items: center;
    padding: 16rpx 0;
  }
  &__label {
    font-size: 22rpx;
    color: $color-muted;
  }
  &__value {
    margin-top: 8rpx;
    font-size: 32rpx;
    font-weight: 600;
    color: $color-hint;
    font-family: Menlo, Consolas, monospace;

    &--done { color: $color-gold-deep; }
  }
  &__divider {
    width: 2rpx;
    background: $color-line;
  }
  &__btn {
    margin-top: 16rpx;
    padding: 20rpx 0;
    background: $color-ink;
    color: $color-gold;
    font-size: 28rpx;
    text-align: center;
    border-radius: 12rpx;
    letter-spacing: 2rpx;
  }
}

.grid {
  display: grid;
  grid-template-columns: repeat(4, 1fr);
  gap: 20rpx;

  &__cell {
    position: relative;
    padding: 24rpx 0;
    background: $color-cream;
    border-radius: 12rpx;
    text-align: center;
  }
  &__icon {
    display: block;
    font-size: 48rpx;
    line-height: 1;
  }
  &__label {
    display: block;
    margin-top: 12rpx;
    font-size: 24rpx;
    color: $color-ink-soft;
  }
  &__badge {
    position: absolute;
    top: 8rpx;
    right: 8rpx;
    min-width: 32rpx;
    padding: 0 8rpx;
    height: 32rpx;
    line-height: 32rpx;
    background: $color-err;
    color: #fff;
    border-radius: 16rpx;
    font-size: 20rpx;
    text-align: center;
  }
}
</style>
