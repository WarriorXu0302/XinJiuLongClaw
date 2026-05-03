<template>
  <view class="container">
    <!-- 用户信息 -->
    <view
      v-if="isAuthInfo"
      class="userinfo"
    >
      <view class="userinfo-con">
        <view class="userinfo-avatar">
          <image
            :src="
              loginResult.pic
                ?
                  (loginResult.pic.indexOf('http') === -1 ? picDomain + loginResult.pic : loginResult.pic)
                :
                  '/static/images/icon/head04.png'
            "
          />
        </view>
        <view class="userinfo-name">
          <view>{{ loginResult.nickName ? loginResult.nickName : "用户昵称" }}</view>
        </view>
      </view>
    </view>

    <view
      v-if="!isAuthInfo"
      class="userinfo-none"
    >
      <view
        class="default-pic"
        @tap="toLogin"
      >
        <image src="@/static/images/icon/head04.png" />
      </view>
      <view
        class="none-login"
        @tap="toLogin"
      >
        <button class="unlogin">
          未登录
        </button>
        <button class="click-login">
          点击登录账号
        </button>
      </view>
    </view>
    <!-- end 用户信息 -->

    <view class="list-cont">
      <!-- 订单状态 -->
      <view class="total-order">
        <view class="order-tit">
          <text style="font-weight:bold">
            我的订单
          </text>
          <view
            class="checkmore"
            data-sts="0"
            @tap="toOrderListPage"
          >
            <text>查看全部</text>
            <text class="arrowhead" />
          </view>
        </view>
        <view class="procedure">
          <view
            class="items"
            data-sts="1"
            @tap="toOrderListPage"
          >
            <image src="@/static/images/icon/toPay.png" />
            <text>待支付</text>
            <text
              v-if="orderAmount.unPay>0"
              class="num-badge"
            >
              {{ orderAmount.unPay }}
            </text>
          </view>
          <view
            class="items"
            data-sts="2"
            @tap="toOrderListPage"
          >
            <image src="@/static/images/icon/toDelivery.png" />
            <text>待发货</text>
            <!-- 待发货数 = 未付（unPay）- 配送中（consignment）- 已完成（payed） ≈ assigned/等财务确认 -->
          </view>
          <view
            class="items"
            data-sts="3"
            @tap="toOrderListPage"
          >
            <image src="@/static/images/icon/toTake.png" />
            <text>待收货</text>
            <text
              v-if="orderAmount.consignment>0"
              class="num-badge"
            >
              {{ orderAmount.consignment }}
            </text>
          </view>
          <view
            class="items"
            data-sts="5"
            @tap="toOrderListPage"
          >
            <image src="@/static/images/icon/toComment.png" />
            <text>已完成</text>
            <text
              v-if="orderAmount.payed>0"
              class="num-badge"
            >
              {{ orderAmount.payed }}
            </text>
          </view>
        </view>
      </view>
      <!--end 订单状态 -->

      <view class="prod-col">
        <view
          class="col-item"
          @tap="myCollectionHandle"
        >
          <view
            v-if="loginResult"
            class="num"
          >
            {{ collectionCount }}
          </view>
          <view
            v-else
            class="num"
          >
            --
          </view>
          <view class="tit">
            我的收藏
          </view>
        </view>
        <view
          class="col-item"
          @tap="handleTips"
        >
          <view
            v-if="loginResult"
            class="num"
          >
            5
          </view>
          <view
            v-else
            class="num"
          >
            --
          </view>
          <view class="tit">
            我的消息
          </view>
        </view>
        <view
          class="col-item"
          @tap="handleTips"
        >
          <view
            v-if="loginResult"
            class="num"
          >
            3
          </view>
          <view
            v-else
            class="num"
          >
            --
          </view>
          <view class="tit">
            我的足迹
          </view>
        </view>
      </view>

      <view class="my-menu">
        <view
          class="memu-item"
          @tap="toNotifications"
        >
          <view class="i-name">
            <image src="@/static/images/icon/myAddr.png" />
            <text>消息通知</text>
            <text
              v-if="unreadCount > 0"
              class="notif-badge"
            >
              {{ unreadCount > 99 ? '99+' : unreadCount }}
            </text>
          </view>
          <view class="arrowhead" />
        </view>
        <view
          class="memu-item"
          @tap="toAddressList"
        >
          <view class="i-name">
            <image src="@/static/images/icon/myAddr.png" />
            <text>收货地址</text>
          </view>
          <view class="arrowhead" />
        </view>
      </view>
      <!--end 列表项 -->

      <view
        v-if="isAuthInfo"
        class="log-out"
        @tap="logout"
      >
        <view class="log-out-n">
          <text>退出登录</text>
        </view>
      </view>
    </view>
  </view>
</template>

<script setup>
const picDomain = import.meta.env.VITE_APP_RESOURCES_URL

const isAuthInfo = ref(false)
const loginResult = ref('')
const orderAmount = ref('')
/**
 * 生命周期函数--监听页面显示
 */
const unreadCount = ref(0)

const loadUnreadCount = () => {
  http.request({
    url: '/api/mall/workspace/notifications/unread-count',
    method: 'GET',
    hasCatch: true
  })
    .then(({ data }) => {
      unreadCount.value = data?.count || 0
    })
    .catch(() => { unreadCount.value = 0 })
}

onShow(() => {
  if (uni.getStorageSync('userType') === 'salesman') {
    uni.reLaunch({ url: '/pages/salesman-profile/salesman-profile' })
    return
  }
  loginResult.value = uni.getStorageSync('loginResult')
  isAuthInfo.value = !!loginResult.value
  // 加载订单数字
  if (isAuthInfo.value) {
    uni.showLoading()
    http.request({
      url: '/api/mall/orders/stats',
      method: 'GET',
      data: {}
    })
      .then(({ data }) => {
        uni.hideLoading()
        orderAmount.value = data
      })
    showCollectionCount()
    loadUnreadCount()
  }
})

const handleTips = () => {
  uni.showToast({
    icon: 'none',
    title: '该功能未开源'
  })
}
const toAddressList = () => {
  uni.navigateTo({
    url: '/pages/delivery-address/delivery-address'
  })
}

const toNotifications = () => {
  uni.navigateTo({ url: '/pages/notifications/notifications' })
}

const toOrderListPage = (e) => {
  const sts = e.currentTarget.dataset.sts
  uni.navigateTo({
    url: '/pages/orderList/orderList?sts=' + sts
  })
}

const collectionCount = ref(0)
/**
 * 查询所有的收藏量
 */
const showCollectionCount = () => {
  if (!uni.getStorageSync('Token')) {
    collectionCount.value = 0
    return
  }
  http.request({
    url: '/api/mall/collections/count',
    method: 'GET'
  }).then(({ data }) => {
    collectionCount.value = data?.total || 0
  }).catch(() => {
    collectionCount.value = 0
  })
}

/**
 * 我的收藏跳转
 */
const myCollectionHandle = () => {
  let url = '/pages/prod-classify/prod-classify?sts=5'
  const id = 0
  const title = '我的收藏商品'
  if (id) {
    url += '&tagid=' + id + '&title=' + title
  }
  uni.navigateTo({
    url
  })
}

/**
 * 去登陆
 */
const toLogin = () => {
  uni.navigateTo({
    url: '/pages/accountLogin/accountLogin'
  })
}

/**
 * 退出登录
 *
 * dontTrunLogin=true 让 http.js 在 401（token 已过期）时不弹"重新登录"模态
 * hasCatch=true 吃掉 4xx toast —— 退出本来就期望 token 无效，不应该报错
 * 跳转只走 .finally 里这一次 switchTab，避免和 http.js 的跳转互相 timeout
 */
const logout = () => {
  http.request({
    url: '/api/mall/auth/logout',
    method: 'POST',
    dontTrunLogin: true,
    hasCatch: true
  })
    .catch(() => {})
    .finally(() => {
      util.removeTabBadge()
      uni.removeStorageSync('loginResult')
      uni.removeStorageSync('Token')
      uni.removeStorageSync('RefreshToken')
      uni.removeStorageSync('hadLogin')
      uni.removeStorageSync('userType')
      uni.removeStorageSync('userId')
      uni.showToast({
        title: '已退出',
        icon: 'none'
      })
      orderAmount.value = ''
      setTimeout(() => {
        uni.switchTab({ url: '/pages/index/index' })
      }, 600)
    })
}
</script>

<style scoped lang="scss">
@use './user.scss';
</style>
