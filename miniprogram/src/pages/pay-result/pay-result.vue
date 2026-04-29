<template>
  <view class="container">
    <view v-if="sts == 0">
      <view class="pay-sts fail">
        订单提交失败
      </view>
      <view class="tips">
        请稍后重试
      </view>
      <view class="tips">
        或联系管理员处理
      </view>
      <view class="btns">
        <text
          class="button checkorder"
          @tap="toOrderList"
        >
          查看订单
        </text>
        <text
          class="button payagain"
          @tap="toOrderList"
        >
          返回订单
        </text>
      </view>
    </view>

    <view v-if="sts == 1">
      <view class="pay-sts succ">
        下单成功
      </view>
      <view class="tips">
        感谢您的购买
      </view>
      <view class="btns">
        <text
          class="button checkorder"
          @tap="toOrderList"
        >
          查看订单
        </text>
        <text
          class="button shopcontinue"
          @tap="toIndex"
        >
          继续购物
        </text>
      </view>
    </view>
  </view>
</template>

<script setup>
const sts = ref(0)
const orderNumbers = ref('')
/**
 * 生命周期函数--监听页面加载
 */
onLoad((options) => {
  sts.value = options.sts
  orderNumbers.value = options.orderNumbers
})

const toOrderList = () => {
  uni.navigateTo({
    url: '/pages/orderList/orderList?sts=0'
  })
}
const toIndex = () => {
  uni.switchTab({
    url: '/pages/index/index'
  })
}
// 无需支付：不提供重新支付入口
</script>

<style scoped lang="scss">
@use './pay-result.scss';
</style>
