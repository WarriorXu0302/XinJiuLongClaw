<template>
  <view class="container">
    <view class="order-detail">
      <view
        v-if="userAddrDto"
        class="delivery-addr"
      >
        <view class="user-info">
          <text class="item">
            {{ userAddrDto.receiver }}
          </text>
          <text class="item">
            {{ userAddrDto.mobile }}
          </text>
        </view>
        <view class="addr">
          {{ userAddrDto.province }}{{ userAddrDto.city }}{{ userAddrDto.area }}{{ userAddrDto.addr }}
        </view>
      </view>

      <!-- 商品信息 -->
      <view
        v-if="orderItemDtos"
        class="prod-item"
      >
        <block
          v-for="(item, index) in orderItemDtos"
          :key="index"
        >
          <view
            class="item-cont"
            :data-prodid="item.prodId"
            @tap="toProdPage"
          >
            <view class="prod-pic">
              <image :src="item.pic" />
            </view>
            <view class="prod-info">
              <view class="prodname">
                {{ item.prodName }}
              </view>
              <view class="prod-info-cont">
                <text class="number">
                  数量：{{ item.count || item.prodCount || item.quantity || 0 }}
                </text>
                <text class="info-item">
                  {{ item.skuName }}
                </text>
              </view>
              <view class="price-nums clearfix">
                <text class="prodprice">
                  <text class="symbol">
                    ￥
                  </text>
                  <text class="big-num">
                    {{ wxs.parsePrice(item.price)[0] }}
                  </text>
                  <text class="small-num">
                    .{{ wxs.parsePrice(item.price)[1] }}
                  </text>
                </text>
                <view class="btn-box" />
              </view>
            </view>
          </view>
        </block>
      </view>

      <!-- 配送员信息（接单后才显示）-->
      <view
        v-if="courier"
        class="order-msg courier-box"
      >
        <view class="msg-item">
          <view class="item courier-row">
            <text class="item-tit">
              配送员：
            </text>
            <text class="item-txt">
              {{ courier.nickname || '业务员' }}
            </text>
            <text
              class="courier-action"
              @tap="onCallCourier"
            >
              📞 拨打电话
            </text>
          </view>
          <view
            v-if="courier.mobile"
            class="item courier-row"
          >
            <text class="item-tit">
              手机号：
            </text>
            <text class="item-txt">
              {{ courier.mobile }}
            </text>
          </view>
          <view
            v-if="courier.wechatQrUrl || courier.alipayQrUrl"
            class="item courier-row courier-qr"
          >
            <text class="item-tit">
              收款码：
            </text>
            <text
              v-if="courier.wechatQrUrl"
              class="courier-qr-btn"
              @tap="onPreviewPayQr(courier.wechatQrUrl)"
            >
              微信
            </text>
            <text
              v-if="courier.alipayQrUrl"
              class="courier-qr-btn"
              @tap="onPreviewPayQr(courier.alipayQrUrl)"
            >
              支付宝
            </text>
          </view>
        </view>
      </view>

      <!-- 订单信息 -->
      <view class="order-msg">
        <view class="msg-item">
          <view class="item">
            <text class="item-tit">
              订单编号：
            </text>
            <text class="item-txt">
              {{ orderNumber }}
            </text>
          </view>
          <view class="item">
            <text class="item-tit">
              下单时间：
            </text>
            <text class="item-txt">
              {{ createTime }}
            </text>
          </view>
        </view>
        <view class="msg-item">
          <view class="item">
            <text class="item-tit">
              下单方式：
            </text>
            <text class="item-txt">
              提交订单
            </text>
          </view>
          <view class="item">
            <text class="item-tit">
              配送方式：
            </text>
            <text class="item-txt">
              普通配送
            </text>
          </view>
          <view class="item">
            <text
              v-if="!!remarks"
              class="item-tit"
            >
              订单备注：
            </text>
            <text class="item-txt remarks">
              {{ remarks }}
            </text>
          </view>
        </view>
      </view>

      <view class="order-msg">
        <view class="msg-item">
          <view class="item">
            <view class="item-tit">
              订单总额：
            </view>
            <view class="item-txt price">
              <text class="symbol">
                ￥
              </text>
              <text class="big-num">
                {{ wxs.parsePrice(total)[0] }}
              </text>
              <text class="small-num">
                .{{ wxs.parsePrice(total)[1] }}
              </text>
            </view>
          </view>
          <view class="item">
            <view class="item-tit">
              运费：
            </view>
            <view class="item-txt price">
              <text class="symbol">
                ￥
              </text>
              <text class="big-num">
                {{ wxs.parsePrice(transfee)[0] }}
              </text>
              <text class="small-num">
                .{{ wxs.parsePrice(transfee)[1] }}
              </text>
            </view>
          </view>
          <view class="item">
            <view class="item-tit">
              优惠券：
            </view>
            <view class="item-txt price">
              <text class="symbol">
                -￥
              </text>
              <text class="big-num">
                {{ wxs.parsePrice(reduceAmount)[0] }}
              </text>
              <text class="small-num">
                .{{ wxs.parsePrice(reduceAmount)[1] }}
              </text>
            </view>
          </view>
          <view class="item payment">
            <view class="item-txt price">
              实付款：
              <text class="symbol">
                ￥
              </text>
              <text class="big-num">
                {{ wxs.parsePrice(actualTotal)[0] }}
              </text>
              <text class="small-num">
                .{{ wxs.parsePrice(actualTotal)[1] }}
              </text>
            </view>
          </view>
        </view>
      </view>

      <!-- 底部栏：仅终态订单（已完成/已取消/坏账关单/已退款）显示软删按钮 -->
      <view
        v-if="isTerminalStatus"
        class="order-detail-footer"
      >
        <text
          class="dele-order"
          @tap="delOrderList"
        >
          删除订单
        </text>
      </view>
    </view>
  </view>
</template>

<script setup>
const wxs = number()

/**
 * 生命周期函数--监听页面加载
 */
onLoad((options) => {
  loadOrderDetail(options.orderNum)
})

/**
 * 跳转商品详情页
 * @param e
 */
const toProdPage = (e) => {
  const prodid = e.currentTarget.dataset.prodid
  uni.navigateTo({
    url: '/pages/prod/prod?prodid=' + prodid
  })
}

const remarks = ref('')
const orderItemDtos = ref([])
const reduceAmount = ref('')
const transfee = ref('')
const status = ref(0)
const actualTotal = ref(0)
const userAddrDto = ref(null)
const orderNumber = ref('')
const createTime = ref('')
const total = ref(0) // 商品总额
const courier = ref(null) // 配送员：{nickname, mobile, wechatQrUrl, alipayQrUrl}
const showPayQr = ref(false)
// 终态订单 = 可从列表软删（completed / cancelled / partial_closed / refunded）
const isTerminalStatus = computed(() => ['completed', 'cancelled', 'partial_closed', 'refunded'].includes(status.value))
/**
 * 加载订单数据
 */
const loadOrderDetail = (orderNum) => {
  uni.showLoading() // 加载订单详情
  http.request({
    url: '/api/mall/orders/' + orderNum,
    method: 'GET',
    data: {}
  })
    .then(({ data }) => {
      // 后端 MallOrderDetailVO 字段：orderNo/status/payAmount/totalAmount/createTime/address/items/...
      orderNumber.value = orderNum
      actualTotal.value = data.payAmount ?? data.actualTotal ?? 0
      userAddrDto.value = data.address || data.userAddrDto
      remarks.value = data.remarks
      orderItemDtos.value = data.items || data.orderItemDtos || []
      createTime.value = data.createTime
      status.value = data.status
      transfee.value = data.shippingFee ?? data.transfee ?? 0
      reduceAmount.value = data.discountAmount ?? data.reduceAmount ?? 0
      total.value = data.totalAmount ?? data.total ?? 0
      courier.value = data.courier || null
      uni.hideLoading()
    })
}

const onCallCourier = () => {
  if (!courier.value?.mobile) {
    uni.showToast({ title: '暂无配送员手机号', icon: 'none' })
    return
  }
  uni.makePhoneCall({ phoneNumber: courier.value.mobile })
}

const onPreviewPayQr = (url) => {
  if (!url) return
  uni.previewImage({ urls: [url], current: url })
}

/**
 * 删除已完成||已取消的订单
 */
const delOrderList = () => {
  uni.showModal({
    title: '',
    content: '确定要删除此订单吗？',
    confirmColor: '#A88847',
    success (res) {
      if (res.confirm) {
        uni.showLoading()
        http.request({
          url: '/api/mall/orders/' + orderNumber.value,
          method: 'DELETE'
        })
          .then(() => {
            uni.hideLoading()
            uni.showToast({
              title: res || '删除成功',
              icon: 'none'
            })
            setTimeout(() => {
              uni.redirectTo({
                url: '/pages/orderList/orderList'
              })
            }, 1000)
          })
      }
    }
  })
}
</script>

<style scoped lang="scss">
@use './order-detail.scss';
</style>
