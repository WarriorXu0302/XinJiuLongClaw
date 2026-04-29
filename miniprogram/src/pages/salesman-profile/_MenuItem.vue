<!-- 通用菜单行 -->
<template>
  <view
    :class="['item', danger && 'item--danger']"
    @tap="$emit('tap')"
  >
    <text class="item__icon">
      {{ icon }}
    </text>
    <text class="item__label">
      {{ label }}
    </text>
    <text
      v-if="hint"
      class="item__hint"
    >
      {{ hint }}
    </text>
    <text
      v-if="badge"
      class="item__badge"
    >
      {{ badge }}
    </text>
    <text class="item__arrow">
      ›
    </text>
  </view>
</template>

<script setup>
defineProps({
  icon: { type: String, default: '' },
  label: { type: String, default: '' },
  hint: { type: String, default: '' },
  badge: { type: [Number, String], default: 0 },
  danger: Boolean
})
defineEmits(['tap'])
</script>

<style lang="scss" scoped>
@import '@/styles/variables.scss';

.item {
  display: flex;
  align-items: center;
  padding: 28rpx 32rpx;
  border-bottom: 1rpx solid $color-line-soft;
  font-size: 28rpx;

  &:last-child { border-bottom: none; }

  &__icon {
    width: 44rpx;
    margin-right: 16rpx;
    font-size: 32rpx;
    text-align: center;
  }
  &__label {
    flex: 1;
    color: $color-ink-soft;
  }
  &__hint {
    font-size: 22rpx;
    color: $color-hint;
    margin-right: 12rpx;
  }
  &__badge {
    min-width: 36rpx;
    padding: 0 10rpx;
    height: 36rpx;
    line-height: 36rpx;
    background: $color-err;
    color: #fff;
    font-size: 22rpx;
    border-radius: 18rpx;
    text-align: center;
    margin-right: 12rpx;
  }
  &__arrow {
    color: $color-hint;
    font-size: 32rpx;
  }

  &--danger &__label { color: $color-err; }
}
</style>
