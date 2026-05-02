<!--
  业务员工作台专用底部导航（小程序 tabBar 不支持多角色 + 动态配置，
  所以每个业务员页面自己引一个这个组件）。

  4 个入口：接单池 / 我的订单 / 工作 / 我的
  props: active — 'home' | 'orders' | 'workspace' | 'profile'
-->
<template>
  <view class="stb">
    <view
      v-for="i in items"
      :key="i.key"
      :class="['stb__item', active === i.key && 'stb__item--active']"
      @tap="onTap(i)"
    >
      <text class="stb__icon">{{ i.icon }}</text>
      <text class="stb__label">{{ i.label }}</text>
    </view>
  </view>
</template>

<script setup>
const props = defineProps({
  active: { type: String, default: 'home' }
})

const items = [
  { key: 'home', icon: '🏠', label: '接单池', path: '/pages/salesman-home/salesman-home' },
  { key: 'orders', icon: '📋', label: '我的订单', path: '/pages/salesman-orders/salesman-orders' },
  { key: 'workspace', icon: '🧰', label: '工作', path: '/pages/salesman-workspace/salesman-workspace' },
  { key: 'profile', icon: '👤', label: '我的', path: '/pages/salesman-profile/salesman-profile' }
]

const onTap = (i) => {
  if (i.key === props.active) return
  uni.reLaunch({ url: i.path })
}
</script>

<style lang="scss" scoped>
.stb {
  position: fixed;
  left: 0;
  right: 0;
  bottom: 0;
  display: flex;
  height: 110rpx;
  padding-bottom: env(safe-area-inset-bottom);
  background: #0E0E0E;
  border-top: 1rpx solid rgba(201, 169, 97, 0.18);
  z-index: 999;
}
.stb__item {
  flex: 1;
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  color: #9A9A9A;
  font-size: 22rpx;
  gap: 4rpx;
}
.stb__item--active {
  color: #C9A961;
}
.stb__icon {
  font-size: 40rpx;
  line-height: 1;
}
.stb__label {
  font-size: 20rpx;
  letter-spacing: 0.5rpx;
}
</style>
