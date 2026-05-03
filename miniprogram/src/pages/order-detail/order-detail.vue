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

      <!-- 退货状态显示（已申请 / 已批准 / 已退款 / 已驳回） -->
      <view
        v-if="returnReq"
        :class="['return-status', `return-status--${returnReq.status}`]"
      >
        <view class="return-status__head">
          退货申请
          <text :class="['return-status__tag', `return-status__tag--${returnReq.status}`]">
            {{ returnStatusLabel(returnReq.status) }}
          </text>
        </view>
        <view class="return-status__body">
          <text class="return-status__label">
            申请原因：
          </text>{{ returnReq.reason }}
        </view>
        <view
          v-if="returnReq.review_note"
          class="return-status__body"
        >
          <text class="return-status__label">
            审批备注：
          </text>{{ returnReq.review_note }}
        </view>
        <view
          v-if="returnReq.refund_amount"
          class="return-status__body"
        >
          <text class="return-status__label">
            退款金额：
          </text>¥{{ returnReq.refund_amount }}
        </view>
        <view
          v-if="returnReq.refunded_at"
          class="return-status__body"
        >
          <text class="return-status__label">
            退款到账：
          </text>{{ fmtRetDate(returnReq.refunded_at) }}（{{ refundMethodLabel(returnReq.refund_method) }}）
        </view>
      </view>

      <!-- 底部栏 -->
      <view
        v-if="canApplyReturn || isTerminalStatus"
        class="order-detail-footer"
      >
        <text
          v-if="canApplyReturn"
          class="action-btn action-btn--return"
          @tap="onApplyReturn"
        >
          申请退货
        </text>
        <text
          v-if="isTerminalStatus"
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

// 退货申请（完整后端：completed/partial_closed 可申；一个订单同时只能有一条活跃申请）
const returnReq = ref(null)
const canApplyReturn = computed(() => {
  if (!['completed', 'partial_closed'].includes(status.value)) return false
  // 已有 pending/approved/refunded 申请就不让重复申请；rejected 可以重申
  if (returnReq.value && ['pending', 'approved', 'refunded'].includes(returnReq.value.status)) return false
  return true
})

const returnStatusLabel = (s) => ({
  pending: '待审批',
  approved: '已通过，等待退款',
  refunded: '已退款',
  rejected: '已驳回'
}[s] || s)

const refundMethodLabel = (m) => ({
  cash: '现金',
  bank: '银行转账',
  wechat: '微信',
  alipay: '支付宝'
}[m] || m || '-')

const fmtRetDate = (iso) => {
  if (!iso) return ''
  const d = new Date(iso)
  if (isNaN(d.getTime())) return iso
  const pad = (n) => String(n).padStart(2, '0')
  return `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())} ${pad(d.getHours())}:${pad(d.getMinutes())}`
}

const loadReturnStatus = (orderNum) => {
  http.request({
    url: `/api/mall/orders/${orderNum}/return`,
    method: 'GET',
    hasCatch: true
  })
    .then(({ data }) => {
      returnReq.value = data // 可能是 null（没申请过）
    })
    .catch(() => {})
}

const onApplyReturn = () => {
  let reason = ''
  uni.showModal({
    title: '申请退货',
    content: '请详细说明退货原因，财务审核通过后会联系您安排退款',
    editable: true,
    placeholderText: '填写退货原因（必填）',
    success: (r) => {
      if (!r.confirm) return
      reason = (r.content || '').trim()
      if (!reason) {
        uni.showToast({ title: '请填写退货原因', icon: 'none' })
        return
      }
      submitReturn(reason)
    }
  })
}

const submitReturn = (reason) => {
  uni.showLoading({ title: '提交中…' })
  http.request({
    url: `/api/mall/orders/${orderNumber.value}/return`,
    method: 'POST',
    data: { reason }
  })
    .then(({ data }) => {
      uni.hideLoading()
      uni.showToast({ title: '退货申请已提交，等待审核', icon: 'success' })
      returnReq.value = data
    })
    .catch((e) => {
      uni.hideLoading()
      uni.showToast({ title: e?.detail || '提交失败', icon: 'none' })
    })
}
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
      // completed / partial_closed / refunded 时查退货记录（可能有历史 rejected，或当前 pending/approved）
      if (['completed', 'partial_closed', 'refunded'].includes(data.status)) {
        loadReturnStatus(orderNum)
      }
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

.return-status {
  margin: 24rpx;
  padding: 24rpx;
  background: #fff;
  border-radius: 16rpx;
  border-left: 8rpx solid #C9A961;

  &--pending { border-left-color: #faad14; }
  &--approved { border-left-color: #1890ff; }
  &--refunded { border-left-color: #52c41a; }
  &--rejected { border-left-color: #ff4d4f; }

  &__head {
    font-size: 30rpx;
    font-weight: 600;
    color: #0E0E0E;
    margin-bottom: 12rpx;
    display: flex;
    align-items: center;
    gap: 12rpx;
  }

  &__tag {
    font-size: 22rpx;
    padding: 4rpx 16rpx;
    border-radius: 20rpx;

    &--pending { background: rgba(250,173,20,0.15); color: #faad14; }
    &--approved { background: rgba(24,144,255,0.15); color: #1890ff; }
    &--refunded { background: rgba(82,196,26,0.15); color: #52c41a; }
    &--rejected { background: rgba(255,77,79,0.15); color: #ff4d4f; }
  }

  &__body {
    font-size: 24rpx;
    color: #555;
    line-height: 1.6;
    margin-top: 4rpx;
    word-break: break-all;
  }

  &__label {
    color: #999;
  }
}

.action-btn {
  display: inline-block;
  padding: 16rpx 40rpx;
  border-radius: 40rpx;
  font-size: 26rpx;
  margin-right: 16rpx;

  &--return {
    background: #fff;
    color: #ff4d4f;
    border: 2rpx solid #ff4d4f;
  }
}
</style>
