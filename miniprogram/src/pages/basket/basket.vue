<template>
  <view class="container">
    <view class="prod-list">
      <block
        v-for="(item, scIndex) in shopCartItemDiscounts"
        :key="scIndex"
      >
        <view class="prod-block">
          <view
            v-if="item.chooseDiscountItemDto"
            class="discount-tips"
          >
            <text class="text-block">
              {{ wxs.parseDiscount(item.chooseDiscountItemDto.discountRule) }}
            </text>
            <text class="text-list">
              {{
                wxs.parseDiscountMsg(item.chooseDiscountItemDto.discountRule, item.chooseDiscountItemDto.needAmount, item.chooseDiscountItemDto.discount)
              }}
            </text>
          </view>
          <block
            v-for="(prod, index) in item.shopCartItems"
            :key="index"
          >
            <view class="item">
              <view class="btn">
                <label>
                  <checkbox
                    :data-scindex="scIndex"
                    :data-index="index"
                    :value="prod.prodId"
                    :checked="prod.checked"
                    :disabled="prod.isAvailable === false"
                    color="#C9A961"
                    @tap="onSelectedItem"
                  />
                </label>
              </view>
              <view class="prodinfo">
                <view class="pic">
                  <image :src="prod.pic" />
                </view>
                <view class="opt">
                  <view class="prod-name">
                    {{ prod.prodName }}
                    <text
                      v-if="prod.isAvailable === false"
                      style="margin-left:8rpx;padding:2rpx 8rpx;background:#f5222d;color:#fff;border-radius:4rpx;font-size:20rpx"
                    >
                      已下架
                    </text>
                  </view>
                  <text :class="'prod-info-text ' + (prod.skuName?'':'empty-n')">
                    {{ prod.skuName }}
                  </text>
                  <view class="price-count">
                    <view class="price">
                      <text class="symbol">
                        ￥
                      </text>
                      <text class="big-num">
                        {{ wxs.parsePrice(prod.price)[0] }}
                      </text>
                      <text class="small-num">
                        .{{ wxs.parsePrice(prod.price)[1] }}
                      </text>
                    </view>
                    <view class="m-numSelector">
                      <view
                        class="minus"
                        :data-scindex="scIndex"
                        :data-index="index"
                        @tap="onCountMinus"
                      />
                      <input
                        type="number"
                        :value="prod.prodCount"
                        disabled
                      >
                      <view
                        class="plus"
                        :data-scindex="scIndex"
                        :data-index="index"
                        @tap="onCountPlus"
                      />
                    </view>
                  </view>
                </view>
              </view>
            </view>
          </block>
        </view>
      </block>
    </view>

    <view
      v-if="!shopCartItemDiscounts.length"
      class="empty"
    >
      <view class="img">
        <image src="@/static/images/tabbar/basket.png" />
      </view>
      <view class="txt">
        您还没有添加任何商品哦~
      </view>
    </view>

    <!-- 底部按钮 -->
    <view
      v-if="shopCartItemDiscounts.length>0"
      class="cart-footer"
    >
      <view class="btn all">
        <checkbox
          :checked="allChecked"
          color="#C9A961"
          @tap="onSelAll"
        />
        全选
      </view>
      <view
        class="btn del"
        @tap="onDelBasket"
      >
        <text>删除</text>
      </view>
      <view class="btn total">
        <view class="finally">
          <text>合计:</text>
          <view class="price">
            <text class="symbol">
              ￥
            </text>
            <text class="big-num">
              {{ wxs.parsePrice(finalMoney)[0] }}
            </text>
            <text class="small-num">
              .{{ wxs.parsePrice(finalMoney)[1] }}
            </text>
          </view>
        </view>
        <view
          v-if="subtractMoney>0"
          class="total-msg"
        >
          总额:￥{{ wxs.toPrice(totalMoney) }} 立减:￥{{ wxs.toPrice(subtractMoney) }}
        </view>
      </view>
      <view
        class="btn settle"
        @tap="toFirmOrder"
      >
        <text>结算</text>
      </view>
    </view>
    <!-- end 底部按钮 -->
  </view>
</template>

<script setup>
const wxs = number()
/**
 * 生命周期函数--监听页面显示
 */
onShow(() => {
  if (uni.getStorageSync('userType') === 'salesman') {
    uni.reLaunch({ url: '/pages/salesman-home/salesman-home' })
    return
  }
  loadBasketData()
  http.getCartCount() // 重新计算购物车总数量
})

const allChecked = ref(false)
const shopCartItemDiscounts = ref([])
const loadBasketData = () => {
  uni.showLoading() // 加载购物车
  // 后端 /api/mall/cart 返回 {records:[MallCartItemVO...], total, totalPrice}
  // 前端模板期望 [{shopCartItemDiscounts:[{shopCartItems:[...]}]}]，做一次壳转换
  http.request({
    url: '/api/mall/cart',
    method: 'GET',
    data: {}
  })
    .then(({ data }) => {
      const records = data?.records || []
      if (records.length > 0) {
        records.forEach(item => {
          item.checked = false
          item.prodCount = item.count
        })
        shopCartItemDiscounts.value = [
          { chooseDiscountItemDto: null, shopCartItems: records }
        ]
        allChecked.value = false
      } else {
        shopCartItemDiscounts.value = []
      }
      calTotalPrice() // 计算总价
      uni.hideLoading()
    })
}

/**
 * 去结算
 */
const toFirmOrder = () => {
  const shopCartItemDiscountsParam = shopCartItemDiscounts.value
  const basketIds = []
  const orderItems = []
  let hasUnavailable = false
  shopCartItemDiscountsParam.forEach(shopCartItemDiscount => {
    shopCartItemDiscount.shopCartItems.forEach(shopCartItem => {
      if (shopCartItem.checked) {
        // 已下架商品不结算（后端 create_order 也会拒绝，但前端先挡住更友好）
        if (shopCartItem.isAvailable === false) {
          hasUnavailable = true
          return
        }
        basketIds.push(shopCartItem.basketId)
        orderItems.push({
          skuId: shopCartItem.skuId,
          count: shopCartItem.prodCount || shopCartItem.count
        })
      }
    })
  })

  if (hasUnavailable) {
    uni.showToast({ title: '已下架商品不能结算，已自动跳过', icon: 'none' })
  }
  if (!basketIds.length) {
    uni.showToast({
      title: '请选择商品',
      icon: 'none'
    })
    return
  }

  uni.setStorageSync('basketIds', JSON.stringify(basketIds))
  // 后端 preview/create 走 sku 维度，存一份 items 给 submit-order 直接用
  uni.setStorageSync('orderItems', JSON.stringify(orderItems))
  uni.navigateTo({
    url: '/pages/submit-order/submit-order?orderEntry=0'
  })
}

/**
 * 全选
 */
const onSelAll = () => {
  const allCheckedParam = !allChecked.value // 改变状态
  const shopCartItemDiscountsParam = shopCartItemDiscounts.value
  for (let i = 0; i < shopCartItemDiscountsParam.length; i++) {
    const cItems = shopCartItemDiscountsParam[i].shopCartItems
    for (let j = 0; j < cItems.length; j++) {
      cItems[j].checked = allCheckedParam
    }
  }
  allChecked.value = allCheckedParam
  shopCartItemDiscounts.value = shopCartItemDiscountsParam
  calTotalPrice() // 计算总价
}

/**
 * 每一项的选择事件
 * +
 */
const onSelectedItem = (e) => {
  const index = e.currentTarget.dataset.index // 获取data- 传进来的index
  const scindex = e.currentTarget.dataset.scindex
  const shopCartItemDiscountsParam = shopCartItemDiscounts.value // 获取购物车列表
  const checked = shopCartItemDiscountsParam[scindex].shopCartItems[index].checked // 获取当前商品的选中状态
  shopCartItemDiscountsParam[scindex].shopCartItems[index].checked = !checked // 改变状态
  shopCartItemDiscounts.value = shopCartItemDiscountsParam
  checkAllSelected() // 检查全选状态
  calTotalPrice() // 计算总价
}

/**
 * 检查全选状态
 */
const checkAllSelected = () => {
  let allCheckedParam = true
  const shopCartItemDiscountsParam = shopCartItemDiscounts.value
  let flag = false
  for (let i = 0; i < shopCartItemDiscountsParam.length; i++) {
    const cItems = shopCartItemDiscountsParam[i].shopCartItems
    for (let j = 0; j < cItems.length; j++) {
      if (!cItems[j].checked) {
        allCheckedParam = !allCheckedParam
        flag = true
        break
      }
    }
    if (flag) break
  }
  allChecked.value = allCheckedParam
}

const totalMoney = ref(0)
const subtractMoney = ref(0)
const finalMoney = ref(0)
/**
 * 计算购物车总额
 * 后端没有 /totalPay，直接在前端求和选中项。
 */
const calTotalPrice = () => {
  const shopCartItemDiscountsParam = shopCartItemDiscounts.value
  let total = 0
  for (let i = 0; i < shopCartItemDiscountsParam.length; i++) {
    const cItems = shopCartItemDiscountsParam[i].shopCartItems
    for (let j = 0; j < cItems.length; j++) {
      if (cItems[j].checked) {
        const price = Number(cItems[j].price || 0)
        const count = Number(cItems[j].prodCount || cItems[j].count || 0)
        total += price * count
      }
    }
  }
  totalMoney.value = total
  subtractMoney.value = 0
  finalMoney.value = total
}

/**
 * 减少数量
 */
const onCountMinus = (e) => {
  const index = e.currentTarget.dataset.index
  const scindex = e.currentTarget.dataset.scindex
  const shopCartItemDiscountsParam = shopCartItemDiscounts.value
  const prodCount = shopCartItemDiscountsParam[scindex].shopCartItems[index].prodCount
  if (prodCount > 1) {
    updateCount(shopCartItemDiscountsParam, scindex, index, -1)
  }
}

/**
 * 增加数量
 */
const onCountPlus = (e) => {
  const index = e.currentTarget.dataset.index
  const scindex = e.currentTarget.dataset.scindex
  const shopCartItemDiscountsParam = shopCartItemDiscounts.value
  updateCount(shopCartItemDiscountsParam, scindex, index, 1)
}

/**
 * 改变购物车数量接口
 */
const updateCount = (shopCartItemDiscountsParam, scindex, index, prodCount) => {
  uni.showLoading({
    mask: true
  })
  http.request({
    url: '/api/mall/cart/change',
    method: 'POST',
    data: {
      count: prodCount,
      prodId: shopCartItemDiscountsParam[scindex].shopCartItems[index].prodId,
      skuId: shopCartItemDiscountsParam[scindex].shopCartItems[index].skuId
    }
  })
    .then(() => {
      shopCartItemDiscountsParam[scindex].shopCartItems[index].prodCount += prodCount
      shopCartItemDiscounts.value = shopCartItemDiscountsParam
      calTotalPrice() // 计算总价
      uni.hideLoading()
      http.getCartCount() // 重新计算购物车总数量
    })
}

/**
 * 删除购物车商品
 */
const onDelBasket = () => {
  const shopCartItemDiscountsParam = shopCartItemDiscounts.value
  const basketIds = []
  for (let i = 0; i < shopCartItemDiscountsParam.length; i++) {
    const cItems = shopCartItemDiscountsParam[i].shopCartItems
    for (let j = 0; j < cItems.length; j++) {
      if (cItems[j].checked) {
        basketIds.push(cItems[j].basketId)
      }
    }
  }
  if (!basketIds.length) {
    uni.showToast({
      title: '请选择商品',
      icon: 'none'
    })
  } else {
    uni.showModal({
      title: '',
      content: '确认要删除选中的商品吗？',
      confirmColor: '#A88847',
      success (res) {
        if (res.confirm) {
          uni.showLoading({
            mask: true
          })
          http.request({
            url: '/api/mall/cart/delete',
            method: 'POST',
            data: basketIds
          })
            .then(() => {
              uni.hideLoading()
              loadBasketData()
            })
        }
      }

    })
  }
}
</script>

<style scoped lang="scss">
@import "./basket.scss";
</style>
